"""
MarketService — all market-data operations use the Yahoo Finance chart/search APIs
directly via httpx. yfinance is NOT used here because its internal HTTP calls
are blocked / return empty bodies in this environment.

Yahoo Finance endpoints used:
  Price history + metadata : /v8/finance/chart/{ticker}?range=Xd&interval=1d
  FX rates                 : same, ticker = "EURUSD=X" etc.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Optional, List

import httpx
from sqlalchemy.orm import Session

from ..models import Instrument, PriceHistory, FxRate, AssetClass, EtfProfile, EtfHolding, EtfSectorWeight, SecurityProfile

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_CHART_URL   = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
_CHART_URL_2 = "https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

FX_PAIRS = {
    "USD": "EURUSD=X",
    "GBP": "EURGBP=X",
    "CHF": "EURCHF=X",
    "JPY": "EURJPY=X",
    "SEK": "EURSEK=X",
    "NOK": "EURNOK=X",
    "DKK": "EURDKK=X",
    "CAD": "EURCAD=X",
    "AUD": "EURAUD=X",
}


# ── Low-level helpers ─────────────────────────────────────────────────────────

async def _fetch_chart(
    ticker: str,
    range_: str = "5d",
    interval: str = "1d",
    client: Optional[httpx.AsyncClient] = None,
    events: Optional[str] = None,
) -> Optional[dict]:
    """
    Fetch Yahoo Finance chart data for *ticker*.
    Returns the first ``result`` dict (contains ``meta``, ``timestamp``,
    ``indicators`` and, when ``events`` is set, ``events``) or None on failure.
    Falls back to query2 if query1 fails.
    """
    params = {"range": range_, "interval": interval, "includePrePost": "false"}
    if events:
        params["events"] = events
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=10.0)
    try:
        for base in (_CHART_URL, _CHART_URL_2):
            url = base.format(ticker=ticker)
            try:
                resp = await client.get(url, headers=_HEADERS, params=params)
                resp.raise_for_status()
                data = resp.json()
                results = (data.get("chart") or {}).get("result") or []
                if results:
                    return results[0]
            except Exception as exc:
                logger.debug(f"Chart API [{base}] failed for {ticker!r}: {exc}")
        logger.warning(f"No chart data for {ticker!r} (range={range_})")
        return None
    finally:
        if own_client:
            await client.aclose()


def _extract_dividends(result: dict) -> List[tuple]:
    """Return list of (ex_date, amount_per_share) from a chart result's events.
    Amount is the dividend per share in the security's own currency."""
    divs = ((result.get("events") or {}).get("dividends")) or {}
    out = []
    for node in divs.values():
        ts = node.get("date")
        amt = node.get("amount")
        if ts is None or amt is None:
            continue
        out.append((datetime.utcfromtimestamp(ts).date(), float(amt)))
    return sorted(out)


def _extract_prices(result: dict) -> List[tuple]:
    """Return list of (date, close_price) from a chart result dict, filtering nulls."""
    timestamps = result.get("timestamp") or []
    closes = (result.get("indicators") or {}).get("quote", [{}])[0].get("close") or []
    out = []
    for ts, price in zip(timestamps, closes):
        if price is None:
            continue
        d = datetime.utcfromtimestamp(ts).date()
        out.append((d, float(price)))
    return out


_QUOTE_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
_QUOTE_SUMMARY_URL_2 = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
_CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
_COOKIE_URL = "https://fc.yahoo.com"


async def _get_crumb(client: httpx.AsyncClient) -> Optional[str]:
    """Authenticate the client (cookie from fc.yahoo.com) and return a quoteSummary
    crumb. Yahoo's quoteSummary endpoint is crumb-gated; this is best-effort."""
    try:
        # getcrumb returns plain text and rejects "Accept: application/json" with 406
        crumb_headers = {**_HEADERS, "Accept": "*/*"}
        await client.get(_COOKIE_URL, headers=crumb_headers)
        resp = await client.get(_CRUMB_URL, headers=crumb_headers)
        crumb = (resp.text or "").strip()
        if not crumb or "{" in crumb:   # error JSON instead of a plain crumb
            return None
        return crumb
    except Exception as exc:
        logger.warning(f"Yahoo crumb fetch failed: {exc}")
        return None


async def _fetch_quote_summary(
    symbol: str, modules: List[str], client: httpx.AsyncClient, crumb: str
) -> Optional[dict]:
    """Fetch quoteSummary modules (assetProfile / topHoldings / fundProfile)."""
    params = {"modules": ",".join(modules), "crumb": crumb}
    for base in (_QUOTE_SUMMARY_URL, _QUOTE_SUMMARY_URL_2):
        try:
            resp = await client.get(base.format(ticker=symbol), headers=_HEADERS, params=params)
            data = resp.json()
            results = (data.get("quoteSummary") or {}).get("result") or []
            if results:
                return results[0]
        except Exception as exc:
            logger.debug(f"quoteSummary [{base}] failed for {symbol!r}: {exc}")
    return None


def _infer_asset_class(instrument_type: str) -> AssetClass:
    t = (instrument_type or "").upper()
    if t == "ETF":
        return AssetClass.ETF
    if t in ("BOND", "TBILL", "TBONDS"):
        return AssetClass.BOND
    if t == "CRYPTOCURRENCY":
        return AssetClass.CRYPTO
    return AssetClass.EQUITY


# ── Service ───────────────────────────────────────────────────────────────────

class MarketService:
    def __init__(self, db: Session):
        self.db = db
        self._sp_seen: set = set()   # symbols already cached in SecurityProfile this run

    # ── Read-only DB helpers ──────────────────────────────────────────────────

    def get_prices(self, instrument_id: int, period: str = "1Y") -> List[PriceHistory]:
        cutoff = self._period_cutoff(period)
        return (
            self.db.query(PriceHistory)
            .filter(PriceHistory.instrument_id == instrument_id, PriceHistory.date >= cutoff)
            .order_by(PriceHistory.date)
            .all()
        )

    def latest_price(self, instrument_id: int) -> Optional[float]:
        row = (
            self.db.query(PriceHistory)
            .filter(PriceHistory.instrument_id == instrument_id)
            .order_by(PriceHistory.date.desc())
            .first()
        )
        return row.close_price if row else None

    def latest_price_date(self, instrument_id: int) -> Optional[date]:
        row = (
            self.db.query(PriceHistory)
            .filter(PriceHistory.instrument_id == instrument_id)
            .order_by(PriceHistory.date.desc())
            .first()
        )
        return row.date if row else None

    def get_fx_rate_today(self, currency: str) -> float:
        if currency == "EUR":
            return 1.0
        today = date.today()
        row = (
            self.db.query(FxRate)
            .filter(FxRate.pair == currency.upper(), FxRate.date <= today)
            .order_by(FxRate.date.desc())
            .first()
        )
        if row:
            return row.rate
        # No stored rate → fall back to 1.0 (treats the price as already EUR). This
        # is wrong for a foreign currency; warn so it isn't a silent ~8% error.
        logger.warning(
            "No FX rate stored for %s — treating its prices as EUR (1.0). "
            "Trigger a price refresh to fetch FX rates.", currency.upper(),
        )
        return 1.0

    # ── FX rate for a specific date ───────────────────────────────────────────

    async def get_fx_rate_for_date(self, currency: str, d: date) -> float:
        if currency == "EUR":
            return 1.0
        pair_key = currency.upper()
        # DB cache
        row = (
            self.db.query(FxRate)
            .filter(FxRate.pair == pair_key, FxRate.date <= d)
            .order_by(FxRate.date.desc())
            .first()
        )
        if row:
            return row.rate
        # Fetch from Yahoo Finance
        yf_ticker = FX_PAIRS.get(pair_key)
        if not yf_ticker:
            return 1.0
        try:
            result = await _fetch_chart(yf_ticker, range_="7d")
            if result:
                prices = _extract_prices(result)
                if prices:
                    rate_date, rate = prices[-1]
                    self._upsert_fx_rate(rate_date, pair_key, rate)
                    self.db.commit()
                    return rate
        except Exception as exc:
            logger.warning(f"FX rate fetch failed for {currency} on {d}: {exc}")
        return 1.0

    def fx_history(self, currency: str) -> List[tuple]:
        """Full stored EUR/<currency> rate history as sorted [(date, rate)].

        Used to convert a price series to EUR at *each date's* rate (capturing
        FX drift), instead of a single constant rate. Empty for EUR.
        """
        if not currency or currency.upper() == "EUR":
            return []
        rows = (
            self.db.query(FxRate)
            .filter(FxRate.pair == currency.upper())
            .order_by(FxRate.date)
            .all()
        )
        return [(r.date, r.rate) for r in rows]

    async def backfill_historical_fx(
        self, currencies: Optional[List[str]] = None, range_: str = "10y", min_rows: int = 100
    ):
        """Fetch and store the FULL daily EUR/<currency> history for each currency.

        Without this only the latest rate is stored, so historical conversion would
        fall back to a constant rate (losing FX drift). Currencies that already have
        ``min_rows`` stored points are skipped, making this cheap to call repeatedly
        (startup, nightly refresh, on-demand for a new benchmark).
        """
        if currencies is None:
            currencies = [c[0] for c in self.db.query(Instrument.currency).distinct().all()]

        targets = []
        for cur in currencies:
            if not cur:
                continue
            cur = cur.upper()
            if cur == "EUR" or cur not in FX_PAIRS or cur in targets:
                continue
            existing = self.db.query(FxRate).filter(FxRate.pair == cur).count()
            if existing < min_rows:
                targets.append(cur)
        if not targets:
            return

        async with httpx.AsyncClient(timeout=20.0) as client:
            results = await asyncio.gather(
                *[_fetch_chart(FX_PAIRS[cur], range_=range_, client=client) for cur in targets],
                return_exceptions=True,
            )
        for cur, result in zip(targets, results):
            if isinstance(result, Exception) or not result:
                logger.warning(f"Historical FX backfill failed for {cur}: {result}")
                continue
            rows = _extract_prices(result)
            for rate_date, rate in rows:
                self._upsert_fx_rate(rate_date, cur, rate)
            logger.info(f"Historical FX backfilled for {cur}: {len(rows)} rows")
        self.db.commit()

    # ── Enrichment: sector/country (stocks) + look-through (ETFs) ──────────────

    async def enrich_all(self, only_missing: bool = True):
        """Enrich every instrument with sector/country (single securities) or
        look-through holdings + sector split + asset-class split (ETFs).

        Best-effort: Yahoo's quoteSummary is crumb-gated and occasionally fails, so
        results are cached in the DB and missing ones are retried on the next run.
        """
        instruments = self.db.query(Instrument).all()
        if not instruments:
            return
        self._sp_seen = {r[0] for r in self.db.query(SecurityProfile.symbol).all()}
        async with httpx.AsyncClient(timeout=15.0) as client:
            crumb = await _get_crumb(client)
            if not crumb:
                logger.warning("Enrichment skipped: could not obtain Yahoo crumb.")
                return
            enriched = 0
            for inst in instruments:
                if only_missing and self._is_enriched(inst):
                    continue
                try:
                    if await self._enrich_one(inst, client, crumb):
                        enriched += 1
                except Exception as exc:
                    logger.warning(f"Enrichment failed for {inst.ticker!r}: {exc}")
            self.db.commit()
            logger.info(f"Enrichment complete: {enriched} instruments updated.")

    def _is_enriched(self, inst: Instrument) -> bool:
        ac = inst.asset_class
        if ac == AssetClass.ETF:
            return self.db.query(EtfProfile).filter(EtfProfile.instrument_id == inst.id).first() is not None
        if ac in (AssetClass.EQUITY, AssetClass.BOND, AssetClass.REAL_ESTATE):
            return bool(inst.sector)
        return True  # crypto/commodity/cash need no external enrichment

    async def enrich_instrument(self, instrument_id: int) -> bool:
        inst = self.db.query(Instrument).filter(Instrument.id == instrument_id).first()
        if not inst:
            return False
        self._sp_seen = {r[0] for r in self.db.query(SecurityProfile.symbol).all()}
        async with httpx.AsyncClient(timeout=15.0) as client:
            crumb = await _get_crumb(client)
            if not crumb:
                return False
            ok = await self._enrich_one(inst, client, crumb)
            self.db.commit()
            return ok

    async def _enrich_one(self, inst: Instrument, client: httpx.AsyncClient, crumb: str) -> bool:
        ac = inst.asset_class
        if ac == AssetClass.ETF:
            return await self._enrich_etf(inst, client, crumb)
        if ac in (AssetClass.EQUITY, AssetClass.BOND, AssetClass.REAL_ESTATE):
            return await self._enrich_security(inst, client, crumb)
        return False

    async def _enrich_security(self, inst: Instrument, client, crumb: str) -> bool:
        result = await _fetch_quote_summary(inst.ticker, ["assetProfile"], client, crumb)
        ap = (result or {}).get("assetProfile") or {}
        sector = ap.get("sector")
        country = ap.get("country")
        if sector:
            inst.sector = sector
        if country:
            inst.country = country
        return bool(sector or country)

    @staticmethod
    def _raw(node) -> float:
        return float((node or {}).get("raw", 0.0)) if isinstance(node, dict) else 0.0

    async def _enrich_etf(self, inst: Instrument, client, crumb: str) -> bool:
        result = await _fetch_quote_summary(inst.ticker, ["topHoldings", "fundProfile"], client, crumb)
        if not result:
            return False
        th = result.get("topHoldings") or {}
        fp = result.get("fundProfile") or {}
        category = fp.get("categoryName")

        equity = self._raw(th.get("stockPosition")) + self._raw(th.get("preferredPosition")) + self._raw(th.get("convertiblePosition"))
        bond = self._raw(th.get("bondPosition"))
        cash = self._raw(th.get("cashPosition"))
        other = self._raw(th.get("otherPosition"))
        commodity = 0.0
        if category and any(k in category.lower() for k in ("commodit", "gold", "precious", "metal")):
            commodity, other = other or 1.0, 0.0

        if equity + bond + cash + other + commodity <= 0:
            return False

        # Asset-class split
        self.db.query(EtfProfile).filter(EtfProfile.instrument_id == inst.id).delete()
        self.db.add(EtfProfile(
            instrument_id=inst.id, equity_pct=equity, bond_pct=bond,
            commodity_pct=commodity, cash_pct=cash, other_pct=other,
            category=category, updated_at=datetime.utcnow(),
        ))

        # Top holdings (look-through)
        self.db.query(EtfHolding).filter(EtfHolding.etf_id == inst.id).delete()
        holding_symbols = []
        for h in (th.get("holdings") or []):
            w = self._raw(h.get("holdingPercent"))
            if w > 0:
                sym = h.get("symbol") or None
                self.db.add(EtfHolding(
                    etf_id=inst.id, symbol=sym,
                    name=h.get("holdingName") or sym or "?", weight=w,
                ))
                if sym:
                    holding_symbols.append(sym)

        # Resolve & cache the country of each underlying holding (for country look-through)
        for sym in holding_symbols:
            if sym in self._sp_seen:
                continue
            self._sp_seen.add(sym)
            sub = await _fetch_quote_summary(sym, ["assetProfile"], client, crumb)
            country = ((sub or {}).get("assetProfile") or {}).get("country")
            self.db.add(SecurityProfile(symbol=sym, country=country, updated_at=datetime.utcnow()))

        # Sector breakdown
        self.db.query(EtfSectorWeight).filter(EtfSectorWeight.etf_id == inst.id).delete()
        for entry in (th.get("sectorWeightings") or []):
            for key, node in entry.items():
                w = self._raw(node)
                if w > 0:
                    self.db.add(EtfSectorWeight(etf_id=inst.id, sector_key=key, weight=w))
        return True

    # ── Instrument lookup (metadata only) ────────────────────────────────────

    async def lookup_instrument(
        self, isin: Optional[str] = None, ticker: Optional[str] = None
    ) -> Optional[dict]:
        """Resolve instrument info from Yahoo Finance chart API."""
        search_ticker = ticker or isin
        if not search_ticker:
            return None
        try:
            result = await _fetch_chart(search_ticker, range_="5d")
            if not result:
                return None
            meta = result.get("meta") or {}
            market_price = meta.get("regularMarketPrice")
            if market_price is None:
                return None
            return {
                "ticker":      meta.get("symbol", search_ticker),
                "name":        meta.get("longName") or meta.get("shortName") or search_ticker,
                "currency":    meta.get("currency", "USD"),
                "isin":        isin,
                "sector":      None,
                "country":     None,
                "asset_class": _infer_asset_class(meta.get("instrumentType", "")),
            }
        except Exception as exc:
            logger.warning(f"Instrument lookup failed for {search_ticker!r}: {exc}")
            return None

    # ── get_or_create_instrument ──────────────────────────────────────────────

    async def get_or_create_instrument(
        self,
        isin: Optional[str] = None,
        ticker: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Optional[Instrument]:
        # 1. Try existing by ISIN
        if isin:
            inst = self.db.query(Instrument).filter(Instrument.isin == isin).first()
            if inst:
                # If caller supplies a different ticker the user explicitly corrected it → update
                if ticker and ticker.strip() and ticker.strip() != inst.ticker:
                    logger.info(f"Updating ticker for ISIN {isin}: {inst.ticker!r} → {ticker.strip()!r}")
                    inst.ticker = ticker.strip()
                    self.db.commit()
                    self.db.refresh(inst)
                return inst
        # 2. Try existing by ticker
        if ticker:
            inst = self.db.query(Instrument).filter(Instrument.ticker == ticker).first()
            if inst:
                return inst
        # 3. Try Yahoo Finance
        info = await self.lookup_instrument(isin=isin, ticker=ticker)
        if info:
            inst = Instrument(
                ticker=info["ticker"],
                isin=isin,
                name=info["name"],
                currency=info["currency"],
                asset_class=info["asset_class"],
                sector=info.get("sector"),
                country=info.get("country"),
            )
        elif name and ticker:
            inst = Instrument(ticker=ticker, isin=isin, name=name, currency="EUR")
        else:
            return None

        self.db.add(inst)
        self.db.commit()
        self.db.refresh(inst)
        return inst

    # ── Price refresh ─────────────────────────────────────────────────────────

    async def refresh_all_prices(self):
        """Refresh latest prices for all instruments and FX rates."""
        instruments = self.db.query(Instrument).all()
        if not instruments:
            return

        # Refresh FX rates first (latest), then ensure full history for conversion
        await self._refresh_fx_rates()
        await self.backfill_historical_fx()
        # Enrich sector/country/look-through for any instrument still missing it
        await self.enrich_all(only_missing=True)

        # Fetch prices in parallel
        async with httpx.AsyncClient(timeout=15.0) as client:
            tasks = [
                _fetch_chart(inst.ticker, range_="5d", client=client)
                for inst in instruments
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        updated = 0
        for inst, result in zip(instruments, results):
            if isinstance(result, Exception) or result is None:
                logger.warning(f"Price fetch failed for {inst.ticker!r}: {result}")
                continue
            prices = _extract_prices(result)
            if not prices:
                continue
            price_date, close = prices[-1]
            self._upsert_price(inst.id, price_date, close, inst.currency)
            updated += 1

        self.db.commit()
        logger.info(f"Prices updated for {updated}/{len(instruments)} instruments.")

    async def fetch_historical_prices(self, instrument_id: int, period: str = "5y"):
        """Fetch full price history for a single instrument."""
        inst = self.db.query(Instrument).filter(Instrument.id == instrument_id).first()
        if not inst:
            return

        # Map internal period strings to Yahoo Finance range strings
        yf_range = {
            "1M": "1mo", "3M": "3mo", "6M": "6mo",
            "YTD": "ytd", "1Y": "1y", "3Y": "3y",
            "5Y": "5y", "All": "10y",
        }.get(period, "5y")

        result = await _fetch_chart(inst.ticker, range_=yf_range)
        if not result:
            logger.warning(f"No historical data for {inst.ticker!r}")
            return

        prices = _extract_prices(result)
        for price_date, close in prices:
            self._upsert_price(inst.id, price_date, close, inst.currency)
        self.db.commit()
        logger.info(f"Historical prices loaded for {inst.ticker!r}: {len(prices)} rows")

    async def fetch_dividend_history(self, ticker: str, range_: str = "10y") -> List[tuple]:
        """Fetch the dividend (ex-date, amount-per-share) history for a ticker
        from Yahoo. Amount is per share, in the security's own currency."""
        result = await _fetch_chart(ticker, range_=range_, interval="1d", events="div")
        if not result:
            return []
        return _extract_dividends(result)

    # ── Instrument price chart ────────────────────────────────────────────────

    async def get_price_chart(self, instrument_id: int, period: str) -> list:
        """
        Return [{date, price}] for the instrument.

        Serves from DB when the stored data covers at least 80 % of the requested
        window (oldest stored row ≤ cutoff + 30 days grace).  Otherwise fetches
        the full history from Yahoo Finance, persists it, then returns from DB so
        subsequent requests are instant.
        """
        from datetime import timedelta

        yf_range = {
            "YTD": "ytd", "1A": "1y", "3A": "3y",
            "5A": "5y", "10A": "10y", "Max": "max",
        }.get(period, "1y")

        today = date.today()
        cutoff_map = {
            "YTD": date(today.year, 1, 1),
            "1A":  today - timedelta(days=365),
            "3A":  today - timedelta(days=365 * 3),
            "5A":  today - timedelta(days=365 * 5),
            "10A": today - timedelta(days=365 * 10),
            "Max": date(2000, 1, 1),
        }
        cutoff = cutoff_map.get(period, today - timedelta(days=365))

        rows = (
            self.db.query(PriceHistory)
            .filter(PriceHistory.instrument_id == instrument_id, PriceHistory.date >= cutoff)
            .order_by(PriceHistory.date)
            .all()
        )

        # Good coverage: oldest row is within 30 days of the period start
        if rows and rows[0].date <= cutoff + timedelta(days=30):
            return [{"date": r.date.isoformat(), "price": r.close_price} for r in rows]

        # Insufficient coverage → fetch full history from Yahoo, persist, re-read
        inst = self.db.query(Instrument).filter(Instrument.id == instrument_id).first()
        if not inst:
            # Return whatever partial data we have
            return [{"date": r.date.isoformat(), "price": r.close_price} for r in rows]

        logger.info(f"Fetching historical prices for {inst.ticker!r} (period={period})")
        result = await _fetch_chart(inst.ticker, range_=yf_range)
        if result:
            prices = _extract_prices(result)
            for price_date, close in prices:
                self._upsert_price(inst.id, price_date, close, inst.currency)
            if prices:
                self.db.commit()
                logger.info(f"Cached {len(prices)} price points for {inst.ticker!r}")

            # Re-read from DB so we return exactly what was stored
            rows = (
                self.db.query(PriceHistory)
                .filter(PriceHistory.instrument_id == instrument_id, PriceHistory.date >= cutoff)
                .order_by(PriceHistory.date)
                .all()
            )
            if rows:
                return [{"date": r.date.isoformat(), "price": r.close_price} for r in rows]

        # Final fallback: return whatever partial DB rows we had
        return [{"date": r.date.isoformat(), "price": r.close_price} for r in rows]

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _refresh_fx_rates(self):
        today = date.today()
        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = {
                currency: _fetch_chart(yf_ticker, range_="5d", client=client)
                for currency, yf_ticker in FX_PAIRS.items()
            }
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for currency, result in zip(tasks.keys(), results):
            if isinstance(result, Exception) or result is None:
                continue
            prices = _extract_prices(result)
            if prices:
                rate_date, rate = prices[-1]
                self._upsert_fx_rate(rate_date, currency, rate)

        self.db.commit()

    def _upsert_price(self, instrument_id: int, d: date, price: float, currency: str):
        row = self.db.query(PriceHistory).filter(
            PriceHistory.instrument_id == instrument_id,
            PriceHistory.date == d,
        ).first()
        if row:
            row.close_price = price
        else:
            self.db.add(PriceHistory(
                instrument_id=instrument_id, date=d,
                close_price=price, currency=currency,
            ))

    def _upsert_fx_rate(self, d: date, pair: str, rate: float):
        row = self.db.query(FxRate).filter(FxRate.date == d, FxRate.pair == pair).first()
        if row:
            row.rate = rate
        else:
            self.db.add(FxRate(date=d, pair=pair, rate=rate))

    @staticmethod
    def _period_cutoff(period: str) -> date:
        today = date.today()
        mapping = {
            "1M": 30, "3M": 91, "6M": 182,
            "YTD": (today - date(today.year, 1, 1)).days,
            "1Y": 365, "3Y": 365 * 3, "5Y": 365 * 5, "All": 365 * 30,
        }
        days = mapping.get(period, 365)
        return today - timedelta(days=days)

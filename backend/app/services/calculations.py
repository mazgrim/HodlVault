"""
Financial calculations: P&L, TWR, Sharpe, Drawdown, HHI.

TWR (Time-Weighted Return): chains sub-period returns to eliminate cash-flow distortion.
Sharpe = (portfolio_return - risk_free_rate) / annualised_volatility
HHI (Herfindahl-Hirschman Index): sum of squared weights — 0 = fully diversified, 1 = single holding.
"""
import os
import math
import time
import bisect
import threading
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .. import models, schemas
from ..models import (
    Transaction, Portfolio, Instrument, PriceHistory, DividendEvent, FxRate, TransactionType,
    DividendType, DividendSource, EtfProfile, EtfHolding, EtfSectorWeight, EtfRegionWeight, SecurityProfile, AssetClass,
)
from .market import MarketService
from . import taxonomy

RISK_FREE_RATE = float(os.getenv("RISK_FREE_RATE", 0.03))

# ── Short-TTL series cache ──────────────────────────────────────────────────────
# A single Performance page load fires several endpoints (Sharpe, monthly returns,
# drawdown, cumulative) that each rebuild the same heavy value/TWR series — and the
# browser fires them concurrently (doubled in dev by React StrictMode). Recomputing
# 6-8 times in parallel on a single-process backend strangles latency. This cache
# coalesces identical concurrent/near-simultaneous computations into one. The TTL is
# short so freshly added transactions / refreshed prices show up almost immediately.
_SERIES_CACHE: Dict[tuple, Tuple[float, object]] = {}
_SERIES_LOCKS: Dict[tuple, threading.Lock] = defaultdict(threading.Lock)
_SERIES_TTL = float(os.getenv("SERIES_CACHE_TTL", 10))


def _cached_series(key: tuple, compute):
    """Return a cached result for *key* if fresh, else compute it. A per-key lock
    makes concurrent identical requests wait for the first computation and reuse it,
    instead of all recomputing at once."""
    now = time.monotonic()
    hit = _SERIES_CACHE.get(key)
    if hit and now - hit[0] < _SERIES_TTL:
        return hit[1]
    with _SERIES_LOCKS[key]:
        hit = _SERIES_CACHE.get(key)
        if hit and time.monotonic() - hit[0] < _SERIES_TTL:
            return hit[1]
        result = compute()
        _SERIES_CACHE[key] = (time.monotonic(), result)
        return result


def _user_portfolio_ids(user_id: int, db: Session, portfolio_id: Optional[int] = None) -> List[int]:
    q = db.query(Portfolio.id).filter(Portfolio.user_id == user_id)
    if portfolio_id:
        q = q.filter(Portfolio.id == portfolio_id)
    return [r[0] for r in q.all()]


# ── Dashboard Calculations ────────────────────────────────────────────────────

class DashboardCalculator:
    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.market = MarketService(db)

    def _build_fx_lookup(self, currencies):
        """Return fn(currency, date) -> FX divisor (foreign units per 1 EUR) using
        the stored historical rate on-or-before that date.

        This converts each day's price at *that day's* rate, so EUR returns reflect
        currency drift. Falls back to the latest rate when no history is available
        yet (e.g. before the first FX backfill), degrading to the old behaviour
        rather than failing.
        """
        hist: Dict[str, List[Tuple[date, float]]] = {}
        keys: Dict[str, List[date]] = {}
        latest: Dict[str, float] = {}
        for cur in currencies:
            if not cur or cur == "EUR":
                continue
            series = self.market.fx_history(cur)
            hist[cur] = series
            keys[cur] = [d for d, _ in series]
            latest[cur] = self.market.get_fx_rate_today(cur) or 1.0

        def fx_at(cur: str, d: date) -> float:
            if not cur or cur == "EUR":
                return 1.0
            series = hist.get(cur)
            if not series:
                return latest.get(cur, 1.0)
            i = bisect.bisect_right(keys[cur], d) - 1
            if i >= 0:
                return series[i][1]
            return series[0][1]  # date precedes history → earliest known rate

        return fx_at

    def open_positions(self, portfolio_id: Optional[int] = None) -> List[schemas.PositionRow]:
        pids = _user_portfolio_ids(self.user_id, self.db, portfolio_id)
        if not pids:
            return []

        txs = (
            self.db.query(Transaction)
            .filter(Transaction.portfolio_id.in_(pids))
            .order_by(Transaction.date)
            .all()
        )

        # Build position book: net quantity, weighted avg cost in EUR
        book: Dict[int, dict] = {}
        realized_pnl: Dict[int, float] = {}

        for tx in txs:
            iid = tx.instrument_id
            if iid not in book:
                book[iid] = {"qty": 0.0, "cost_eur": 0.0, "instrument": tx.instrument}
                realized_pnl[iid] = 0.0

            price_eur = tx.price / tx.fx_rate if tx.fx_rate else tx.price
            fees_eur = tx.fees / tx.fx_rate if tx.fx_rate else tx.fees

            if tx.type == TransactionType.BUY:
                total_cost = price_eur * tx.quantity + fees_eur
                book[iid]["cost_eur"] += total_cost
                book[iid]["qty"] += tx.quantity
            else:  # SELL
                if book[iid]["qty"] > 0:
                    avg = book[iid]["cost_eur"] / book[iid]["qty"]
                    proceeds = price_eur * tx.quantity - fees_eur
                    realized_pnl[iid] += proceeds - avg * tx.quantity
                    book[iid]["cost_eur"] -= avg * tx.quantity
                    book[iid]["qty"] -= tx.quantity

        positions = []
        total_market_value = 0.0

        for iid, pos in book.items():
            if pos["qty"] < 0.0001:
                continue
            inst: Instrument = pos["instrument"]
            raw_price = self.market.latest_price(iid)
            if raw_price is None:
                continue
            fx = self.market.get_fx_rate_today(inst.currency)
            current_price_eur = raw_price / fx if fx else raw_price

            market_value = current_price_eur * pos["qty"]
            avg_cost = pos["cost_eur"] / pos["qty"] if pos["qty"] else 0
            upnl = market_value - pos["cost_eur"]
            upnl_pct = (upnl / pos["cost_eur"] * 100) if pos["cost_eur"] else 0

            total_market_value += market_value
            positions.append({
                "instrument_id": iid,
                "ticker": inst.ticker,
                "name": inst.name,
                "isin": inst.isin,
                "asset_class": inst.asset_class.value,
                "currency": inst.currency,
                "quantity": round(pos["qty"], 6),
                "avg_cost": round(avg_cost, 4),
                "current_price": round(current_price_eur, 4),
                "current_price_orig": round(raw_price, 4),
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(upnl, 2),
                "unrealized_pnl_pct": round(upnl_pct, 2),
                "weight_pct": 0.0,
                "total_invested": round(pos["cost_eur"], 2),
            })

        # Compute weights
        for p in positions:
            p["weight_pct"] = round(p["market_value"] / total_market_value * 100, 2) if total_market_value else 0

        return [schemas.PositionRow(**p) for p in sorted(positions, key=lambda x: -x["market_value"])]

    def kpis(self, portfolio_id: Optional[int] = None) -> schemas.DashboardKPIs:
        positions = self.open_positions(portfolio_id)
        pids = _user_portfolio_ids(self.user_id, self.db, portfolio_id)

        total_value = sum(p.market_value for p in positions)
        total_invested = sum(p.total_invested for p in positions)
        unrealized_pnl = sum(p.unrealized_pnl for p in positions)
        unrealized_pnl_pct = (unrealized_pnl / total_invested * 100) if total_invested else 0

        # Realized P&L: closed-trade gains + cashed dividends/coupons
        realized_trade_pnl = self._calc_realized_pnl(pids)
        realized_dividends = self._calc_realized_dividends(pids)
        realized_pnl = realized_trade_pnl + realized_dividends

        # Portfolio age
        first_tx = (
            self.db.query(Transaction)
            .filter(Transaction.portfolio_id.in_(pids))
            .order_by(Transaction.date)
            .first()
        )
        age_days = (date.today() - first_tx.date).days if first_tx else 0

        # Annualised return = geometric TWR (cash-flow free), the SAME basis used on
        # the Performance and Benchmark pages, so all three agree. Returns None for
        # portfolios with < ~90 days of history, where annualising a tiny window
        # produces meaningless blow-ups (e.g. +5% over 10 days → +450%).
        ann_return = self._annualized_twr(portfolio_id, age_days)

        return schemas.DashboardKPIs(
            total_value=round(total_value, 2),
            total_invested=round(total_invested, 2),
            unrealized_pnl=round(unrealized_pnl, 2),
            unrealized_pnl_pct=round(unrealized_pnl_pct, 2),
            realized_pnl=round(realized_pnl, 2),
            realized_trade_pnl=round(realized_trade_pnl, 2),
            realized_dividends=round(realized_dividends, 2),
            total_pnl=round(unrealized_pnl + realized_pnl, 2),
            annualized_return=round(ann_return * 100, 2) if ann_return is not None else None,
            portfolio_age_days=age_days,
            as_of_date=date.today(),
        )

    def portfolio_instruments(self, portfolio_id: Optional[int] = None) -> List[dict]:
        """Instruments ever traded in the portfolio (for the what-if checkboxes)."""
        pids = _user_portfolio_ids(self.user_id, self.db, portfolio_id)
        if not pids:
            return []
        rows = (
            self.db.query(Instrument.id, Instrument.ticker, Instrument.name)
            .join(Transaction, Transaction.instrument_id == Instrument.id)
            .filter(Transaction.portfolio_id.in_(pids))
            .distinct()
            .all()
        )
        return [
            {"instrument_id": r[0], "ticker": r[1], "name": r[2]}
            for r in sorted(rows, key=lambda x: (x[2] or "").lower())
        ]

    def invested_flows(
        self, portfolio_id: Optional[int], after: date, through: date,
        exclude_instrument_ids: Optional[List[int]] = None,
    ) -> List[Tuple[date, float]]:
        """External cash flows in (after, through] as (date, signed EUR): a BUY is
        positive (cash invested), a SELL negative (cash returned). Instruments in
        *exclude_instrument_ids* are dropped (the 'as if never bought' what-if)."""
        pids = _user_portfolio_ids(self.user_id, self.db, portfolio_id)
        if not pids:
            return []
        q = self.db.query(Transaction).filter(
            Transaction.portfolio_id.in_(pids),
            Transaction.date > after,
            Transaction.date <= through,
        )
        if exclude_instrument_ids:
            q = q.filter(~Transaction.instrument_id.in_(exclude_instrument_ids))
        flows: List[Tuple[date, float]] = []
        for tx in q.order_by(Transaction.date).all():
            price_eur = tx.price / tx.fx_rate if tx.fx_rate else tx.price
            fees_eur = tx.fees / tx.fx_rate if tx.fx_rate else tx.fees
            if tx.type == TransactionType.BUY:
                flows.append((tx.date, price_eur * tx.quantity + fees_eur))
            else:
                flows.append((tx.date, -(price_eur * tx.quantity - fees_eur)))
        return flows

    def _net_flow_eur(self, pids: List[int], after: date, through: date) -> float:
        """Net cash invested (buys cost − sells proceeds, in EUR) for transactions
        dated in (after, through]. Used to strip contributions out of a value change."""
        txs = (
            self.db.query(Transaction)
            .filter(
                Transaction.portfolio_id.in_(pids),
                Transaction.date > after,
                Transaction.date <= through,
            )
            .all()
        )
        flow = 0.0
        for tx in txs:
            price_eur = tx.price / tx.fx_rate if tx.fx_rate else tx.price
            fees_eur = tx.fees / tx.fx_rate if tx.fx_rate else tx.fees
            if tx.type == TransactionType.BUY:
                flow += price_eur * tx.quantity + fees_eur
            else:
                flow -= price_eur * tx.quantity - fees_eur
        return flow

    def _annualized_twr(self, portfolio_id: Optional[int], age_days: int) -> Optional[float]:
        """Annualised geometric TWR over the full history, or None when there isn't
        enough history (< ~90 days) to annualise meaningfully."""
        if age_days < 90:
            return None
        twr = self.portfolio_twr_chart(portfolio_id, "All")
        if len(twr) < 2:
            return None
        start_v, end_v = twr[0][1], twr[-1][1]
        span_days = (twr[-1][0] - twr[0][0]).days
        if start_v <= 0 or end_v <= 0 or span_days < 90:
            return None
        try:
            return (end_v / start_v) ** (365 / span_days) - 1
        except (OverflowError, ValueError, ZeroDivisionError):
            return None

    def portfolio_chart(
        self, portfolio_id: Optional[int] = None, period: str = "1Y",
        exclude_instrument_ids: Optional[List[int]] = None,
    ) -> schemas.PortfolioChartResponse:
        key = ("chart", self.user_id, portfolio_id, period, tuple(sorted(exclude_instrument_ids or ())))
        return _cached_series(key, lambda: self._portfolio_chart_compute(portfolio_id, period, exclude_instrument_ids))

    def _portfolio_chart_compute(
        self, portfolio_id: Optional[int] = None, period: str = "1Y",
        exclude_instrument_ids: Optional[List[int]] = None,
    ) -> schemas.PortfolioChartResponse:
        """Approximate portfolio value series by summing position values day by day."""
        pids = _user_portfolio_ids(self.user_id, self.db, portfolio_id)
        if not pids:
            return schemas.PortfolioChartResponse(points=[])

        cutoff = MarketService._period_cutoff(period)

        # Pre-load ALL transactions (needed to replay opening positions before cutoff)
        all_txs = (
            self.db.query(Transaction)
            .filter(Transaction.portfolio_id.in_(pids))
            .order_by(Transaction.date)
            .all()
        )
        if exclude_instrument_ids:
            excl = set(exclude_instrument_ids)
            all_txs = [t for t in all_txs if t.instrument_id not in excl]
        if not all_txs:
            return schemas.PortfolioChartResponse(points=[])

        inst_ids = list({t.instrument_id for t in all_txs})  # all instruments ever held
        if not inst_ids:
            return schemas.PortfolioChartResponse(points=[])

        # First transaction date — chart never starts before the first buy
        first_tx_date = all_txs[0].date
        # For non-All periods the chart window may start later than first_tx
        chart_start = max(cutoff, first_tx_date)

        # Get price series for all instruments (from chart_start)
        prices: Dict[int, Dict[date, float]] = {}
        for iid in inst_ids:
            rows = self.db.query(PriceHistory).filter(
                PriceHistory.instrument_id == iid,
                PriceHistory.date >= chart_start,
            ).order_by(PriceHistory.date).all()
            prices[iid] = {r.date: r.close_price for r in rows}

        # Build date axis: union of all price dates from chart_start onward
        all_dates = sorted({d for pd in prices.values() for d in pd})
        if not all_dates:
            return schemas.PortfolioChartResponse(points=[])

        # Pre-compute sorted price lists for efficient "last known price" lookups
        sorted_prices: Dict[int, List[Tuple[date, float]]] = {
            iid: sorted(pd.items()) for iid, pd in prices.items()
        }

        # Historical FX: each day's price is converted at THAT day's rate.
        inst_currencies: Dict[int, str] = {}
        for iid in inst_ids:
            inst = self.db.query(Instrument).filter(Instrument.id == iid).first()
            if inst:
                inst_currencies[iid] = inst.currency
        fx_at = self._build_fx_lookup(set(inst_currencies.values()))

        # Apply transactions with a date-ordered pointer: at each chart date we apply
        # every transaction with date <= chart_date not yet applied. This counts trades
        # whose date isn't on the price axis (weekends/holidays) at the next valuation,
        # instead of silently dropping them.
        sorted_txs = all_txs  # already ordered by Transaction.date
        running_book: Dict[int, float] = defaultdict(float)
        ti = 0

        # Iterate chart dates
        points = []
        for chart_date in all_dates:
            while ti < len(sorted_txs) and sorted_txs[ti].date <= chart_date:
                tx = sorted_txs[ti]
                if tx.type == TransactionType.BUY:
                    running_book[tx.instrument_id] += tx.quantity
                else:
                    running_book[tx.instrument_id] -= tx.quantity
                ti += 1

            total = 0.0
            for iid, qty in running_book.items():
                if qty <= 0:
                    continue
                price = prices.get(iid, {}).get(chart_date)
                if price is None:
                    sp = sorted_prices.get(iid, [])
                    # Last known price on or before chart_date
                    before = [v for k, v in sp if k <= chart_date]
                    if before:
                        price = before[-1]
                    else:
                        # No history before chart_date → use earliest available price
                        price = sp[0][1] if sp else 0.0
                currency = inst_currencies.get(iid, "EUR")
                fx = fx_at(currency, chart_date)
                price_eur = price / fx if fx and currency != "EUR" else price
                total += qty * price_eur

            points.append(schemas.PortfolioChartPoint(date=chart_date, value=round(total, 2)))

        # Market change over the shown window: last vs first value, with cash flows
        # inside the window netted out so a contribution isn't read as a gain.
        change = change_pct = None
        if len(points) >= 2:
            first, last = points[0], points[-1]
            flow = self._net_flow_eur(pids, first.date, last.date)
            change = round((last.value - first.value) - flow, 2)
            change_pct = round(change / first.value * 100, 2) if first.value else None

        return schemas.PortfolioChartResponse(points=points, change=change, change_pct=change_pct)

    def analysis(self, portfolio_id: Optional[int] = None) -> schemas.AnalysisResponse:
        positions = self.open_positions(portfolio_id)
        total = sum(p.market_value for p in positions)

        by_asset: Dict[str, float] = defaultdict(float)
        by_sector: Dict[str, float] = defaultdict(float)
        by_country: Dict[str, float] = defaultdict(float)
        by_currency: Dict[str, float] = defaultdict(float)
        by_region: Dict[str, float] = defaultdict(float)
        # Quota di ogni settore/area che proviene da DENTRO gli ETF (per le parentesi)
        by_sector_etf: Dict[str, float] = defaultdict(float)
        by_region_etf: Dict[str, float] = defaultdict(float)

        # Le 4 macro categorie vanno sempre mostrate, anche a 0% (Obbligazioni / Materie Prime)
        _ASSET_ALWAYS = {taxonomy.AZIONI, taxonomy.OBBLIGAZIONI, taxonomy.MATERIE_PRIME, taxonomy.CRYPTO}
        for k in _ASSET_ALWAYS:
            by_asset[k] = 0.0

        # Look-through company exposure: {symbol_or_name: {name, symbol, direct, via_etf}}
        companies: Dict[str, dict] = {}

        def _company(symbol: Optional[str], name: str) -> dict:
            key = (symbol or name or "?").upper()
            if key not in companies:
                companies[key] = {"name": name, "symbol": symbol, "direct": 0.0, "via_etf": 0.0}
            return companies[key]

        # Concentrazione "per nome singolo" (look-through): aggrega l'esposizione reale
        # per singolo nome (azienda, Bitcoin, Oro…). Le quote diversificate degli ETF
        # (parte azionaria non coperta dalle top-10, obbligazioni) NON sono nomi singoli.
        single_names: Dict[str, float] = defaultdict(float)

        def _crypto_name(inst, category=None) -> str:
            s = ((inst.name if inst else "") + " " + (category or "")).lower()
            t = (inst.ticker if inst else "").upper()
            if "btc" in t or "bitcoin" in s:
                return "Bitcoin"
            if "eth" in t or "ethereum" in s:
                return "Ethereum"
            return (inst.name if inst else None) or "Crypto"

        def _commodity_name(inst, category=None) -> str:
            s = ((inst.name if inst else "") + " " + (category or "")).lower()
            if "gold" in s or "oro" in s:
                return "Oro"
            if "silver" in s or "argento" in s:
                return "Argento"
            return (inst.name if inst else None) or "Materie Prime"

        etf_total = 0.0          # valore complessivo degli ETF
        etf_captured = 0.0       # quota di ETF "guardata dentro" (somma pesi top-10)

        for p in positions:
            mv = p.market_value
            inst = self.db.query(Instrument).filter(Instrument.id == p.instrument_id).first()
            by_currency[p.currency] += mv
            ac = inst.asset_class if inst else AssetClass.EQUITY

            if ac == AssetClass.ETF:
                etf_total += mv
                profile = self.db.query(EtfProfile).filter(EtfProfile.instrument_id == p.instrument_id).first()
                split = taxonomy.etf_macro_split(profile)
                # Asset class: ripartisci l'ETF tra Azioni/Obbligazioni/…
                for macro, frac in split.items():
                    by_asset[macro] += mv * frac
                # Settore: la parte azionaria è distribuita sui settori; le parti
                # non azionarie (obbligazioni / materie prime / liquidità) finiscono
                # nella rispettiva macro-categoria invece che in "Non classificato".
                equity_frac = split.get(taxonomy.AZIONI, 0.0)
                sw = self.db.query(EtfSectorWeight).filter(EtfSectorWeight.etf_id == p.instrument_id).all()
                sw_total = sum(r.weight for r in sw)
                if equity_frac > 0 and sw_total > 0:
                    for r in sw:
                        lbl = taxonomy.sector_it(r.sector_key)
                        contrib = mv * equity_frac * (r.weight / sw_total)
                        by_sector[lbl] += contrib
                        by_sector_etf[lbl] += contrib
                elif equity_frac > 0:
                    by_sector["Non classificato"] += mv * equity_frac
                    by_sector_etf["Non classificato"] += mv * equity_frac
                for macro in (taxonomy.OBBLIGAZIONI, taxonomy.MATERIE_PRIME, taxonomy.CRYPTO, taxonomy.LIQUIDITA, taxonomy.ALTRO):
                    frac = split.get(macro, 0.0)
                    if frac > 0:
                        by_sector[macro] += mv * frac
                        by_sector_etf[macro] += mv * frac
                # Look-through aziende: top holdings
                holdings = self.db.query(EtfHolding).filter(EtfHolding.etf_id == p.instrument_id).all()
                for h in holdings:
                    _company(h.symbol, h.name)["via_etf"] += mv * h.weight
                    etf_captured += mv * h.weight
                # Nomi singoli concentrati dentro l'ETF (crypto / materie prime)
                cat = profile.category if profile else None
                if split.get(taxonomy.CRYPTO, 0.0) > 0:
                    single_names[_crypto_name(inst, cat)] += mv * split[taxonomy.CRYPTO]
                if split.get(taxonomy.MATERIE_PRIME, 0.0) > 0:
                    single_names[_commodity_name(inst, cat)] += mv * split[taxonomy.MATERIE_PRIME]

                # Area geografica: usa l'allocazione regionale del fondo se nota,
                # altrimenti deduce dalle top-10 e mette il resto in "Altri mercati".
                # Crypto/materie prime non sono geografici → esclusi.
                geo_frac = split.get(taxonomy.AZIONI, 0.0) + split.get(taxonomy.OBBLIGAZIONI, 0.0)
                rw = self.db.query(EtfRegionWeight).filter(EtfRegionWeight.etf_id == p.instrument_id).all()
                if rw:
                    for r in rw:
                        by_region[r.region] += mv * r.weight
                        by_region_etf[r.region] += mv * r.weight
                elif geo_frac > 0:
                    covered = 0.0
                    for h in holdings:
                        sp = self.db.query(SecurityProfile).filter(SecurityProfile.symbol == h.symbol).first() if h.symbol else None
                        region = taxonomy.region_for(sp.country if sp else None)
                        by_region[region] += mv * h.weight
                        by_region_etf[region] += mv * h.weight
                        covered += h.weight
                    if covered < geo_frac:
                        by_region[taxonomy.ALTRI_MERCATI] += mv * (geo_frac - covered)
                        by_region_etf[taxonomy.ALTRI_MERCATI] += mv * (geo_frac - covered)
            else:
                macro = taxonomy.macro_for_simple(ac.value if hasattr(ac, "value") else str(ac))
                by_asset[macro] += mv
                # Settore
                if macro == taxonomy.CRYPTO:
                    by_sector[taxonomy.CRYPTO] += mv
                elif macro == taxonomy.MATERIE_PRIME:
                    by_sector[taxonomy.MATERIE_PRIME] += mv
                elif macro == taxonomy.OBBLIGAZIONI:
                    by_sector[taxonomy.OBBLIGAZIONI] += mv
                else:
                    by_sector[taxonomy.sector_it(inst.sector if inst else None)] += mv
                # Area geografica (crypto e materie prime non sono geografici → esclusi)
                if macro not in (taxonomy.CRYPTO, taxonomy.MATERIE_PRIME):
                    by_region[taxonomy.region_for(inst.country if inst else None)] += mv
                # Look-through aziende / nomi singoli
                if macro == taxonomy.AZIONI:
                    _company(p.ticker, p.name)["direct"] += mv
                elif macro == taxonomy.CRYPTO:
                    single_names[_crypto_name(inst)] += mv
                elif macro == taxonomy.MATERIE_PRIME:
                    single_names[_commodity_name(inst)] += mv

        def to_items(d: dict, always: frozenset = frozenset(), etf_d: dict = None) -> List[schemas.AllocationItem]:
            items = []
            for k, v in d.items():
                pct = round(v / total * 100, 2) if total else 0
                if pct > 0 or k in always:   # scarta le voci che arrotondano a 0% (tranne le fisse)
                    via_etf = round((etf_d.get(k, 0.0) / total * 100), 2) if (etf_d and total) else 0.0
                    items.append(schemas.AllocationItem(
                        label=k, value=round(v, 2), weight_pct=pct, via_etf_pct=via_etf,
                    ))
            return sorted(items, key=lambda x: -x.value)

        # L'area geografica si riferisce alla sola quota geografica (azioni+obbligazioni),
        # quindi le percentuali sono calcolate sul totale di quella quota (sommano a 100%).
        region_total = sum(by_region.values())
        region_items = sorted(
            [schemas.AllocationItem(
                label=k, value=round(v, 2),
                weight_pct=round(v / region_total * 100, 2) if region_total else 0,
                via_etf_pct=round(by_region_etf.get(k, 0.0) / region_total * 100, 2) if region_total else 0,
            ) for k, v in by_region.items() if v > 0.005],
            key=lambda x: -x.value,
        )

        # Esposizione per azienda (diretta + dentro gli ETF)
        company_exposure = []
        for c in companies.values():
            val = c["direct"] + c["via_etf"]
            if val <= 0:
                continue
            company_exposure.append(schemas.CompanyExposure(
                name=c["name"], symbol=c["symbol"],
                value=round(val, 2),
                weight_pct=round(val / total * 100, 2) if total else 0,
                direct_value=round(c["direct"], 2),
                via_etf_value=round(c["via_etf"], 2),
                direct_pct=round(c["direct"] / total * 100, 2) if total else 0,
                via_etf_pct=round(c["via_etf"] / total * 100, 2) if total else 0,
            ))
        company_exposure.sort(key=lambda x: -x.value)
        company_exposure = company_exposure[:15]
        coverage = (etf_captured / etf_total * 100) if etf_total > 0 else 0.0

        # ── Concentrazione PER STRUMENTO (ogni posizione = 1 holding) ─────────────
        weights = [p.market_value / total for p in positions if total > 0]
        hhi = sum(w ** 2 for w in weights) * 10000  # scala 0-10000
        top5 = sum(sorted([p.market_value for p in positions], reverse=True)[:5])
        top5_weight = top5 / total * 100 if total else 0

        # ── Concentrazione PER NOME (look-through) ────────────────────────────────
        # Unisce le aziende (diretto + dentro ETF) ai nomi singoli (Bitcoin, Oro…).
        # Le quote diversificate degli ETF non sono nomi singoli → contributo ~0.
        names = dict(single_names)
        for c in companies.values():
            val = c["direct"] + c["via_etf"]
            if val > 0:
                names[c["name"]] = names.get(c["name"], 0.0) + val
        name_vals = sorted(names.values(), reverse=True)
        hhi_lt = sum((v / total) ** 2 for v in names.values()) * 10000 if total else 0
        top5_lt = sum(name_vals[:5]) / total * 100 if (total and name_vals) else 0
        top_name = max(names.items(), key=lambda kv: kv[1])[0] if names else None
        top_name_pct = (name_vals[0] / total * 100) if (total and name_vals) else 0

        return schemas.AnalysisResponse(
            by_asset_class=to_items(by_asset, always=frozenset(_ASSET_ALWAYS)),
            by_sector=to_items(by_sector, etf_d=by_sector_etf),
            by_country=region_items,
            by_currency=to_items(by_currency),
            top_holdings=positions[:10],
            concentration=schemas.ConcentrationRisk(
                top5_weight=round(top5_weight, 2),
                hhi=round(hhi, 0),
                top5_weight_lookthrough=round(top5_lt, 2),
                hhi_lookthrough=round(hhi_lt, 0),
                top_name=top_name,
                top_name_pct=round(top_name_pct, 2),
            ),
            company_exposure=company_exposure,
            lookthrough_coverage_pct=round(coverage, 1),
        )

    def portfolio_twr_chart(
        self, portfolio_id: Optional[int] = None, period: str = "All",
        exclude_instrument_ids: Optional[List[int]] = None,
    ) -> List[Tuple[date, float]]:
        key = ("twr", self.user_id, portfolio_id, period, tuple(sorted(exclude_instrument_ids or ())))
        return _cached_series(key, lambda: self._portfolio_twr_chart_compute(portfolio_id, period, exclude_instrument_ids))

    def _portfolio_twr_chart_compute(
        self, portfolio_id: Optional[int] = None, period: str = "All",
        exclude_instrument_ids: Optional[List[int]] = None,
    ) -> List[Tuple[date, float]]:
        """
        Time-Weighted Return series (base 1.0 = start).
        Cash flows (purchases/sales) are stripped out so only market
        price appreciation is measured — comparable to a buy-and-hold index.
        Returns list of (date, cumulative_twr) where day-0 = 1.0.
        """
        pids = _user_portfolio_ids(self.user_id, self.db, portfolio_id)
        if not pids:
            return []

        cutoff = MarketService._period_cutoff(period)

        all_txs = (
            self.db.query(Transaction)
            .filter(Transaction.portfolio_id.in_(pids))
            .order_by(Transaction.date)
            .all()
        )
        if exclude_instrument_ids:
            excl = set(exclude_instrument_ids)
            all_txs = [t for t in all_txs if t.instrument_id not in excl]
        if not all_txs:
            return []

        first_tx_date = all_txs[0].date
        chart_start = max(cutoff, first_tx_date)

        inst_ids = list({t.instrument_id for t in all_txs})

        # Price history from chart_start
        prices: Dict[int, Dict[date, float]] = {}
        sorted_prices: Dict[int, List[Tuple[date, float]]] = {}
        for iid in inst_ids:
            rows = self.db.query(PriceHistory).filter(
                PriceHistory.instrument_id == iid,
                PriceHistory.date >= chart_start,
            ).order_by(PriceHistory.date).all()
            prices[iid] = {r.date: r.close_price for r in rows}
            sorted_prices[iid] = sorted(prices[iid].items())

        all_dates = sorted({d for pd in prices.values() for d in pd})
        if not all_dates:
            return []

        # Historical FX: each day's price is converted at THAT day's rate.
        inst_currencies: Dict[int, str] = {}
        for iid in inst_ids:
            inst = self.db.query(Instrument).filter(Instrument.id == iid).first()
            if inst:
                inst_currencies[iid] = inst.currency
        fx_at = self._build_fx_lookup(set(inst_currencies.values()))

        def _price_eur(iid: int, d: date) -> float:
            p = prices.get(iid, {}).get(d)
            if p is None:
                sp = sorted_prices.get(iid, [])
                before = [v for k, v in sp if k <= d]
                p = before[-1] if before else (sp[0][1] if sp else 0.0)
            cur = inst_currencies.get(iid, "EUR")
            fx = fx_at(cur, d)
            return p / fx if fx and cur != "EUR" else p

        def _book_value(book: Dict[int, float], d: date) -> float:
            return sum(_price_eur(iid, d) * qty for iid, qty in book.items() if qty > 0.0001)

        # Apply cash flows with a date-ordered pointer: at each valuation date we apply
        # every transaction with date <= d AFTER measuring the pre-flow market return.
        # Trades on non-axis dates (weekends/holidays) are thus counted at the next
        # valuation instead of being dropped from the book.
        sorted_txs = all_txs  # already ordered by Transaction.date
        running_book: Dict[int, float] = defaultdict(float)
        ti = 0

        # TWR: chain sub-period returns measured BEFORE each cash flow
        cumulative = 1.0
        prev_value: Optional[float] = None
        result: List[Tuple[date, float]] = []

        for d in all_dates:
            value_before = _book_value(running_book, d)

            # Market return since last period (excluding this period's cash flows)
            if prev_value is not None and prev_value > 0:
                cumulative *= value_before / prev_value

            # Apply all cash flows up to and including this date
            while ti < len(sorted_txs) and sorted_txs[ti].date <= d:
                tx = sorted_txs[ti]
                if tx.type == TransactionType.BUY:
                    running_book[tx.instrument_id] += tx.quantity
                else:
                    running_book[tx.instrument_id] -= tx.quantity
                ti += 1

            prev_value = _book_value(running_book, d)
            result.append((d, cumulative))

        return result

    def _calc_realized_pnl(self, pids: List[int]) -> float:
        txs = (
            self.db.query(Transaction)
            .filter(Transaction.portfolio_id.in_(pids))
            .order_by(Transaction.date)
            .all()
        )
        book: Dict[int, dict] = {}
        realized = 0.0
        for tx in txs:
            iid = tx.instrument_id
            if iid not in book:
                book[iid] = {"qty": 0.0, "cost": 0.0}
            price_eur = tx.price / tx.fx_rate if tx.fx_rate else tx.price
            fees_eur = tx.fees / tx.fx_rate if tx.fx_rate else tx.fees
            if tx.type == TransactionType.BUY:
                book[iid]["cost"] += price_eur * tx.quantity + fees_eur
                book[iid]["qty"] += tx.quantity
            else:
                if book[iid]["qty"] > 0:
                    avg = book[iid]["cost"] / book[iid]["qty"]
                    proceeds = price_eur * tx.quantity - fees_eur
                    realized += proceeds - avg * tx.quantity
                    book[iid]["cost"] -= avg * tx.quantity
                    book[iid]["qty"] -= tx.quantity
        return realized

    def _calc_realized_dividends(self, pids: List[int]) -> float:
        """Total dividends + coupons cashed, converted to EUR."""
        events = (
            self.db.query(DividendEvent)
            .filter(DividendEvent.portfolio_id.in_(pids))
            .all()
        )
        return sum(
            (ev.amount / ev.fx_rate if ev.fx_rate else ev.amount)
            for ev in events
        )


# ── Performance Calculations ──────────────────────────────────────────────────

class PerformanceCalculator:
    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self._dash = DashboardCalculator(db, user_id)

    def _twr_series(self, portfolio_id: Optional[int] = None) -> List[Tuple[date, float]]:
        """
        Cumulative time-weighted return series (base 1.0 at start).
        Cash flows (purchases/sales) are stripped out, so this reflects pure
        market performance — the ONLY correct basis for return/risk metrics.
        Using the raw market-value series instead would treat every contribution
        as a daily "return", massively inflating volatility and Sharpe.
        """
        return self._dash.portfolio_twr_chart(portfolio_id, "All")

    @staticmethod
    def _daily_returns(twr: List[Tuple[date, float]]) -> List[float]:
        """Daily returns derived from the cumulative TWR series."""
        rets = []
        for i in range(1, len(twr)):
            prev = twr[i - 1][1]
            if prev > 0:
                rets.append(twr[i][1] / prev - 1)
        return rets

    def monthly_returns(self, portfolio_id: Optional[int] = None) -> List[schemas.MonthlyReturn]:
        twr = self._twr_series(portfolio_id)
        if not twr:
            return []

        # Last cumulative TWR value seen in each month → chained month-over-month.
        monthly: Dict[Tuple[int, int], float] = {}
        for d, v in twr:
            monthly[(d.year, d.month)] = v

        keys = sorted(monthly.keys())
        result = []
        # Seed with the inception TWR (base 1.0 at the very first data point) so the
        # first (partial) month's return is included instead of being dropped.
        prev_val = twr[0][1]
        for key in keys:
            curr_val = monthly[key]
            ret = ((curr_val - prev_val) / prev_val * 100) if prev_val else 0
            result.append(schemas.MonthlyReturn(year=key[0], month=key[1], return_pct=round(ret, 2)))
            prev_val = curr_val
        return result

    def drawdown_series(self, portfolio_id: Optional[int] = None) -> List[schemas.DrawdownPoint]:
        # Drawdown on the TWR series (cash-flow free) — otherwise a contribution
        # would inflate the value and mask a real market drawdown.
        twr = self._twr_series(portfolio_id)
        if not twr:
            return []
        peak = twr[0][1]
        result = []
        for d, v in twr:
            if v > peak:
                peak = v
            dd = ((v - peak) / peak * 100) if peak > 0 else 0
            result.append(schemas.DrawdownPoint(date=d, drawdown=round(dd, 2)))
        return result

    def metrics(self, portfolio_id: Optional[int] = None, benchmark: str = "SWDA.MI") -> schemas.PerformanceMetrics:
        # Risk/return metrics MUST be computed on the time-weighted return series,
        # which removes cash flows. The raw market-value series would count every
        # purchase as a daily "return", producing nonsensical Sharpe/volatility.
        twr = self._twr_series(portfolio_id)
        daily_returns = self._daily_returns(twr)

        # Max drawdown on the same (cash-flow free) TWR series.
        max_dd = 0.0
        if twr:
            peak = twr[0][1]
            for _, v in twr:
                if v > peak:
                    peak = v
                if peak > 0:
                    dd = (v - peak) / peak * 100
                    if dd < max_dd:
                        max_dd = dd

        period_rets = self._period_returns(twr)

        if len(daily_returns) < 20:
            return schemas.PerformanceMetrics(
                sharpe_ratio=None,
                volatility_annual=None,
                max_drawdown=round(max_dd, 2) if twr else None,
                period_returns=period_rets,
            )

        import math
        n = len(daily_returns)
        mean_daily = sum(daily_returns) / n
        variance = sum((r - mean_daily) ** 2 for r in daily_returns) / n
        std_daily = math.sqrt(variance) if variance >= 0 else 0.0

        # Annualised volatility (√252 trading days)
        vol_annual = std_daily * math.sqrt(252)

        # Annualised return for the Sharpe numerator = GEOMETRIC TWR (the chained
        # product of the clean sub-period returns), annualised on the same 252-period
        # basis as the volatility. Using the true geometric TWR — instead of the
        # arithmetic mean compounded, (1+mean)^252-1 — removes the variance-drag
        # overstatement (~σ²/2, large for high-vol/crypto portfolios) and keeps the
        # numerator (time-weighted) coherent with the time-weighted denominator.
        total_twr = twr[-1][1] / twr[0][1] if twr and twr[0][1] > 0 else 0.0
        try:
            ann_return = total_twr ** (252 / n) - 1 if total_twr > 0 else -1.0
        except (OverflowError, ValueError):
            ann_return = float('inf')

        if math.isfinite(ann_return) and vol_annual > 0:
            sharpe_raw = (ann_return - RISK_FREE_RATE) / vol_annual
            sharpe = sharpe_raw if math.isfinite(sharpe_raw) else None
        else:
            sharpe = None

        vol_annual_pct = vol_annual * 100
        if not math.isfinite(vol_annual_pct):
            vol_annual_pct = None

        return schemas.PerformanceMetrics(
            sharpe_ratio=round(sharpe, 3) if sharpe is not None else None,
            volatility_annual=round(vol_annual_pct, 2) if vol_annual_pct is not None else None,
            max_drawdown=round(max_dd, 2),
            period_returns=period_rets,
        )

    def cumulative_chart(
        self, portfolio_id: Optional[int] = None, benchmark: str = "SWDA.MI", period: str = "1Y"
    ) -> schemas.PortfolioChartResponse:
        return self._dash.portfolio_chart(portfolio_id, period)

    def _period_returns(self, twr: List[Tuple[date, float]]) -> List[schemas.PeriodReturn]:
        # Period returns are time-weighted (cash-flow free) so they reflect market
        # performance, not money added/withdrawn during the period.
        if not twr:
            return []
        today = date.today()
        periods = {
            "1M": 30, "3M": 91, "6M": 182,
            "YTD": (today - date(today.year, 1, 1)).days,
            "1Y": 365, "3Y": 365 * 3, "5Y": 365 * 5, "10Y": 365 * 10,
        }
        result = []
        latest = twr[-1][1]
        import math as _math

        def _pct(ref_val: float) -> Optional[float]:
            if not ref_val or not _math.isfinite(ref_val) or ref_val <= 0:
                return None
            raw = (latest - ref_val) / ref_val * 100
            return round(raw, 2) if _math.isfinite(raw) else None

        for label, days in periods.items():
            cutoff = today - timedelta(days=days)
            ref_points = [(d, v) for d, v in twr if d <= cutoff]
            if not ref_points:
                result.append(schemas.PeriodReturn(period=label, portfolio_return=None, benchmark_return=None))
                continue
            result.append(schemas.PeriodReturn(period=label, portfolio_return=_pct(ref_points[-1][1]), benchmark_return=None))

        # Max = from the very first TWR data point (total return since inception)
        result.append(schemas.PeriodReturn(period="Max", portfolio_return=_pct(twr[0][1]), benchmark_return=None))
        return result


# ── Dividend Calculations ─────────────────────────────────────────────────────

# Finestra (giorni) entro cui un incasso broker/manuale, datato alla data di
# pagamento, "copre" il dividendo Yahoo datato alla ex-date: sotto i ~90 giorni
# tra due dividendi trimestrali, così non fonde per errore eventi distinti.
_DIVIDEND_RECONCILE_DAYS = 60


class DividendCalculator:
    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.market = MarketService(db)

    def kpis(self, portfolio_id: Optional[int] = None) -> schemas.DividendKPIs:
        pids = _user_portfolio_ids(self.user_id, self.db, portfolio_id)
        events = self.db.query(DividendEvent).filter(DividendEvent.portfolio_id.in_(pids)).all()

        today = date.today()
        ytd_total = 0.0
        all_total = 0.0
        gross_total = 0.0
        tax_total = 0.0
        for ev in events:
            fx = ev.fx_rate or 1.0
            all_total += ev.amount / fx
            gross_total += (ev.gross_amount if ev.gross_amount is not None else ev.amount) / fx
            tax_total += ((ev.foreign_tax_amount or 0.0) + (ev.tax_amount or 0.0)) / fx
            if ev.date.year == today.year:
                ytd_total += ev.amount / fx

        # Yield on cost: sum(annual dividends per instrument) / sum(cost basis)
        avg_yield = self._avg_yield_on_cost(pids)

        return schemas.DividendKPIs(
            total_ytd=round(ytd_total, 2),
            total_all_time=round(all_total, 2),
            total_gross=round(gross_total, 2),
            total_tax=round(tax_total, 2),
            avg_yield_on_cost=round(avg_yield * 100, 2),
        )

    def monthly_last_12(self, portfolio_id: Optional[int] = None) -> List[schemas.MonthlyDividend]:
        pids = _user_portfolio_ids(self.user_id, self.db, portfolio_id)
        today = date.today()
        cutoff = today - timedelta(days=365)
        events = self.db.query(DividendEvent).filter(
            DividendEvent.portfolio_id.in_(pids),
            DividendEvent.date >= cutoff,
        ).all()

        # Netto per mese, separato tra dividendi e cedole (bond + certificati)
        # per il grafico impilato "Dividendi/Cedole".
        monthly: Dict[str, Dict[str, float]] = defaultdict(lambda: {"dividends": 0.0, "coupons": 0.0})
        for ev in events:
            key = f"{ev.date.year}-{ev.date.month:02d}"
            bucket = "dividends" if ev.type == DividendType.DIVIDEND else "coupons"
            monthly[key][bucket] += ev.amount / (ev.fx_rate or 1.0)

        return [
            schemas.MonthlyDividend(
                month=k,
                amount=round(v["dividends"] + v["coupons"], 2),
                dividends=round(v["dividends"], 2),
                coupons=round(v["coupons"], 2),
            )
            for k, v in sorted(monthly.items())
        ]

    def projection_12_months(self, portfolio_id: Optional[int] = None) -> List[schemas.DividendProjection]:
        pids = _user_portfolio_ids(self.user_id, self.db, portfolio_id)
        events = self.db.query(DividendEvent).filter(DividendEvent.portfolio_id.in_(pids)).all()
        if not events:
            return []

        # Group by instrument, aggregating per ex-date: the same instrument held in
        # several portfolios yields multiple events on the same date — they are one
        # payment (summed), not a shorter payout cadence.
        by_inst: Dict[int, Dict[date, float]] = defaultdict(lambda: defaultdict(float))
        for ev in events:
            by_inst[ev.instrument_id][ev.date] += ev.amount / (ev.fx_rate or 1.0)

        projections: Dict[str, float] = defaultdict(float)
        today = date.today()

        for iid, per_date in by_inst.items():
            if len(per_date) < 2:
                continue
            dates_sorted = sorted(per_date)
            # Infer average interval; the 1-day floor keeps the projection loop
            # advancing even on degenerate data (e.g. consecutive-day events).
            gaps = [(dates_sorted[i] - dates_sorted[i - 1]).days for i in range(1, len(dates_sorted))]
            avg_gap = max(sum(gaps) / len(gaps), 1.0)
            avg_amount = sum(per_date.values()) / len(per_date)
            last_date = dates_sorted[-1]

            # Project forward 12 months
            next_date = last_date + timedelta(days=avg_gap)
            while next_date <= today + timedelta(days=365):
                if next_date > today:
                    key = f"{next_date.year}-{next_date.month:02d}"
                    projections[key] += avg_amount
                next_date += timedelta(days=avg_gap)

        return [
            schemas.DividendProjection(month=k, amount=round(v, 2))
            for k, v in sorted(projections.items())
        ]

    def _avg_yield_on_cost(self, pids: List[int]) -> float:
        """Average yield-on-cost: annual dividend per instrument / avg cost basis."""
        if not pids:
            return 0.0

        events = self.db.query(DividendEvent).filter(DividendEvent.portfolio_id.in_(pids)).all()
        txs = self.db.query(Transaction).filter(Transaction.portfolio_id.in_(pids)).all()

        # Cost basis per instrument
        cost_basis: Dict[int, float] = defaultdict(float)
        qty_book: Dict[int, float] = defaultdict(float)
        for tx in sorted(txs, key=lambda t: t.date):
            price_eur = tx.price / (tx.fx_rate or 1.0)
            if tx.type == TransactionType.BUY:
                cost_basis[tx.instrument_id] += price_eur * tx.quantity
                qty_book[tx.instrument_id] += tx.quantity
            else:
                if qty_book[tx.instrument_id] > 0:
                    avg = cost_basis[tx.instrument_id] / qty_book[tx.instrument_id]
                    cost_basis[tx.instrument_id] -= avg * tx.quantity
                    qty_book[tx.instrument_id] -= tx.quantity

        # Annual dividends per instrument (last 12 months)
        cutoff = date.today() - timedelta(days=365)
        annual: Dict[int, float] = defaultdict(float)
        for ev in events:
            if ev.date >= cutoff:
                annual[ev.instrument_id] += ev.amount / (ev.fx_rate or 1.0)

        # Value-weighted yield-on-cost: total annual dividends / total cost basis of
        # the dividend-paying holdings. An unweighted mean of per-instrument yields
        # would let a tiny high-yield position dominate the figure.
        total_div = 0.0
        total_cost = 0.0
        for iid, div in annual.items():
            cost = cost_basis.get(iid, 0.0)
            if cost > 0:
                total_div += div
                total_cost += cost

        return (total_div / total_cost) if total_cost > 0 else 0.0

    async def sync_from_market(self, portfolio_id: Optional[int] = None) -> int:
        """
        Fetch each held instrument's dividend history from Yahoo and create the
        DividendEvents that were paid while shares were held, sized to the shares
        held on the ex-date and taxed (estimated) gross→net. Returns how many new
        events were created. Existing events (e.g. imported from a CSV with real
        amounts) are preserved — the UniqueConstraint skips duplicates.
        """
        from .tax import compute_net

        pids = _user_portfolio_ids(self.user_id, self.db, portfolio_id)
        if not pids:
            return 0

        txs = (
            self.db.query(Transaction)
            .filter(Transaction.portfolio_id.in_(pids))
            .order_by(Transaction.date)
            .all()
        )

        # Group transactions per (portfolio, instrument)
        by_key: Dict[Tuple[int, int], List[Transaction]] = defaultdict(list)
        instruments: Dict[int, Instrument] = {}
        for tx in txs:
            by_key[(tx.portfolio_id, tx.instrument_id)].append(tx)
            instruments[tx.instrument_id] = tx.instrument

        # Fetch dividend history once per instrument (cached across portfolios).
        # Gli strumenti con fonte prezzo manuale/custom non sono su Yahoo: le
        # loro cedole si gestiscono col piano cedolare, non col sync.
        history: Dict[int, List[tuple]] = {}
        for iid, inst in instruments.items():
            if not inst or not inst.ticker or inst.price_source != models.PriceSource.YAHOO:
                continue
            try:
                history[iid] = await self.market.fetch_dividend_history(inst.ticker)
            except Exception:
                history[iid] = []

        created = 0
        for (pid, iid), inst_txs in by_key.items():
            inst = instruments.get(iid)
            divs = history.get(iid) or []
            if not inst or not divs:
                continue

            div_type = (
                DividendType.COUPON
                if inst.asset_class == AssetClass.BOND
                else DividendType.DIVIDEND
            )
            inst_txs_sorted = sorted(inst_txs, key=lambda t: t.date)

            # Riconciliazione "broker se presente, altrimenti Yahoo": raccolgo le
            # date degli incassi NON-Yahoo già registrati per questo strumento nel
            # portafoglio (import broker o manuali). Un dividendo Yahoo viene
            # saltato se un incasso non-Yahoo cade tra la ex-date e +N giorni,
            # perché broker e Yahoo datano lo stesso dividendo in modo diverso
            # (Yahoo = ex-date, broker = data pagamento, alcune settimane dopo).
            broker_dates = [
                d for (d,) in self.db.query(DividendEvent.date).filter(
                    DividendEvent.portfolio_id == pid,
                    DividendEvent.instrument_id == iid,
                    DividendEvent.source != DividendSource.YAHOO,
                ).all()
            ]

            for ex_date, per_share in divs:
                # Un incasso reale (broker/manuale) copre già questo dividendo?
                if any(0 <= (bd_date - ex_date).days <= _DIVIDEND_RECONCILE_DAYS
                       for bd_date in broker_dates):
                    continue

                # Shares held the day before the ex-date (a same-day buy isn't entitled)
                qty = 0.0
                for tx in inst_txs_sorted:
                    if tx.date >= ex_date:
                        break
                    qty += tx.quantity if tx.type == TransactionType.BUY else -tx.quantity
                if qty <= 0.0001:
                    continue

                gross = per_share * qty
                fx = await self.market.get_fx_rate_for_date(inst.currency, ex_date)
                bd = compute_net(gross, div_type, inst.asset_class, inst.country)

                ev = DividendEvent(
                    portfolio_id=pid,
                    instrument_id=iid,
                    date=ex_date,
                    amount=round(bd.net, 4),
                    gross_amount=round(gross, 4),
                    foreign_tax_amount=round(bd.foreign_tax, 4),
                    tax_amount=round(bd.italian_tax, 4),
                    accrued_interest=0.0,
                    currency=inst.currency,
                    fx_rate=fx,
                    type=div_type,
                    source=DividendSource.YAHOO,
                )
                # Per-row savepoint: a duplicate (unique-constraint) skips just this row.
                try:
                    with self.db.begin_nested():
                        self.db.add(ev)
                        self.db.flush()
                    created += 1
                except Exception:
                    pass

        self.db.commit()
        return created

    def find_yahoo_duplicates(self, portfolio_id: Optional[int] = None) -> List[Tuple[DividendEvent, date]]:
        """Incassi di fonte YAHOO che un incasso reale (import broker/manuale) già
        copre: stesso strumento nel portafoglio, con la data broker (pagamento)
        tra la ex-date Yahoo e +N giorni. Stessa regola della riconciliazione nel
        sync — qui applicata retroattivamente per deduplicare lo storico.

        Ritorna coppie (evento YAHOO duplicato, data dell'import che lo copre)."""
        pids = _user_portfolio_ids(self.user_id, self.db, portfolio_id)
        if not pids:
            return []
        divs = (
            self.db.query(DividendEvent)
            .filter(DividendEvent.portfolio_id.in_(pids))
            .order_by(DividendEvent.date)
            .all()
        )
        broker_dates: Dict[Tuple[int, int], List] = defaultdict(list)
        for d in divs:
            if d.source != DividendSource.YAHOO:
                broker_dates[(d.portfolio_id, d.instrument_id)].append(d.date)

        dupes: List[Tuple[DividendEvent, date]] = []
        for d in divs:
            if d.source != DividendSource.YAHOO:
                continue
            covering = sorted(
                bd for bd in broker_dates.get((d.portfolio_id, d.instrument_id), [])
                if 0 <= (bd - d.date).days <= _DIVIDEND_RECONCILE_DAYS
            )
            if covering:
                dupes.append((d, covering[0]))
        return dupes



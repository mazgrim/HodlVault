import math
import logging
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user
from ..services.calculations import DashboardCalculator
from ..services.market import MarketService, _fetch_chart, _extract_prices

logger = logging.getLogger(__name__)
router = APIRouter()

BENCHMARKS = [
    {"label": "MSCI World",    "ticker": "SWDA.MI",   "currency": "EUR"},
    {"label": "S&P 500",       "ticker": "SPY",       "currency": "USD"},
    {"label": "NASDAQ 100",    "ticker": "QQQ",       "currency": "USD"},
    {"label": "MSCI Emerging", "ticker": "EIMI.L",    "currency": "USD"},
    {"label": "Euro Stoxx 50", "ticker": "^STOXX50E", "currency": "EUR"},
    {"label": "BTP Italia",    "ticker": "IITB.MI",   "currency": "EUR"},
    {"label": "Gold",          "ticker": "GC=F",      "currency": "USD"},
    {"label": "Bitcoin",       "ticker": "BTC-EUR",   "currency": "EUR"},
]
_CURRENCY = {b["ticker"]: b["currency"] for b in BENCHMARKS}

_COLORS = {
    "SWDA.MI":   "#3b82f6",
    "SPY":       "#10b981",
    "QQQ":       "#f59e0b",
    "EIMI.L":    "#ec4899",
    "^STOXX50E": "#8b5cf6",
    "IITB.MI":   "#06b6d4",
    "GC=F":      "#f97316",
    "BTC-EUR":   "#a3e635",
}

_YF_RANGE = {
    "3M": "3mo", "6M": "6mo", "YTD": "ytd",
    "1A": "1y",  "3A": "3y",  "5A": "5y", "Max": "10y",
}


def _cutoff(period: str, portfolio_start: Optional[date] = None) -> date:
    today = date.today()
    if period == "Max":
        return portfolio_start or (today - timedelta(days=365 * 10))
    mapping = {
        "3M": 91, "6M": 182,
        "YTD": (today - date(today.year, 1, 1)).days,
        "1A": 365, "3A": 365 * 3, "5A": 365 * 5,
    }
    return today - timedelta(days=mapping.get(period, 365))


def _normalize(pairs: list[tuple[date, float]], cutoff: date) -> list[dict]:
    pts = [(d, v) for d, v in pairs if d >= cutoff and v and v > 0]
    if not pts:
        return []
    base = pts[0][1]
    return [{"date": d.isoformat(), "value": round(v / base * 100, 4)} for d, v in pts]


def _stats(normalized: list[dict]) -> dict:
    if len(normalized) < 2:
        return {"period_return": None, "annualized_return": None, "volatility": None, "max_drawdown": None}

    vals = [p["value"] for p in normalized]
    period_ret = round((vals[-1] - vals[0]) / vals[0] * 100, 2)

    days = (date.fromisoformat(normalized[-1]["date"]) - date.fromisoformat(normalized[0]["date"])).days
    ann = round(((vals[-1] / vals[0]) ** (365 / days) - 1) * 100, 2) if days > 30 else None

    daily = [(vals[i] - vals[i - 1]) / vals[i - 1] for i in range(1, len(vals)) if vals[i - 1] > 0]
    vol = None
    if len(daily) >= 5:
        m = sum(daily) / len(daily)
        v = sum((r - m) ** 2 for r in daily) / len(daily)
        raw = math.sqrt(v) * math.sqrt(252) * 100
        vol = round(raw, 2) if math.isfinite(raw) else None

    peak = vals[0]
    max_dd = 0.0
    for v in vals:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak * 100
            if dd < max_dd:
                max_dd = dd

    return {
        "period_return": period_ret,
        "annualized_return": ann,
        "volatility": vol,
        "max_drawdown": round(max_dd, 2),
    }


def _price_at(pairs: list[tuple[date, float]], d: date) -> Optional[float]:
    """Benchmark EUR price on-or-before *d* (else the earliest known)."""
    if not pairs:
        return None
    prev = pairs[0][1]
    for pd, pv in pairs:
        if pd > d:
            break
        prev = pv
    return prev


def _xnpv(rate: float, flows: list[tuple[date, float]]) -> float:
    t0 = flows[0][0]
    return sum(amt / (1.0 + rate) ** ((d - t0).days / 365.0) for d, amt in flows)


def _xirr(flows: list[tuple[date, float]]) -> Optional[float]:
    """Annualised money-weighted return (XIRR) for dated cash flows, by bisection.
    Returns None when there's no sign change (no solvable rate)."""
    if len(flows) < 2 or all(abs(a) < 1e-9 for _, a in flows):
        return None
    lo, hi = -0.9999, 10.0
    f_lo, f_hi = _xnpv(lo, flows), _xnpv(hi, flows)
    if not (math.isfinite(f_lo) and math.isfinite(f_hi)) or f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = _xnpv(mid, flows)
        if abs(f_mid) < 1e-7:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


async def _benchmark_eur_pairs(
    db: Session, market: MarketService, dash: DashboardCalculator,
    ticker: str, label: str, cutoff: date, period: str,
) -> list[tuple[date, float]]:
    """Benchmark price history converted to EUR at each date's FX rate, from *cutoff*."""
    bench_cur = _CURRENCY.get(ticker, "EUR")

    inst = db.query(models.Instrument).filter(models.Instrument.ticker == ticker).first()
    if not inst:
        inst = models.Instrument(
            ticker=ticker, name=label, currency=bench_cur, asset_class=models.AssetClass.ETF,
        )
        db.add(inst)
        db.commit()
        db.refresh(inst)
    elif inst.currency != bench_cur:
        inst.currency = bench_cur
        db.commit()

    def _rows():
        return (
            db.query(models.PriceHistory)
            .filter(models.PriceHistory.instrument_id == inst.id,
                    models.PriceHistory.date >= cutoff)
            .order_by(models.PriceHistory.date)
            .all()
        )

    rows = _rows()
    if len(rows) < 10 or (rows and rows[0].date > cutoff + timedelta(days=30)):
        try:
            result = await _fetch_chart(ticker, range_=_YF_RANGE.get(period, "1y"))
            if result:
                for price_date, close in _extract_prices(result):
                    market._upsert_price(inst.id, price_date, close, bench_cur)
                db.commit()
                rows = _rows()
        except Exception as exc:
            logger.warning(f"Benchmark fetch failed for {ticker}: {exc}")

    if not rows:
        return []
    if bench_cur != "EUR":
        await market.backfill_historical_fx([bench_cur])
    fx_at = dash._build_fx_lookup({bench_cur})
    return [(r.date, r.close_price / fx_at(bench_cur, r.date)) for r in rows if fx_at(bench_cur, r.date)]


@router.get("/available", response_model=list[schemas.BenchmarkInfo])
def available_benchmarks():
    return [schemas.BenchmarkInfo(ticker=b["ticker"], label=b["label"]) for b in BENCHMARKS]


# Benchmark period → portfolio_chart period (the value-series helper uses different keys)
_PF_PERIOD = {"3M": "3M", "6M": "6M", "YTD": "YTD", "1A": "1Y", "3A": "3Y", "5A": "5Y", "Max": "All"}


@router.get("/chart", response_model=schemas.BenchmarkChartResponse)
async def benchmark_chart(
    portfolio_id: Optional[int] = Query(None),
    tickers: str = Query(""),          # comma-separated ticker list
    period: str = Query("1A"),
    mode: str = Query("twr"),          # "twr" | "invested" (a parità di versamenti)
    exclude: str = Query(""),          # comma-separated instrument ids to drop (what-if)
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    market = MarketService(db)
    dash = DashboardCalculator(db, current_user.id)

    # Ensure historical FX is available for all held currencies, so the EUR
    # conversion of both the portfolio and the benchmarks reflects FX drift.
    await market.backfill_historical_fx()

    label_map = {b["ticker"]: b["label"] for b in BENCHMARKS}
    requested = [t.strip() for t in tickers.split(",") if t.strip() and t.strip() in label_map]

    exclude_ids = [int(x) for x in exclude.split(",") if x.strip().isdigit()]
    holdings = [schemas.BenchmarkHolding(**h) for h in dash.portfolio_instruments(portfolio_id)]

    # Guard: a selection with no open value in the chosen period (e.g. only titles
    # already sold before the window) would draw a flat/degenerate line. Return an
    # empty series so the UI can explain it instead.
    value_pts = dash.portfolio_chart(
        portfolio_id, _PF_PERIOD.get(period, "1Y"), exclude_instrument_ids=exclude_ids,
    ).points
    if not value_pts or all(p.value == 0 for p in value_pts):
        return schemas.BenchmarkChartResponse(series=[], holdings=holdings)

    if mode == "invested":
        resp = await _invested_chart(db, market, dash, portfolio_id, requested, period, label_map, exclude_ids)
        resp.holdings = holdings
        return resp

    # ── TWR mode (default): portfolio TWR vs benchmark price, both rebased to 100 ──
    twr_points = dash.portfolio_twr_chart(portfolio_id, "All", exclude_instrument_ids=exclude_ids)
    if not twr_points:
        return schemas.BenchmarkChartResponse(series=[], holdings=holdings)

    portfolio_start = twr_points[0][0]
    cutoff = max(_cutoff(period, portfolio_start), portfolio_start)

    pf_norm = _normalize(twr_points, cutoff)
    series: list[schemas.BenchmarkSeries] = [
        schemas.BenchmarkSeries(
            key="portfolio", label="HodlVault", color="#D4A017",
            points=[schemas.BenchmarkPoint(**p) for p in pf_norm],
            **_stats(pf_norm),
        )
    ]

    for ticker in requested:
        pairs = await _benchmark_eur_pairs(db, market, dash, ticker, label_map[ticker], cutoff, period)
        if not pairs:
            continue
        bench_norm = _normalize(pairs, cutoff)
        series.append(schemas.BenchmarkSeries(
            key=ticker, label=label_map[ticker], color=_COLORS.get(ticker, "#888"),
            points=[schemas.BenchmarkPoint(**p) for p in bench_norm],
            **_stats(bench_norm),
        ))

    return schemas.BenchmarkChartResponse(series=series, holdings=holdings)


async def _invested_chart(
    db: Session, market: MarketService, dash: DashboardCalculator,
    portfolio_id: Optional[int], requested: list[str], period: str, label_map: dict,
    exclude_ids: Optional[list[int]] = None,
) -> schemas.BenchmarkChartResponse:
    """'A parità di versamenti' (money-weighted, twin-account): the actual portfolio €
    value vs a twin that starts with the same stake, mirrors every DEPOSIT €-for-€ and
    every WITHDRAWAL as the same PROPORTION, each growing at its own returns. Lines are
    absolute EUR; stats are total € gain and annualised IRR, on the same deposited base."""
    pf_resp = dash.portfolio_chart(portfolio_id, _PF_PERIOD.get(period, "1Y"), exclude_instrument_ids=exclude_ids)
    pf_points = pf_resp.points
    if len(pf_points) < 2:
        return schemas.BenchmarkChartResponse(series=[])

    start, end = pf_points[0].date, pf_points[-1].date
    initial, final_pf = pf_points[0].value, pf_points[-1].value
    flows = dash.invested_flows(portfolio_id, start, end, exclude_instrument_ids=exclude_ids)
    # Total money put in (initial stake + deposits) — same for portfolio and twins, so
    # the percentage returns share a denominator and are directly comparable.
    deposited = initial + sum(amt for _, amt in flows if amt > 0)

    pf_vals = [(p.date, p.value) for p in pf_points]

    def _pf_val_after(d: date) -> float:
        """Portfolio € value at the first valuation on-or-after *d* (i.e. AFTER that
        day's trades), used to size a withdrawal as a fraction of the portfolio."""
        for vd, vv in pf_vals:
            if vd >= d:
                return vv
        return pf_vals[-1][1]

    def _mk(key, label, color, value_points, gain, irr):
        return schemas.BenchmarkSeries(
            key=key, label=label, color=color, points=value_points,
            period_return=round(gain / deposited * 100, 2) if deposited else None,
            annualized_return=round(irr * 100, 2) if irr is not None else None,
            volatility=None, max_drawdown=None,
            gain_eur=round(gain, 2), irr=round(irr * 100, 2) if irr is not None else None,
        )

    # Portfolio: deposits negative, withdrawals (proceeds) positive, end value positive.
    pf_cf = [(start, -initial)] + [(d, -amt) for d, amt in flows] + [(end, final_pf)]
    pf_gain = (final_pf + sum(-amt for _, amt in flows if amt < 0)) - deposited
    series = [_mk(
        "portfolio", "HodlVault", "#D4A017",
        [schemas.BenchmarkPoint(date=p.date.isoformat(), value=round(p.value, 2)) for p in pf_points],
        pf_gain, _xirr(pf_cf),
    )]

    for ticker in requested:
        pairs = await _benchmark_eur_pairs(db, market, dash, ticker, label_map[ticker], start, period)
        p0 = _price_at(pairs, start)
        if not pairs or not p0:
            continue
        units = initial / p0
        twin_cf: list[tuple[date, float]] = [(start, -initial)]
        withdrawn = 0.0
        timeline: list[tuple[date, float]] = []   # (flow date, units AFTER the flow)
        for fd, amt in sorted(flows, key=lambda x: x[0]):
            price = _price_at(pairs, fd) or p0
            if amt > 0:                                   # deposit: same € into the twin
                units += amt / price
                twin_cf.append((fd, -amt))
            else:                                         # withdrawal: same proportion
                withdrawal = -amt
                v_before = _pf_val_after(fd) + withdrawal
                frac = min(max(withdrawal / v_before, 0.0), 1.0) if v_before > 0 else 1.0
                cash = units * price * frac               # € actually taken from the twin
                units *= (1.0 - frac)
                twin_cf.append((fd, cash))
                withdrawn += cash
            timeline.append((fd, units))

        def _units_at(d: date) -> float:
            u = initial / p0
            for fd, uu in timeline:
                if fd > d:
                    break
                u = uu
            return u

        bench_points = [
            schemas.BenchmarkPoint(date=pd.isoformat(), value=round(_units_at(pd) * pv, 2))
            for pd, pv in pairs if pd >= start
        ]
        if not bench_points:
            continue
        bench_final = bench_points[-1].value
        twin_cf.append((end, bench_final))
        bench_gain = (withdrawn + bench_final) - deposited
        series.append(_mk(ticker, label_map[ticker], _COLORS.get(ticker, "#888"), bench_points, bench_gain, _xirr(twin_cf)))

    return schemas.BenchmarkChartResponse(series=series)

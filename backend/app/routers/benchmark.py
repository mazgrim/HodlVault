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


@router.get("/available", response_model=list[schemas.BenchmarkInfo])
def available_benchmarks():
    return [schemas.BenchmarkInfo(ticker=b["ticker"], label=b["label"]) for b in BENCHMARKS]


@router.get("/chart", response_model=schemas.BenchmarkChartResponse)
async def benchmark_chart(
    portfolio_id: Optional[int] = Query(None),
    tickers: str = Query(""),          # comma-separated ticker list
    period: str = Query("1A"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    market = MarketService(db)
    dash = DashboardCalculator(db, current_user.id)

    # Ensure historical FX is available for all held currencies, so the EUR
    # conversion of both the portfolio and the benchmarks reflects FX drift.
    await market.backfill_historical_fx()

    # Portfolio series — use TWR so new cash invested doesn't inflate the return
    twr_points = dash.portfolio_twr_chart(portfolio_id, "All")
    if not twr_points:
        return schemas.BenchmarkChartResponse(series=[])

    portfolio_start = twr_points[0][0]
    cutoff = max(_cutoff(period, portfolio_start), portfolio_start)

    pf_norm = _normalize(twr_points, cutoff)
    pf_stats = _stats(pf_norm)

    series: list[schemas.BenchmarkSeries] = [
        schemas.BenchmarkSeries(
            key="portfolio", label="HodlVault", color="#D4A017",
            points=[schemas.BenchmarkPoint(**p) for p in pf_norm],
            **pf_stats,
        )
    ]

    label_map = {b["ticker"]: b["label"] for b in BENCHMARKS}
    requested = [t.strip() for t in tickers.split(",") if t.strip() and t.strip() in label_map]

    for ticker in requested:
        # Authoritative listing currency from the curated benchmark config — do NOT
        # rely on the price-fetch path to set it (cached instruments skip the fetch,
        # which previously left foreign tickers mislabelled as EUR → no FX conversion).
        bench_cur = _CURRENCY.get(ticker, "EUR")

        inst = db.query(models.Instrument).filter(models.Instrument.ticker == ticker).first()
        if not inst:
            inst = models.Instrument(
                ticker=ticker, name=label_map[ticker],
                currency=bench_cur, asset_class=models.AssetClass.ETF,
            )
            db.add(inst)
            db.commit()
            db.refresh(inst)
        elif inst.currency != bench_cur:
            # Repair a stale/incorrect currency on an already-cached benchmark instrument.
            inst.currency = bench_cur
            db.commit()

        rows = (
            db.query(models.PriceHistory)
            .filter(models.PriceHistory.instrument_id == inst.id,
                    models.PriceHistory.date >= cutoff)
            .order_by(models.PriceHistory.date)
            .all()
        )

        needs_fetch = len(rows) < 10 or (rows and rows[0].date > cutoff + timedelta(days=30))
        if needs_fetch:
            yf_range = _YF_RANGE.get(period, "1y")
            try:
                result = await _fetch_chart(ticker, range_=yf_range)
                if result:
                    for price_date, close in _extract_prices(result):
                        market._upsert_price(inst.id, price_date, close, bench_cur)
                    db.commit()
                    rows = (
                        db.query(models.PriceHistory)
                        .filter(models.PriceHistory.instrument_id == inst.id,
                                models.PriceHistory.date >= cutoff)
                        .order_by(models.PriceHistory.date)
                        .all()
                    )
            except Exception as exc:
                logger.warning(f"Benchmark fetch failed for {ticker}: {exc}")

        if not rows:
            continue

        # Convert benchmark prices to EUR at each date's FX rate so the comparison
        # is in the portfolio's currency (EUR), FX drift included.
        if bench_cur != "EUR":
            await market.backfill_historical_fx([bench_cur])
        fx_at = dash._build_fx_lookup({bench_cur})
        bench_pairs = [
            (r.date, r.close_price / fx_at(bench_cur, r.date))
            for r in rows if fx_at(bench_cur, r.date)
        ]
        bench_norm = _normalize(bench_pairs, cutoff)
        bench_stats = _stats(bench_norm)

        series.append(schemas.BenchmarkSeries(
            key=ticker, label=label_map[ticker], color=_COLORS.get(ticker, "#888"),
            points=[schemas.BenchmarkPoint(**p) for p in bench_norm],
            **bench_stats,
        ))

    return schemas.BenchmarkChartResponse(series=series)

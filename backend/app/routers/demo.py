"""
HodlVault – Live Demo
─────────────────────
POST /api/demo/login  →  crea (o riutilizza) l'utente demo pre-popolato e
                         restituisce una coppia di JWT senza richiedere credenziali.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Tuple

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import hash_password, create_access_token, create_refresh_token

router = APIRouter()

# ── Credenziali demo (hash-only, nessuno può fare login con username+pw) ──────
_DEMO_PASSWORD = "hodlvault-demo-readonly-2024"

# ── Strumenti ─────────────────────────────────────────────────────────────────
_INSTRUMENTS: List[dict] = [
    dict(ticker="AAPL",    isin="US0378331005", name="Apple Inc.",
         asset_class="EQUITY", currency="USD", sector="Technology", country="USA"),
    dict(ticker="MSFT",    isin="US5949181045", name="Microsoft Corp.",
         asset_class="EQUITY", currency="USD", sector="Technology", country="USA"),
    dict(ticker="NVDA",    isin="US67066G1040", name="Nvidia Corp.",
         asset_class="EQUITY", currency="USD", sector="Technology", country="USA"),
    dict(ticker="VWCE.DE", isin="IE00BK5BQT80", name="Vanguard FTSE All-World ETF",
         asset_class="ETF",    currency="EUR", sector=None,          country="IRL"),
    dict(ticker="BTC-USD", isin=None,           name="Bitcoin",
         asset_class="CRYPTO", currency="USD", sector=None,          country=None),
    dict(ticker="ENI.MI",  isin="IT0003132476", name="Eni S.p.A.",
         asset_class="EQUITY", currency="EUR", sector="Energy",      country="ITA"),
    dict(ticker="AGGH.MI", isin="IE00BDBRDM35", name="iShares Core Global Aggregate Bond ETF",
         asset_class="ETF",    currency="EUR", sector=None,          country=None),
    dict(ticker="SGLD.MI", isin="IE00B4ND3602", name="Invesco Physical Gold ETC",
         asset_class="ETF",    currency="EUR", sector=None,          country=None),
    dict(ticker="BTCE.DE", isin="DE000A27Z304", name="ETC Group Physical Bitcoin",
         asset_class="ETF",    currency="EUR", sector=None,          country=None),
]

# ── Prezzi mensili: gen 2024 → mag 2026 (29 valori per strumento) ─────────────
_START_MONTH = date(2024, 1, 1)

_MONTHLY_PRICES: dict[str, list[float]] = {
    "AAPL": [
        185, 184, 171, 165, 192, 213, 222, 226, 226, 225, 237, 254,  # 2024
        230, 228, 212, 198, 207, 198, 201, 215, 221, 225, 232, 247,  # 2025
        238, 242, 233, 212, 198,                                      # gen-mag 2026
    ],
    "MSFT": [
        375, 405, 421, 400, 430, 446, 428, 418, 441, 425, 435, 448,
        462, 415, 380, 360, 395, 450, 468, 452, 445, 440, 436, 430,
        420, 408, 385, 395, 400,
    ],
    "NVDA": [
         49,  67,  88,  76,  94, 121, 117, 116, 121, 140, 145, 135,
        125, 111, 109,  88, 114, 131, 141, 130, 124, 135, 148, 137,
        132, 140, 111,  96, 113,
    ],
    "VWCE.DE": [
         95,  97, 101,  97, 105, 110, 112, 114, 116, 115, 120, 125,
        128, 126, 122, 118, 124, 129, 132, 130, 128, 131, 134, 136,
        132, 135, 130, 128, 131,
    ],
    "BTC-USD": [
         42000,  51000,  68000,  65000,  67000,  62000,  66000,  58000,
         60000,  70000,  96000,  94000, 104000,  95000,  86000,  80000,
         95000, 107000, 119000, 100000,  89000,  95000, 100000,  97000,
        102000,  88000,  82000,  79000, 103000,
    ],
    "ENI.MI": [
        14.0, 14.5, 15.1, 14.8, 14.2, 14.7, 14.5, 14.3, 14.6, 15.0, 14.8, 14.5,
        14.2, 14.0, 13.8, 13.5, 13.9, 14.1, 14.3, 14.0, 13.8, 13.6, 13.4, 13.2,
        13.5, 13.0, 12.8, 12.5, 12.9,
    ],
    "AGGH.MI": [
        5.05, 5.03, 5.00, 4.98, 4.99, 5.01, 5.02, 5.00, 4.97, 4.95, 4.93, 4.90,
        4.92, 4.95, 4.98, 4.96, 4.99, 5.02, 5.05, 5.03, 5.01, 5.04, 5.06, 5.05,
        5.07, 5.06, 5.08, 5.10, 5.09,
    ],
    "SGLD.MI": [
        18.0, 18.6, 19.5, 19.2, 19.8, 20.5, 21.0, 21.8, 22.5, 23.0, 23.8, 24.2,
        24.8, 25.5, 26.0, 25.6, 26.4, 27.2, 28.0, 28.6, 29.0, 29.5, 30.2, 30.8,
        31.0, 31.5, 30.8, 31.2, 32.0,
    ],
    "BTCE.DE": [
        38.9, 47.2, 63.0, 60.2, 62.0, 57.4, 61.1, 53.7, 55.6, 64.8, 88.9, 87.0,
        96.3, 88.0, 79.6, 74.1, 88.0, 99.1, 110.2, 92.6, 82.4, 88.0, 92.6, 89.8,
        94.4, 81.5, 75.9, 73.1, 95.4,
    ],
}

# ── Tassi EUR/USD mensili: gen 2024 → mag 2026 ────────────────────────────────
_FX_USD: list[float] = [
    1.095, 1.079, 1.089, 1.072, 1.083, 1.074, 1.085, 1.104, 1.116, 1.082, 1.056, 1.038,
    1.042, 1.047, 1.085, 1.080, 1.126, 1.132, 1.172, 1.117, 1.090, 1.115, 1.049, 1.038,
    1.030, 1.047, 1.084, 1.138, 1.136,
]

# ── Portafogli demo ───────────────────────────────────────────────────────────
_PORTFOLIOS = [
    ("Portfolio Principale", "Interactive Brokers", "EUR"),
    ("Satellite Crypto",     "Coinbase",            "EUR"),
]

# ── Transazioni ───────────────────────────────────────────────────────────────
# (idx_portfolio, ticker, tipo, data, qty, prezzo, valuta, fx_rate, commissioni)
_TRANSACTIONS = [
    # Portfolio 0 – Portfolio Principale
    (0, "VWCE.DE", "BUY",  date(2024,  1, 20),  20,   95.0,   "EUR", 1.000,  0.50),
    (0, "VWCE.DE", "BUY",  date(2024,  8, 12),  15,  114.0,   "EUR", 1.000,  0.50),
    (0, "AAPL",    "BUY",  date(2024,  1, 22),  10,  185.0,   "USD", 1.095,  1.99),
    (0, "AAPL",    "BUY",  date(2024, 10, 18),   5,  225.0,   "USD", 1.082,  0.99),
    (0, "MSFT",    "BUY",  date(2024,  2, 12),   6,  405.0,   "USD", 1.079,  1.99),
    (0, "MSFT",    "BUY",  date(2025,  1, 10),   4,  462.0,   "USD", 1.042,  1.99),
    (0, "NVDA",    "BUY",  date(2024,  1, 25),  50,   49.0,   "USD", 1.095,  1.99),
    (0, "NVDA",    "BUY",  date(2024,  6, 18),  30,  121.0,   "USD", 1.074,  1.99),
    (0, "ENI.MI",  "BUY",  date(2024,  3, 12), 200,   15.1,   "EUR", 1.000,  0.50),
    (0, "AAPL",    "SELL", date(2025,  1, 20),   3,  230.0,   "USD", 1.042,  0.99),
    (0, "NVDA",    "SELL", date(2025,  4, 10),  10,   88.0,   "USD", 1.080,  1.99),
    (0, "AGGH.MI", "BUY",  date(2024,  2, 15), 600,    5.03,   "EUR", 1.000,  0.50),
    (0, "SGLD.MI", "BUY",  date(2024,  3,  1), 150,   19.50,   "EUR", 1.000,  0.50),
    # Portfolio 1 – Satellite Crypto
    (1, "BTC-USD", "BUY",  date(2024,  1, 12),  0.10, 42000.0, "USD", 1.095, 5.00),
    (1, "BTC-USD", "BUY",  date(2024,  4, 22),  0.05, 65000.0, "USD", 1.072, 3.00),
    (1, "BTC-USD", "BUY",  date(2025,  3,  8),  0.03, 82000.0, "USD", 1.085, 2.50),
    (1, "BTCE.DE", "BUY",  date(2024,  3, 15), 30,    63.00,   "EUR", 1.000, 2.00),
]

# ── Dividendi & cedole ────────────────────────────────────────────────────────
# (idx_portfolio, ticker, data, importo, valuta, fx_rate, tipo)
# NB: VWCE è ad ACCUMULO → nessuna distribuzione. SGLD (oro) e BTCE (bitcoin) non
# distribuiscono. AGGH è un ETF obbligazionario a DISTRIBUZIONE → paga cedole.
_DIVIDENDS = [
    # Apple (USD) – trimestrale
    (0, "AAPL",   date(2024,  2, 15),   2.50, "USD", 1.079, "DIVIDEND"),
    (0, "AAPL",   date(2024,  5, 15),   2.50, "USD", 1.083, "DIVIDEND"),
    (0, "AAPL",   date(2024,  8, 15),   2.60, "USD", 1.104, "DIVIDEND"),
    (0, "AAPL",   date(2024, 11, 15),   3.70, "USD", 1.056, "DIVIDEND"),
    (0, "AAPL",   date(2025,  2, 15),   3.00, "USD", 1.047, "DIVIDEND"),
    (0, "AAPL",   date(2025,  5, 15),   3.00, "USD", 1.126, "DIVIDEND"),
    (0, "AAPL",   date(2025,  8, 15),   3.00, "USD", 1.117, "DIVIDEND"),
    (0, "AAPL",   date(2025, 11, 15),   3.00, "USD", 1.049, "DIVIDEND"),
    (0, "AAPL",   date(2026,  2, 16),   3.10, "USD", 1.047, "DIVIDEND"),
    (0, "AAPL",   date(2026,  5, 15),   3.10, "USD", 1.136, "DIVIDEND"),
    # Microsoft (USD) – trimestrale
    (0, "MSFT",   date(2024,  3, 14),   4.50, "USD", 1.089, "DIVIDEND"),
    (0, "MSFT",   date(2024,  6, 13),   4.50, "USD", 1.074, "DIVIDEND"),
    (0, "MSFT",   date(2024,  9, 12),   4.50, "USD", 1.116, "DIVIDEND"),
    (0, "MSFT",   date(2024, 12, 12),   4.50, "USD", 1.038, "DIVIDEND"),
    (0, "MSFT",   date(2025,  3, 13),   7.50, "USD", 1.085, "DIVIDEND"),
    (0, "MSFT",   date(2025,  6, 12),   7.50, "USD", 1.132, "DIVIDEND"),
    (0, "MSFT",   date(2025,  9, 11),   7.50, "USD", 1.090, "DIVIDEND"),
    (0, "MSFT",   date(2025, 12, 11),   7.50, "USD", 1.038, "DIVIDEND"),
    (0, "MSFT",   date(2026,  3, 12),   7.70, "USD", 1.084, "DIVIDEND"),
    (0, "MSFT",   date(2026,  6, 11),   7.70, "USD", 1.150, "DIVIDEND"),
    # Eni (EUR) – acconto + saldo
    (0, "ENI.MI", date(2024,  5, 22),  90.0,  "EUR", 1.000, "DIVIDEND"),
    (0, "ENI.MI", date(2024,  9, 25),  90.0,  "EUR", 1.000, "DIVIDEND"),
    (0, "ENI.MI", date(2025,  5, 21),  95.0,  "EUR", 1.000, "DIVIDEND"),
    (0, "ENI.MI", date(2025,  9, 24),  95.0,  "EUR", 1.000, "DIVIDEND"),
    (0, "ENI.MI", date(2026,  5, 20),  98.0,  "EUR", 1.000, "DIVIDEND"),
    # AGGH – ETF obbligazionario a distribuzione → cedole trimestrali
    (0, "AGGH.MI", date(2024,  5, 31),  17.0,  "EUR", 1.000, "COUPON"),
    (0, "AGGH.MI", date(2024,  8, 30),  18.0,  "EUR", 1.000, "COUPON"),
    (0, "AGGH.MI", date(2024, 11, 29),  18.0,  "EUR", 1.000, "COUPON"),
    (0, "AGGH.MI", date(2025,  2, 28),  18.5,  "EUR", 1.000, "COUPON"),
    (0, "AGGH.MI", date(2025,  5, 30),  18.5,  "EUR", 1.000, "COUPON"),
    (0, "AGGH.MI", date(2025,  8, 29),  19.0,  "EUR", 1.000, "COUPON"),
    (0, "AGGH.MI", date(2025, 11, 28),  19.0,  "EUR", 1.000, "COUPON"),
    (0, "AGGH.MI", date(2026,  2, 27),  19.5,  "EUR", 1.000, "COUPON"),
    (0, "AGGH.MI", date(2026,  5, 29),  19.5,  "EUR", 1.000, "COUPON"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def _build_weekly(anchors: list[float], start: date) -> List[Tuple[date, float]]:
    """Interpola linearmente fra i prezzi mensili e restituisce un punto ogni 7 giorni."""
    months: list[date] = []
    m = start
    for _ in anchors:
        months.append(m)
        m = _next_month(m)

    result: List[Tuple[date, float]] = []
    current = start
    end = months[-1]
    while current <= end:
        for i in range(len(months) - 1):
            if months[i] <= current < months[i + 1]:
                span = (months[i + 1] - months[i]).days
                t = (current - months[i]).days / span if span else 0.0
                price = anchors[i] + t * (anchors[i + 1] - anchors[i])
                result.append((current, round(price, 4)))
                break
        current += timedelta(days=7)
    return result


def _seed(db: Session, user: models.User) -> None:
    """Popola strumenti, prezzi, tassi FX, portafogli, transazioni e dividendi."""

    # ── Strumenti ─────────────────────────────────────────────────────────────
    inst_map: dict[str, models.Instrument] = {}
    for d in _INSTRUMENTS:
        inst = None
        if d["isin"]:
            inst = db.query(models.Instrument).filter(
                models.Instrument.isin == d["isin"]
            ).first()
        if not inst:
            inst = db.query(models.Instrument).filter(
                models.Instrument.ticker == d["ticker"]
            ).first()
        if not inst:
            inst = models.Instrument(
                ticker=d["ticker"], isin=d["isin"], name=d["name"],
                asset_class=models.AssetClass(d["asset_class"]),
                currency=d["currency"], sector=d["sector"], country=d["country"],
            )
            db.add(inst)
            db.flush()
        inst_map[d["ticker"]] = inst

    # ── Storico prezzi (settimanale) ──────────────────────────────────────────
    for ticker, monthly in _MONTHLY_PRICES.items():
        inst = inst_map[ticker]
        if db.query(models.PriceHistory).filter(
            models.PriceHistory.instrument_id == inst.id
        ).count() >= 50:
            continue
        existing_dates = {
            r.date for r in db.query(models.PriceHistory.date).filter(
                models.PriceHistory.instrument_id == inst.id
            ).all()
        }
        for d, price in _build_weekly(monthly, _START_MONTH):
            if d not in existing_dates:
                db.add(models.PriceHistory(
                    instrument_id=inst.id, date=d,
                    close_price=price, currency=inst.currency,
                ))

    # ── Tassi EUR/USD ─────────────────────────────────────────────────────────
    if db.query(models.FxRate).filter(models.FxRate.pair == "USD").count() < 50:
        existing_fx = {
            r.date for r in db.query(models.FxRate.date).filter(
                models.FxRate.pair == "USD"
            ).all()
        }
        for d, rate in _build_weekly(_FX_USD, _START_MONTH):
            if d not in existing_fx:
                db.add(models.FxRate(date=d, pair="USD", rate=rate))

    db.commit()

    # ── Look-through ETF (VWCE = FTSE All-World, azionario globale) ──────────────
    vwce = inst_map.get("VWCE.DE")
    if vwce and not db.query(models.EtfProfile).filter(models.EtfProfile.instrument_id == vwce.id).first():
        db.add(models.EtfProfile(
            instrument_id=vwce.id, equity_pct=0.99, bond_pct=0.0,
            commodity_pct=0.0, cash_pct=0.01, other_pct=0.0,
            category="Azionario Globale Large Cap",
        ))
        _VWCE_HOLDINGS = [
            ("NVDA", "NVIDIA Corp", 0.047), ("AAPL", "Apple Inc", 0.039),
            ("MSFT", "Microsoft Corp", 0.030), ("AMZN", "Amazon.com Inc", 0.025),
            ("META", "Meta Platforms Inc", 0.018), ("GOOGL", "Alphabet Inc", 0.015),
            ("AVGO", "Broadcom Inc", 0.014), ("TSLA", "Tesla Inc", 0.011),
            ("BRK-B", "Berkshire Hathaway", 0.009), ("JPM", "JPMorgan Chase", 0.008),
        ]
        for sym, nm, w in _VWCE_HOLDINGS:
            db.add(models.EtfHolding(etf_id=vwce.id, symbol=sym, name=nm, weight=w))
        _VWCE_SECTORS = [
            ("technology", 0.26), ("financial_services", 0.16), ("healthcare", 0.11),
            ("consumer_cyclical", 0.11), ("industrials", 0.10), ("communication_services", 0.08),
            ("consumer_defensive", 0.06), ("energy", 0.04), ("basic_materials", 0.04),
            ("utilities", 0.025), ("realestate", 0.025),
        ]
        for key, w in _VWCE_SECTORS:
            db.add(models.EtfSectorWeight(etf_id=vwce.id, sector_key=key, weight=w))
        # Paese delle holding (per il look-through Paese degli ETF)
        for sym, nm, _ in _VWCE_HOLDINGS:
            if not db.query(models.SecurityProfile).filter(models.SecurityProfile.symbol == sym).first():
                db.add(models.SecurityProfile(symbol=sym, country="United States"))
        db.commit()

    # ── Profili degli ETF obbligazionario e oro (asset class via look-through) ───
    aggh = inst_map.get("AGGH.MI")
    if aggh and not db.query(models.EtfProfile).filter(models.EtfProfile.instrument_id == aggh.id).first():
        db.add(models.EtfProfile(instrument_id=aggh.id, bond_pct=1.0, category="Obbligazionario Globale Aggregate"))
    sgld = inst_map.get("SGLD.MI")
    if sgld and not db.query(models.EtfProfile).filter(models.EtfProfile.instrument_id == sgld.id).first():
        db.add(models.EtfProfile(instrument_id=sgld.id, commodity_pct=1.0, category="Materie Prime - Oro"))
    btce = inst_map.get("BTCE.DE")
    if btce and not db.query(models.EtfProfile).filter(models.EtfProfile.instrument_id == btce.id).first():
        db.add(models.EtfProfile(instrument_id=btce.id, category="Crypto - Bitcoin"))
    db.commit()

    # ── Allocazione per area geografica degli ETF (guardia indipendente) ─────────
    _ETF_REGIONS = {
        "VWCE.DE": [("Nord America", 0.64), ("Europa", 0.14), ("Giappone", 0.06),
                    ("Asia-Pacifico", 0.04), ("Mercati Emergenti", 0.10), ("Altri mercati", 0.02)],
        "AGGH.MI": [("Nord America", 0.40), ("Europa", 0.30), ("Giappone", 0.13),
                    ("Mercati Emergenti", 0.10), ("Asia-Pacifico", 0.04), ("Altri mercati", 0.03)],
    }
    for tk, regs in _ETF_REGIONS.items():
        inst = inst_map.get(tk)
        if inst and not db.query(models.EtfRegionWeight).filter(models.EtfRegionWeight.etf_id == inst.id).first():
            for region, w in regs:
                db.add(models.EtfRegionWeight(etf_id=inst.id, region=region, weight=w))
    db.commit()

    # ── Portafogli ────────────────────────────────────────────────────────────
    portfolios: list[models.Portfolio] = []
    for name, broker, currency in _PORTFOLIOS:
        p = db.query(models.Portfolio).filter(
            models.Portfolio.user_id == user.id,
            models.Portfolio.name == name,
        ).first()
        if not p:
            p = models.Portfolio(
                user_id=user.id, name=name, broker=broker, currency=currency,
            )
            db.add(p)
            db.flush()
        portfolios.append(p)

    db.commit()

    # ── Transazioni ───────────────────────────────────────────────────────────
    for pidx, ticker, tx_type, tx_date, qty, price, currency, fx_rate, fees in _TRANSACTIONS:
        p = portfolios[pidx]
        inst = inst_map[ticker]
        exists = db.query(models.Transaction).filter(
            models.Transaction.portfolio_id == p.id,
            models.Transaction.instrument_id == inst.id,
            models.Transaction.date == tx_date,
            models.Transaction.quantity == qty,
        ).first()
        if not exists:
            db.add(models.Transaction(
                portfolio_id=p.id, instrument_id=inst.id,
                type=models.TransactionType(tx_type),
                date=tx_date, quantity=qty, price=price,
                fees=fees, currency=currency, fx_rate=fx_rate,
            ))

    # ── Dividendi ─────────────────────────────────────────────────────────────
    for pidx, ticker, div_date, amount, currency, fx_rate, div_type in _DIVIDENDS:
        p = portfolios[pidx]
        inst = inst_map[ticker]
        exists = db.query(models.DividendEvent).filter(
            models.DividendEvent.portfolio_id == p.id,
            models.DividendEvent.instrument_id == inst.id,
            models.DividendEvent.date == div_date,
        ).first()
        if not exists:
            db.add(models.DividendEvent(
                portfolio_id=p.id, instrument_id=inst.id,
                date=div_date, amount=amount,
                currency=currency, fx_rate=fx_rate,
                type=models.DividendType(div_type),
                source=models.DividendSource.IMPORT,
            ))

    db.commit()


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/login", response_model=schemas.Token)
def demo_login(db: Session = Depends(get_db)):
    """
    Accesso istantaneo alla modalità demo — nessuna credenziale richiesta.
    Crea e popola l'account demo al primo utilizzo.
    """
    DEMO_USERNAME = "demo"
    DEMO_EMAIL    = "demo@hodlvault.app"

    user = db.query(models.User).filter(
        models.User.username == DEMO_USERNAME
    ).first()

    if not user:
        user = models.User(
            username=DEMO_USERNAME,
            email=DEMO_EMAIL,
            hashed_password=hash_password(_DEMO_PASSWORD),
            is_active=True,
            is_admin=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # Popola i dati solo se i portafogli non esistono ancora
    has_portfolios = db.query(models.Portfolio).filter(
        models.Portfolio.user_id == user.id
    ).count() > 0
    if not has_portfolios:
        _seed(db, user)

    return schemas.Token(
        access_token=create_access_token({"sub": str(user.id)}),
        refresh_token=create_refresh_token({"sub": str(user.id)}),
    )

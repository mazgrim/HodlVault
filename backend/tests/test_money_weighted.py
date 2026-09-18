"""
Rendimento money-weighted (XIRR): tiene conto di quanto capitale era investito
in ogni momento, quindi segue il P&L reale. A differenza del TWR può avere segno
opposto. Dati fittizi.
"""
from datetime import date, timedelta

from app import models
from app.services.calculations import _xirr, DashboardCalculator


def test_xirr_semplice():
    # -1000 investiti, +1100 dopo un anno → ~10% annuo.
    r = _xirr([(date(2020, 1, 1), -1000.0), (date(2021, 1, 1), 1100.0)])
    assert r is not None
    assert abs(r - 0.10) < 0.005


def test_xirr_richiede_segni_opposti():
    assert _xirr([(date(2020, 1, 1), -100.0)]) is None
    assert _xirr([(date(2020, 1, 1), -100.0), (date(2021, 1, 1), -50.0)]) is None


def test_money_weighted_positivo_con_profitto(db, user, portfolio):
    inst = models.Instrument(ticker="ZETA.MI", isin=None, name="Zeta", currency="EUR")
    db.add(inst); db.flush()
    d0 = date.today() - timedelta(days=550)
    db.add(models.Transaction(
        portfolio_id=portfolio.id, instrument_id=inst.id, type=models.TransactionType.BUY,
        date=d0, quantity=100, price=10.0, fees=0.0, currency="EUR", fx_rate=1.0))
    db.add(models.PriceHistory(instrument_id=inst.id, date=date.today(),
                               close_price=12.0, currency="EUR"))
    db.commit()

    k = DashboardCalculator(db, user.id).kpis()
    # +200 di P&L su 1000 investiti in ~1,5 anni → money-weighted positivo.
    assert k.money_weighted_return is not None
    assert k.money_weighted_return > 0

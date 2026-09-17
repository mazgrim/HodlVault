"""
Posizioni chiuse in dashboard: strumenti con quantità netta tornata a 0 dopo una
vendita. Prezzi medi acquisto/vendita, P&L realizzato € e %, valore attuale.
"""
from datetime import date

from app import models
from app.services.calculations import DashboardCalculator


def _inst(db, ticker="ACME", isin="TS0000000400", name="ACME", currency="EUR"):
    i = models.Instrument(ticker=ticker, isin=isin, name=name, currency=currency)
    db.add(i); db.flush()
    return i


def _tx(db, p, i, ttype, qty, price, d, fees=0.0):
    db.add(models.Transaction(
        portfolio_id=p.id, instrument_id=i.id, type=ttype, date=d,
        quantity=qty, price=price, fees=fees, currency="EUR", fx_rate=1.0,
    ))


def test_posizione_chiusa_calcoli(db, user, portfolio):
    inst = _inst(db)
    _tx(db, portfolio, inst, models.TransactionType.BUY, 10, 100.0, date(2024, 1, 1))
    _tx(db, portfolio, inst, models.TransactionType.SELL, 10, 120.0, date(2024, 6, 1))
    # prezzo attuale per il valore ipotetico
    db.add(models.PriceHistory(instrument_id=inst.id, date=date(2024, 12, 1), close_price=150.0))
    db.commit()

    rows = DashboardCalculator(db, user.id).closed_positions(portfolio.id)
    assert len(rows) == 1
    r = rows[0]
    assert r.ticker == "ACME"
    assert r.quantity == 10
    assert r.avg_buy_price == 100.0
    assert r.avg_sell_price == 120.0
    assert r.buy_value == 1000.0            # 100 × 10
    assert r.sell_value == 1200.0           # 120 × 10
    assert r.realized_pnl == 200.0          # (120-100)*10, lordo
    assert r.realized_pnl_pct == 20.0       # 200 / 1000
    assert r.realized_pnl_net == 148.0      # 200 − 26% = 148 (equity)
    assert r.current_price == 150.0
    assert r.current_value == 1500.0        # 150 * 10 (valore ipotetico oggi)
    assert r.first_buy_date == date(2024, 1, 1)
    assert r.last_sell_date == date(2024, 6, 1)


def test_posizione_aperta_non_e_chiusa(db, user, portfolio):
    inst = _inst(db)
    _tx(db, portfolio, inst, models.TransactionType.BUY, 10, 100.0, date(2024, 1, 1))
    _tx(db, portfolio, inst, models.TransactionType.SELL, 4, 120.0, date(2024, 6, 1))  # parziale
    db.commit()
    rows = DashboardCalculator(db, user.id).closed_positions(portfolio.id)
    assert rows == []                        # ancora 6 quote in portafoglio → aperta


def test_perdita_realizzata(db, user, portfolio):
    inst = _inst(db)
    _tx(db, portfolio, inst, models.TransactionType.BUY, 5, 200.0, date(2024, 1, 1))
    _tx(db, portfolio, inst, models.TransactionType.SELL, 5, 150.0, date(2024, 3, 1))
    db.commit()
    rows = DashboardCalculator(db, user.id).closed_positions(portfolio.id)
    assert len(rows) == 1
    assert rows[0].realized_pnl == -250.0    # (150-200)*5
    assert rows[0].realized_pnl_net == -250.0  # perdita: nessuna imposta
    assert rows[0].current_price is None     # nessun prezzo salvato
    assert rows[0].current_value is None

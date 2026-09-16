"""
Import: avviso "vendita senza acquisto corrispondente". Un file che contiene il
SELL ma non il BUY porterebbe la posizione in negativo → va segnalato in anteprima.
"""
from datetime import date

from app import models
from app.schemas import ParsedTransaction
from app.routers.import_data import _annotate_position_warnings


def _sell(name="ACME", isin="TS0000000300", qty=25.0, d=date(2025, 2, 14)):
    return ParsedTransaction(
        date=d, type=models.TransactionType.SELL, ticker=None, isin=isin, name=name,
        quantity=qty, price=100.0, fees=0.0, currency="EUR",
    )


def _buy(name="ACME", isin="TS0000000300", qty=25.0, d=date(2024, 8, 2)):
    return ParsedTransaction(
        date=d, type=models.TransactionType.BUY, ticker=None, isin=isin, name=name,
        quantity=qty, price=100.0, fees=0.0, currency="EUR",
    )


def test_sell_senza_buy_viene_segnalato(db, portfolio):
    rows = [_sell()]
    _annotate_position_warnings(rows, portfolio.id, db)
    assert rows[0].warning is not None
    assert "Vendita senza acquisto" in rows[0].warning


def test_buy_e_sell_nello_stesso_import_nessun_avviso(db, portfolio):
    rows = [_buy(), _sell()]  # 25 comprate poi 25 vendute → posizione 0, ok
    _annotate_position_warnings(rows, portfolio.id, db)
    assert all(r.warning is None for r in rows)


def test_sell_coperto_da_posizione_esistente_nessun_avviso(db, portfolio):
    # BUY già presente nel portafoglio (import precedente): il SELL è a copertura.
    inst = models.Instrument(ticker="ACME", isin="TS0000000300", name="ACME", currency="EUR")
    db.add(inst); db.flush()
    db.add(models.Transaction(
        portfolio_id=portfolio.id, instrument_id=inst.id, type=models.TransactionType.BUY,
        date=date(2024, 8, 2), quantity=25, price=100.0, fees=0.0, currency="EUR", fx_rate=1.0,
    ))
    db.commit()
    rows = [_sell()]
    _annotate_position_warnings(rows, portfolio.id, db)
    assert rows[0].warning is None


def test_sell_parziale_scoperto_segnalato(db, portfolio):
    rows = [_buy(qty=10), _sell(qty=25)]  # compra 10, vende 25 → -15 scoperto
    _annotate_position_warnings(rows, portfolio.id, db)
    sell_row = [r for r in rows if r.type == models.TransactionType.SELL][0]
    assert sell_row.warning is not None

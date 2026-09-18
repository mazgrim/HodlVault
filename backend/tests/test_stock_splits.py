"""
Split / raggruppamento azionario.

Uno strumento comprato 500 (300+200) e poi raggruppato 10:1 diventa 50 azioni:
vendendone 50 la posizione deve risultare CHIUSA (non 450 aperte) e il P&L
realizzato corretto. Il costo totale è invariante allo split. Dati fittizi.
"""
from datetime import date

from app import models
from app.services.calculations import DashboardCalculator


def _seed(db, portfolio):
    inst = models.Instrument(ticker="ALFA.MI", isin=None, name="Alpha", currency="EUR")
    db.add(inst); db.flush()
    for d, ttype, qty, price in [
        (date(2020, 1, 24), models.TransactionType.BUY, 300, 0.9193),
        (date(2020, 2, 24), models.TransactionType.BUY, 200, 0.899),
        (date(2025, 9, 18), models.TransactionType.SELL, 50, 0.86),
    ]:
        db.add(models.Transaction(
            portfolio_id=portfolio.id, instrument_id=inst.id, type=ttype, date=d,
            quantity=qty, price=price, fees=7.0, currency="EUR", fx_rate=1.0))
    db.add(models.PriceHistory(instrument_id=inst.id, date=date(2025, 9, 18),
                               close_price=0.86, currency="EUR"))
    db.commit()
    return inst


def test_senza_split_resta_aperta_450(db, user, portfolio):
    inst = _seed(db, portfolio)
    calc = DashboardCalculator(db, user.id)
    pos = next((p for p in calc.open_positions() if p.instrument_id == inst.id), None)
    assert pos is not None
    assert pos.quantity == 450          # 500 comprate − 50 vendute (bug senza split)


def test_con_split_10_a_1_posizione_chiusa(db, user, portfolio):
    inst = _seed(db, portfolio)
    # Raggruppamento 10:1 tra gli acquisti e la vendita: 10 vecchie → 1 nuova.
    db.add(models.StockSplit(instrument_id=inst.id, date=date(2024, 6, 1),
                             old_shares=10, new_shares=1))
    db.commit()

    calc = DashboardCalculator(db, user.id)

    # Non più tra le posizioni aperte.
    assert all(p.instrument_id != inst.id for p in calc.open_positions())

    # Chiusa: 50 comprate (post-split) − 50 vendute = 0.
    closed = next((c for c in calc.closed_positions() if c.instrument_id == inst.id), None)
    assert closed is not None
    assert closed.quantity == 50                       # quote vendute (post-split)
    # Costo invariante allo split: 30×0,9193×10 + 20×0,899×10 + commissioni.
    assert round(closed.buy_value, 2) == round(300 * 0.9193 + 200 * 0.899 + 14, 2)
    # Perdita reale: incasso (43 − 7) − costo.
    assert round(closed.realized_pnl, 2) == round((50 * 0.86 - 7) - closed.buy_value, 2)


def test_split_endpoints_crud(client, db, portfolio):
    inst = models.Instrument(ticker="BETA.MI", isin=None, name="Beta", currency="EUR")
    db.add(inst); db.commit()

    r = client.post("/api/splits/", json={
        "instrument_id": inst.id, "date": "2024-06-01",
        "old_shares": 10, "new_shares": 1, "note": "raggruppamento",
    })
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    lst = client.get("/api/splits/", params={"instrument_id": inst.id})
    assert lst.status_code == 200
    assert len(lst.json()) == 1

    # Duplicato stessa data → 409
    dup = client.post("/api/splits/", json={
        "instrument_id": inst.id, "date": "2024-06-01", "old_shares": 2, "new_shares": 1})
    assert dup.status_code == 409

    assert client.delete(f"/api/splits/{sid}").status_code == 204
    assert client.get("/api/splits/", params={"instrument_id": inst.id}).json() == []

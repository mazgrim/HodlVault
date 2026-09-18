"""
Dettaglio strumento filtrabile per portafoglio.

Lo stesso ticker è un unico strumento condiviso tra i portafogli; il dettaglio
può essere ristretto a un portafoglio così lo stesso titolo su broker diversi non
viene mischiato (transazioni, dividendi e posizione riflettono solo lo scope).
Dati fittizi.
"""
from datetime import date

from app import models


def _pf(db, user, name, broker):
    p = models.Portfolio(user_id=user.id, name=name, broker=broker)
    db.add(p); db.flush()
    return p


def _tx(db, pid, iid, ttype, d, qty, price):
    db.add(models.Transaction(
        portfolio_id=pid, instrument_id=iid, type=ttype, date=d,
        quantity=qty, price=price, fees=0.0, currency="EUR", fx_rate=1.0))


def _setup(db, user, portfolio):
    # portfolio (fixture) = broker A; ne creo un secondo = broker B.
    pf_a = portfolio
    pf_a.broker = "Broker A"
    pf_b = _pf(db, user, "PF B", "Broker B")

    inst = models.Instrument(ticker="AAA.MI", isin=None, name="Alpha", currency="EUR")
    db.add(inst); db.flush()

    # Broker A: aperta (10 + 12 = 22)
    _tx(db, pf_a.id, inst.id, models.TransactionType.BUY, date(2024, 12, 31), 10, 100.0)
    _tx(db, pf_a.id, inst.id, models.TransactionType.BUY, date(2025, 4, 7), 12, 90.0)
    # Broker B: chiusa (20 - 20 = 0)
    _tx(db, pf_b.id, inst.id, models.TransactionType.BUY, date(2025, 1, 27), 20, 114.0)
    _tx(db, pf_b.id, inst.id, models.TransactionType.SELL, date(2026, 4, 28), 20, 178.0)

    db.add(models.PriceHistory(instrument_id=inst.id, date=date(2026, 6, 1),
                               close_price=180.0, currency="EUR"))
    db.commit()
    return inst, pf_a, pf_b


def _detail(client, iid, pid=None):
    params = {"portfolio_id": str(pid)} if pid else {}
    r = client.get(f"/api/market/instruments/{iid}/detail", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_detail_senza_filtro_aggrega_tutti(client, db, user, portfolio):
    inst, pf_a, pf_b = _setup(db, user, portfolio)
    d = _detail(client, inst.id)
    assert len(d["transactions"]) == 4
    assert d["position"]["quantity"] == 22          # 10+12 aperti (B si chiude)
    assert {p["id"] for p in d["portfolios"]} == {pf_a.id, pf_b.id}


def test_detail_filtrato_broker_b_e_chiuso(client, db, user, portfolio):
    inst, pf_a, pf_b = _setup(db, user, portfolio)
    d = _detail(client, inst.id, pf_b.id)
    # Solo le 2 operazioni del Broker B, posizione chiusa → nessuna posizione aperta.
    assert len(d["transactions"]) == 2
    assert d["position"] is None


def test_detail_filtrato_broker_a_resta_aperto(client, db, user, portfolio):
    inst, pf_a, pf_b = _setup(db, user, portfolio)
    d = _detail(client, inst.id, pf_a.id)
    assert len(d["transactions"]) == 2
    assert d["position"]["quantity"] == 22

"""
Portafogli: rinomina (PUT) ed eliminazione (DELETE) con cascade su transazioni e
dividendi. La UI "Portafogli" espone queste azioni, quindi verifichiamo che la
cancellazione non lasci dati orfani.
"""
from datetime import date

from app import models


def _seed_portfolio_with_data(db, user):
    p = models.Portfolio(user_id=user.id, name="Vecchio nome", broker="Fineco")
    db.add(p)
    db.flush()
    inst = models.Instrument(ticker="ACME", isin="TS0000000099", name="ACME", currency="EUR")
    db.add(inst)
    db.flush()
    db.add(models.Transaction(
        portfolio_id=p.id, instrument_id=inst.id, type=models.TransactionType.BUY,
        date=date(2025, 1, 1), quantity=10, price=100.0, fees=0.0, currency="EUR", fx_rate=1.0,
    ))
    db.add(models.DividendEvent(
        portfolio_id=p.id, instrument_id=inst.id, date=date(2025, 6, 1),
        amount=5.0, gross_amount=5.0, currency="EUR", fx_rate=1.0,
        type=models.DividendType.DIVIDEND, source=models.DividendSource.IMPORT,
    ))
    db.commit()
    return p


def test_rinomina_portafoglio(client, db, user):
    p = _seed_portfolio_with_data(db, user)
    resp = client.put(f"/api/portfolios/{p.id}", json={"name": "Nuovo nome", "broker": "Directa"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Nuovo nome"
    assert body["broker"] == "Directa"


def test_elimina_portafoglio_rimuove_transazioni_e_dividendi(client, db, user):
    p = _seed_portfolio_with_data(db, user)
    assert db.query(models.Transaction).filter_by(portfolio_id=p.id).count() == 1
    assert db.query(models.DividendEvent).filter_by(portfolio_id=p.id).count() == 1

    resp = client.delete(f"/api/portfolios/{p.id}")
    assert resp.status_code == 204, resp.text

    assert db.query(models.Portfolio).filter_by(id=p.id).first() is None
    # Cascade: niente transazioni/dividendi orfani.
    assert db.query(models.Transaction).filter_by(portfolio_id=p.id).count() == 0
    assert db.query(models.DividendEvent).filter_by(portfolio_id=p.id).count() == 0


def test_non_si_rinomina_portafoglio_di_altri(client, db, user):
    other = models.User(username="altro", email="altro@example.com", hashed_password="x")
    db.add(other)
    db.flush()
    p = models.Portfolio(user_id=other.id, name="Non mio")
    db.add(p)
    db.commit()
    resp = client.put(f"/api/portfolios/{p.id}", json={"name": "hack"})
    assert resp.status_code == 404

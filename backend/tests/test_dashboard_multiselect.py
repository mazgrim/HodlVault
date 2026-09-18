"""
Dashboard: selezione multipla di portafogli.

Lo scope (`portfolio_id`) può essere None (tutti), un singolo id o una lista di
id. Verifica il filtro in `_user_portfolio_ids`, l'aggregazione in
`open_positions` e il parsing del query param comma-separated nell'endpoint.
"""
from datetime import date

from app import models
from app.routers.market_data import _parse_pf_ids
from app.services.calculations import _user_portfolio_ids, DashboardCalculator


def _pf(db, user, name):
    p = models.Portfolio(user_id=user.id, name=name)
    db.add(p); db.flush()
    return p


def _instrument_with_buy(db, pf, ticker, name):
    inst = models.Instrument(ticker=ticker, isin=None, name=name, currency="EUR")
    db.add(inst); db.flush()
    db.add(models.Transaction(
        portfolio_id=pf.id, instrument_id=inst.id, type=models.TransactionType.BUY,
        date=date(2024, 1, 1), quantity=10, price=100.0, fees=0.0,
        currency="EUR", fx_rate=1.0,
    ))
    db.add(models.PriceHistory(instrument_id=inst.id, date=date(2024, 6, 1),
                               close_price=110.0, currency="EUR"))
    db.commit()
    return inst


def test_user_portfolio_ids_scope(db, user):
    pf1 = _pf(db, user, "PF1"); pf2 = _pf(db, user, "PF2"); pf3 = _pf(db, user, "PF3")
    db.commit()
    allids = {pf1.id, pf2.id, pf3.id}

    assert set(_user_portfolio_ids(user.id, db)) == allids                 # None = tutti
    assert set(_user_portfolio_ids(user.id, db, pf1.id)) == {pf1.id}       # singolo
    assert set(_user_portfolio_ids(user.id, db, [pf1.id, pf2.id])) == {pf1.id, pf2.id}
    # Id non dell'utente vengono ignorati (resta il sottoinsieme valido).
    assert set(_user_portfolio_ids(user.id, db, [pf1.id, 99999])) == {pf1.id}


def test_open_positions_rispetta_il_sottoinsieme(db, user):
    pf1 = _pf(db, user, "PF1"); pf2 = _pf(db, user, "PF2")
    db.commit()
    a = _instrument_with_buy(db, pf1, "AAA.MI", "Alpha")
    b = _instrument_with_buy(db, pf2, "BBB.MI", "Beta")

    calc = DashboardCalculator(db, user.id)

    def ids(scope):
        return {p.instrument_id for p in calc.open_positions(scope)}

    assert ids(None) == {a.id, b.id}                 # tutti
    assert ids([pf1.id]) == {a.id}                   # solo PF1
    assert ids([pf2.id]) == {b.id}                   # solo PF2
    assert ids([pf1.id, pf2.id]) == {a.id, b.id}     # due insieme


def test_parse_pf_ids():
    assert _parse_pf_ids(None) is None
    assert _parse_pf_ids("") is None
    assert _parse_pf_ids("3") == [3]
    assert _parse_pf_ids("3,5") == [3, 5]
    assert _parse_pf_ids("3, 5 ,x") == [3, 5]   # spazi e token non numerici ignorati


def test_endpoint_positions_multiselect(client, db, user):
    pf1 = _pf(db, user, "PF1"); pf2 = _pf(db, user, "PF2")
    db.commit()
    a = _instrument_with_buy(db, pf1, "AAA.MI", "Alpha")
    b = _instrument_with_buy(db, pf2, "BBB.MI", "Beta")

    r_all = client.get("/api/market/dashboard/positions")
    assert r_all.status_code == 200
    assert {p["instrument_id"] for p in r_all.json()} == {a.id, b.id}

    r_one = client.get("/api/market/dashboard/positions", params={"portfolio_id": str(pf1.id)})
    assert {p["instrument_id"] for p in r_one.json()} == {a.id}

    r_two = client.get("/api/market/dashboard/positions", params={"portfolio_id": f"{pf1.id},{pf2.id}"})
    assert {p["instrument_id"] for p in r_two.json()} == {a.id, b.id}

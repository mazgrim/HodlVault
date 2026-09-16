"""
Deduplica dividendi on-demand: rimuove gli incassi YAHOO che un import reale già
copre (regola "broker vince"), con anteprima prima della cancellazione.
"""
from datetime import date

from app import models


def _instrument(db, name="ACME CORPORATION", ticker="ACME", isin="TS0000000010"):
    inst = models.Instrument(ticker=ticker, isin=isin, name=name, currency="USD")
    db.add(inst)
    db.flush()
    return inst


def _dividend(db, portfolio, inst, d, amount, source, currency="EUR", fx=1.0, foreign=0.0):
    ev = models.DividendEvent(
        portfolio_id=portfolio.id, instrument_id=inst.id, date=d,
        amount=amount, gross_amount=amount + foreign, foreign_tax_amount=foreign,
        tax_amount=0.0, currency=currency, fx_rate=fx, type=models.DividendType.DIVIDEND,
        source=source,
    )
    db.add(ev)
    db.flush()
    return ev


def test_preview_e_deduplica_rimuove_solo_yahoo_coperti(client, db, portfolio):
    inst = _instrument(db)
    # Yahoo ex-date + import a 22 giorni (pagamento) → duplicato
    yahoo = _dividend(db, portfolio, inst, date(2025, 6, 11), 0.14, models.DividendSource.YAHOO,
                      currency="USD", fx=1.15, foreign=0.03)
    imp = _dividend(db, portfolio, inst, date(2025, 7, 3), 0.12, models.DividendSource.IMPORT)
    # Yahoo isolato (nessun import entro 60 gg) → NON duplicato, va tenuto
    solo = _dividend(db, portfolio, inst, date(2026, 6, 4), 0.14, models.DividendSource.YAHOO,
                     currency="USD", fx=1.16, foreign=0.03)
    db.commit()

    # Anteprima
    r = client.get("/api/dividends/duplicates")
    assert r.status_code == 200, r.text
    prev = r.json()
    assert len(prev) == 1
    assert prev[0]["id"] == yahoo.id
    assert prev[0]["covered_by_date"] == "2025-07-03"
    assert prev[0]["instrument_name"] == "ACME CORPORATION"

    # Esecuzione
    r = client.post("/api/dividends/deduplicate")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 1

    remaining = {e.id for e in db.query(models.DividendEvent).all()}
    assert yahoo.id not in remaining      # duplicato rimosso
    assert imp.id in remaining            # import reale intatto
    assert solo.id in remaining           # Yahoo isolato tenuto


def test_deduplica_idempotente(client, db, portfolio):
    inst = _instrument(db)
    _dividend(db, portfolio, inst, date(2025, 6, 11), 0.14, models.DividendSource.YAHOO,
              currency="USD", fx=1.15, foreign=0.03)
    _dividend(db, portfolio, inst, date(2025, 7, 3), 0.12, models.DividendSource.IMPORT)
    db.commit()

    assert client.post("/api/dividends/deduplicate").json()["deleted"] == 1
    # Seconda chiamata: niente più da rimuovere.
    assert client.post("/api/dividends/deduplicate").json()["deleted"] == 0
    assert client.get("/api/dividends/duplicates").json() == []

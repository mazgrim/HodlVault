"""Piano cedolare: conferma → DividendEvent (income) CERT_COUPON; salto → nulla."""
from datetime import date

import pytest

from app import models
from app.models import CouponStatus, CouponType, DividendType, PriceSource


@pytest.fixture()
def certificate(db):
    inst = models.Instrument(
        ticker="XS0000000009", isin="XS0000000009", name="Certificato Memory Cash Collect",
        asset_class=models.AssetClass.OTHER, currency="EUR",
        price_source=PriceSource.MANUAL,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _mk_coupon(client, certificate, **overrides):
    payload = {
        "instrument_id": certificate.id,
        "payment_date": "2026-07-10",
        "observation_date": "2026-07-03",
        "amount_per_unit": 2.5,
        "coupon_type": "CONDITIONAL",
        "memory_effect": True,
    }
    payload.update(overrides)
    res = client.post("/api/coupons/", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def test_confirm_creates_income_event(client, db, portfolio, certificate):
    coupon = _mk_coupon(client, certificate)

    res = client.post(f"/api/coupons/{coupon['id']}/confirm", json={
        "portfolio_id": portfolio.id,
        "gross_amount": 250.0,   # 100 certificati × 2,50 €
    })
    assert res.status_code == 200, res.text
    ev = res.json()

    # Evento income con sottotipo distinto e tassazione 26% (no ritenuta estera)
    assert ev["type"] == "CERT_COUPON"
    assert ev["gross_amount"] == 250.0
    assert ev["foreign_tax_amount"] == 0.0
    assert ev["tax_amount"] == pytest.approx(250.0 * 0.26)
    assert ev["amount"] == pytest.approx(250.0 * 0.74)
    assert ev["date"] == "2026-07-10"
    assert ev["currency"] == "EUR"

    row = db.query(models.DividendEvent).one()
    assert row.type == DividendType.CERT_COUPON
    assert row.portfolio_id == portfolio.id

    db.expire_all()
    sched = db.query(models.CouponSchedule).one()
    assert sched.status == CouponStatus.PAID
    assert sched.dividend_event_id == row.id

    # Una cedola già pagata non si riconferma
    res = client.post(f"/api/coupons/{coupon['id']}/confirm", json={
        "portfolio_id": portfolio.id, "gross_amount": 250.0,
    })
    assert res.status_code == 400


def test_confirm_with_memory_recovery_amount(client, db, portfolio, certificate):
    """L'importo effettivo può superare il piano (cedole in memoria recuperate)."""
    coupon = _mk_coupon(client, certificate)
    res = client.post(f"/api/coupons/{coupon['id']}/confirm", json={
        "portfolio_id": portfolio.id,
        "gross_amount": 500.0,   # cedola corrente + una in memoria
    })
    assert res.status_code == 200
    assert res.json()["gross_amount"] == 500.0


def test_skipped_coupon_creates_nothing(client, db, portfolio, certificate):
    coupon = _mk_coupon(client, certificate)

    res = client.post(f"/api/coupons/{coupon['id']}/skip")
    assert res.status_code == 200
    assert res.json()["status"] == "SKIPPED"

    # Nessun evento income generato: le cedole saltate (e quelle previste)
    # non entrano mai nei calcoli
    assert db.query(models.DividendEvent).count() == 0

    # E non è confermabile finché è SKIPPED
    res = client.post(f"/api/coupons/{coupon['id']}/confirm", json={
        "portfolio_id": portfolio.id, "gross_amount": 100.0,
    })
    assert res.status_code == 400

    # Reset: torna PLANNED
    res = client.post(f"/api/coupons/{coupon['id']}/reset")
    assert res.status_code == 200
    assert res.json()["status"] == "PLANNED"


def test_planned_coupons_do_not_touch_realized_dividends(client, db, portfolio, certificate):
    _mk_coupon(client, certificate)
    from app.services.calculations import DashboardCalculator
    calc = DashboardCalculator(db, portfolio.user_id)
    assert calc._calc_realized_dividends([portfolio.id]) == 0.0


def test_deleting_income_event_resets_coupon(client, db, portfolio, certificate):
    coupon = _mk_coupon(client, certificate)
    res = client.post(f"/api/coupons/{coupon['id']}/confirm", json={
        "portfolio_id": portfolio.id, "gross_amount": 250.0,
    })
    ev_id = res.json()["id"]

    res = client.delete(f"/api/dividends/{ev_id}")
    assert res.status_code == 204

    db.expire_all()
    sched = db.query(models.CouponSchedule).one()
    assert sched.status == CouponStatus.PLANNED
    assert sched.dividend_event_id is None


def test_bulk_create_quarterly_plan(client, db, certificate):
    rows = [
        {
            "instrument_id": certificate.id,
            "payment_date": f"2026-{m:02d}-15",
            "amount_per_unit": 2.5,
            "coupon_type": "CONDITIONAL",
            "memory_effect": True,
        }
        for m in (1, 4, 7, 10)
    ]
    res = client.post("/api/coupons/bulk", json=rows)
    assert res.status_code == 201
    assert len(res.json()) == 4
    assert db.query(models.CouponSchedule).count() == 4


def test_upcoming_calendar_lists_planned_of_held_instruments(client, db, portfolio, certificate):
    # 100 pezzi in posizione
    client.post("/api/transactions/", json={
        "portfolio_id": portfolio.id, "instrument_id": certificate.id, "type": "BUY",
        "date": "2026-01-10", "quantity": 100, "price": 95.0, "currency": "EUR", "fx_rate": 1,
    })
    # Tre cedole: una da confermare (resterà PLANNED), una PAID, una SKIPPED
    c1 = _mk_coupon(client, certificate, payment_date="2026-08-15")
    c2 = _mk_coupon(client, certificate, payment_date="2026-05-15")
    c3 = _mk_coupon(client, certificate, payment_date="2026-06-15")
    client.post(f"/api/coupons/{c2['id']}/confirm", json={"portfolio_id": portfolio.id, "gross_amount": 250.0})
    client.post(f"/api/coupons/{c3['id']}/skip")

    res = client.get("/api/coupons/upcoming")
    assert res.status_code == 200
    rows = res.json()
    # Solo la PLANNED, con stima lordo = 100 × 2,50 (valuta EUR → stesso valore in EUR)
    assert [r["id"] for r in rows] == [c1["id"]]
    assert rows[0]["quantity"] == 100
    assert rows[0]["estimated_total"] == 250.0
    assert rows[0]["estimated_total_eur"] == 250.0
    assert rows[0]["ticker"] == certificate.ticker

    # Strumento con piano ma senza posizione → escluso
    other = models.Instrument(
        ticker="XS0000000010", isin="XS0000000010", name="Cert non posseduto",
        asset_class=models.AssetClass.OTHER, currency="EUR", price_source=PriceSource.MANUAL,
    )
    db.add(other)
    db.commit()
    _mk_coupon(client, other, instrument_id=other.id, payment_date="2026-09-15")
    rows = client.get("/api/coupons/upcoming").json()
    assert [r["id"] for r in rows] == [c1["id"]]

    # Filtro per portafoglio senza posizioni → vuoto
    empty_pf = models.Portfolio(user_id=portfolio.user_id, name="Vuoto")
    db.add(empty_pf)
    db.commit()
    rows = client.get("/api/coupons/upcoming", params={"portfolio_id": empty_pf.id}).json()
    assert rows == []


def test_paid_coupon_cannot_be_edited_or_deleted(client, db, portfolio, certificate):
    coupon = _mk_coupon(client, certificate)
    client.post(f"/api/coupons/{coupon['id']}/confirm", json={
        "portfolio_id": portfolio.id, "gross_amount": 250.0,
    })
    assert client.put(f"/api/coupons/{coupon['id']}", json={"amount_per_unit": 3.0}).status_code == 400
    assert client.delete(f"/api/coupons/{coupon['id']}").status_code == 400


# ── Compensazione minusvalenze ────────────────────────────────────────────────

def test_confirm_with_minus_compensation(client, db, portfolio, certificate):
    """Flag attivo alla conferma: nessuna imposta, netto = lordo."""
    coupon = _mk_coupon(client, certificate)
    res = client.post(f"/api/coupons/{coupon['id']}/confirm", json={
        "portfolio_id": portfolio.id,
        "gross_amount": 250.0,
        "minus_compensation": True,
    })
    assert res.status_code == 200, res.text
    ev = res.json()
    assert ev["minus_compensation"] is True
    assert ev["gross_amount"] == 250.0
    assert ev["tax_amount"] == 0.0
    assert ev["foreign_tax_amount"] == 0.0
    assert ev["amount"] == 250.0


def test_toggle_minus_compensation_retroactively(client, db, portfolio, certificate):
    """ON azzera le imposte (netto = lordo); OFF ricalcola la stima al 26%."""
    coupon = _mk_coupon(client, certificate)
    ev = client.post(f"/api/coupons/{coupon['id']}/confirm", json={
        "portfolio_id": portfolio.id, "gross_amount": 250.0,
    }).json()
    assert ev["tax_amount"] == pytest.approx(250.0 * 0.26)

    res = client.patch(f"/api/dividends/{ev['id']}/minus-compensation",
                       json={"minus_compensation": True})
    assert res.status_code == 200, res.text
    on = res.json()
    assert on["minus_compensation"] is True
    assert on["tax_amount"] == 0.0
    assert on["amount"] == 250.0

    res = client.patch(f"/api/dividends/{ev['id']}/minus-compensation",
                       json={"minus_compensation": False})
    assert res.status_code == 200
    off = res.json()
    assert off["minus_compensation"] is False
    assert off["tax_amount"] == pytest.approx(250.0 * 0.26)
    assert off["amount"] == pytest.approx(250.0 * 0.74)


def test_toggle_minus_rejected_for_non_cert_coupon(client, db, portfolio, certificate):
    """La compensazione si applica solo alle cedole di certificati."""
    ev = client.post("/api/dividends/", json={
        "portfolio_id": portfolio.id, "instrument_id": certificate.id,
        "date": "2026-06-01", "gross_amount": 100.0, "currency": "EUR",
        "type": "DIVIDEND",
    }).json()
    res = client.patch(f"/api/dividends/{ev['id']}/minus-compensation",
                       json={"minus_compensation": True})
    assert res.status_code == 400


def test_monthly_breakdown_splits_dividends_and_coupons(client, db, portfolio, certificate):
    """/api/dividends/monthly separa dividendi e cedole; amount resta il totale."""
    from datetime import timedelta

    d = (date.today() - timedelta(days=30)).isoformat()
    month_key = d[:7]

    # Un dividendo con tasse manuali (netto noto: 74) e una cedola compensata (netto 250)
    client.post("/api/dividends/", json={
        "portfolio_id": portfolio.id, "instrument_id": certificate.id,
        "date": d, "gross_amount": 100.0, "tax_amount": 26.0,
        "currency": "EUR", "type": "DIVIDEND",
    })
    coupon = _mk_coupon(client, certificate, payment_date=d)
    client.post(f"/api/coupons/{coupon['id']}/confirm", json={
        "portfolio_id": portfolio.id, "gross_amount": 250.0, "minus_compensation": True,
    })

    rows = client.get("/api/dividends/monthly").json()
    row = next(r for r in rows if r["month"] == month_key)
    assert row["dividends"] == pytest.approx(74.0)
    assert row["coupons"] == pytest.approx(250.0)
    assert row["amount"] == pytest.approx(324.0)

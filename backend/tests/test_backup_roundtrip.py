"""Backup v2: fonte prezzo, piano cedolare e prezzi non-Yahoo sopravvivono
all'export → delete → import (un restore non può riscaricarli da Yahoo)."""
import io
import json

from app import models
from app.models import CouponStatus, PriceSource


def test_backup_roundtrip_preserves_custom_source_and_coupons(client, db, portfolio):
    # Certificato manuale con prezzi, piano cedolare e una transazione
    r = client.post("/api/market/instruments", json={
        "ticker": "XS0000000042", "isin": "XS0000000042", "name": "Cert Backup",
        "asset_class": "OTHER", "currency": "EUR",
        "price_source": "CUSTOM_JSON",
        "custom_url": "https://api.example.com/q/{ISIN}",
        "custom_jsonpath_price": "$.price",
    })
    iid = r.json()["id"]
    for d, p in (("2026-07-01", 98.0), ("2026-07-10", 99.5)):
        client.post(f"/api/market/instruments/{iid}/prices", json={"date": d, "price": p})
    client.post("/api/coupons/bulk", json=[
        {"instrument_id": iid, "payment_date": "2026-10-15", "amount_per_unit": 2.5,
         "coupon_type": "CONDITIONAL", "memory_effect": True},
        {"instrument_id": iid, "payment_date": "2027-01-15", "amount_per_unit": 2.5,
         "coupon_type": "GUARANTEED", "memory_effect": False},
    ])
    client.post("/api/transactions/", json={
        "portfolio_id": portfolio.id, "instrument_id": iid, "type": "BUY",
        "date": "2026-06-01", "quantity": 100, "price": 100.0,
        "currency": "EUR", "fx_rate": 1,
    })

    # Export
    r = client.get("/api/backup/export")
    assert r.status_code == 200
    backup = json.loads(r.content)
    spec = backup["instruments"][0]
    assert spec["price_source"] == "CUSTOM_JSON"
    assert spec["custom_jsonpath_price"] == "$.price"
    assert len(spec["coupon_schedule"]) == 2
    assert len(spec["price_history"]) == 2

    # Simula un'installazione nuova: via strumento (cascade su prezzi/cedole) e dati
    db.query(models.Transaction).delete()
    db.query(models.DividendEvent).delete()
    inst = db.query(models.Instrument).get(iid)
    db.delete(inst)
    db.commit()
    assert db.query(models.CouponSchedule).count() == 0
    assert db.query(models.PriceHistory).count() == 0

    # Import
    r = client.post("/api/backup/import", files={
        "file": ("backup.json", io.BytesIO(r.content), "application/json"),
    })
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["instruments_created"] == 1
    assert res["coupons_imported"] == 2
    assert res["prices_imported"] == 2
    assert res["transactions_imported"] == 1

    restored = db.query(models.Instrument).filter(models.Instrument.isin == "XS0000000042").one()
    assert restored.price_source == PriceSource.CUSTOM_JSON
    assert restored.custom_url == "https://api.example.com/q/{ISIN}"
    assert {r_.close_price for r_ in restored.price_history} == {98.0, 99.5}
    assert all(c.status == CouponStatus.PLANNED for c in restored.coupon_schedule)

    # Re-import: merge idempotente, nessun duplicato
    r2 = client.post("/api/backup/import", files={
        "file": ("backup.json", io.BytesIO(json.dumps(backup).encode()), "application/json"),
    })
    res2 = r2.json()
    assert res2["coupons_imported"] == 0
    assert res2["prices_imported"] == 0
    assert db.query(models.CouponSchedule).count() == 2
    assert db.query(models.PriceHistory).count() == 2

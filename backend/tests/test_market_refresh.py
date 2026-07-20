"""Refresh prezzi: un fetch custom fallito mantiene l'ultimo prezzo noto,
registra l'errore sullo strumento e non interrompe il refresh degli altri."""
import asyncio
from datetime import date, timedelta

from app import models
from app.models import PriceSource
from app.services import market as market_mod
from app.services.custom_price import CustomPriceError
from app.services.market import MarketService

YESTERDAY = date.today() - timedelta(days=1)


def _mk_instruments(db):
    yahoo = models.Instrument(
        ticker="AAPL", name="Apple", currency="EUR",
        price_source=PriceSource.YAHOO,
    )
    custom = models.Instrument(
        ticker="CERT1", isin="XS0000000001", name="Certificato Test", currency="EUR",
        price_source=PriceSource.CUSTOM_JSON,
        custom_url="https://api.example.com/q/{ISIN}",
        custom_jsonpath_price="$.price",
    )
    db.add_all([yahoo, custom])
    db.commit()
    # Ultimo prezzo noto del certificato (da preservare in caso di errore)
    db.add(models.PriceHistory(instrument_id=custom.id, date=YESTERDAY, close_price=95.0, currency="EUR"))
    db.commit()
    return yahoo, custom


def _quiet_service(svc, monkeypatch):
    """Disattiva FX/enrichment (chiamerebbero Yahoo) — non sono sotto test."""
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(svc, "_refresh_fx_rates", _noop)
    monkeypatch.setattr(svc, "backfill_historical_fx", _noop)
    monkeypatch.setattr(svc, "enrich_all", _noop)


def _fake_chart_for(price: float):
    """Chart Yahoo finto con un solo punto a oggi."""
    import time as _time
    async def _fake(ticker, range_="5d", interval="1d", client=None, events=None):
        return {
            "timestamp": [int(_time.time())],
            "indicators": {"quote": [{"close": [price]}]},
        }
    return _fake


def test_failed_custom_fetch_keeps_last_price_and_records_error(db, monkeypatch):
    yahoo, custom = _mk_instruments(db)
    svc = MarketService(db)
    _quiet_service(svc, monkeypatch)
    monkeypatch.setattr(market_mod, "_fetch_chart", _fake_chart_for(180.0))

    async def _failing(*args, **kwargs):
        raise CustomPriceError("HTTP 503 da https://api.example.com/q/XS0000000001")
    monkeypatch.setattr(market_mod, "fetch_custom_price", _failing)

    asyncio.run(svc.refresh_all_prices())

    # Lo strumento Yahoo è stato comunque aggiornato
    assert svc.latest_price(yahoo.id) == 180.0
    # L'ultimo prezzo noto del custom è preservato
    assert svc.latest_price(custom.id) == 95.0
    assert svc.latest_price_date(custom.id) == YESTERDAY
    # L'errore è registrato sullo strumento (per la segnalazione in UI)
    db.refresh(custom)
    assert "503" in custom.price_fetch_error
    assert custom.price_fetch_error_at is not None


def test_successful_custom_fetch_updates_price_and_clears_error(db, monkeypatch):
    _, custom = _mk_instruments(db)
    custom.price_fetch_error = "errore precedente"
    db.commit()
    svc = MarketService(db)

    async def _ok(*args, **kwargs):
        return 102.5, date.today(), "https://api.example.com/q/XS0000000001"
    monkeypatch.setattr(market_mod, "fetch_custom_price", _ok)

    assert asyncio.run(svc.refresh_custom_price(custom)) is True
    db.commit()

    assert svc.latest_price(custom.id) == 102.5
    db.refresh(custom)
    assert custom.price_fetch_error is None
    assert custom.price_fetch_error_at is None


def test_manual_instruments_are_never_fetched(db, monkeypatch):
    manual = models.Instrument(
        ticker="MAN1", name="Asset manuale", currency="EUR",
        price_source=PriceSource.MANUAL,
    )
    db.add(manual)
    db.commit()
    db.add(models.PriceHistory(instrument_id=manual.id, date=YESTERDAY, close_price=10.0, currency="EUR"))
    db.commit()

    svc = MarketService(db)
    _quiet_service(svc, monkeypatch)

    called = []
    async def _spy_chart(ticker, *args, **kwargs):
        called.append(ticker)
        return None
    monkeypatch.setattr(market_mod, "_fetch_chart", _spy_chart)

    asyncio.run(svc.refresh_all_prices())

    assert called == []                                # nessun fetch Yahoo
    assert svc.latest_price(manual.id) == 10.0         # prezzo manuale intatto

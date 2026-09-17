"""
Identità strumento = TICKER. Lo stesso ISIN può avere più quotazioni (ticker/
valuta diversi) che restano SEPARATE: get_or_create non fonde né sovrascrive mai
il ticker di uno strumento esistente.
"""
import asyncio

from app import models
from app.services.market import MarketService

ISIN = "US5949724083"  # stesso ISIN per entrambe le quotazioni


def test_stesso_isin_ticker_diverso_crea_strumenti_separati(db, monkeypatch):
    # Strumento esistente: MSTR / USD
    mstr = models.Instrument(ticker="MSTR", isin=ISIN, name="Strategy", currency="USD")
    db.add(mstr); db.commit()

    svc = MarketService(db)

    async def fake_lookup(self, isin=None, ticker=None):
        return {"ticker": ticker, "name": "Strategy", "currency": "EUR",
                "isin": isin, "sector": None, "country": None,
                "asset_class": models.AssetClass.EQUITY}
    monkeypatch.setattr(MarketService, "lookup_instrument", fake_lookup)

    # Stesso ISIN, ticker diverso → nuovo strumento separato (EUR), MSTR intatto.
    miga = asyncio.run(svc.get_or_create_instrument(isin=ISIN, ticker="MIGA.SG", name="Strategy"))
    db.refresh(mstr)
    assert miga.id != mstr.id
    assert miga.ticker == "MIGA.SG" and miga.currency == "EUR"
    assert mstr.ticker == "MSTR" and mstr.currency == "USD"   # non sovrascritto
    assert db.query(models.Instrument).filter_by(isin=ISIN).count() == 2


def test_stesso_ticker_riusa_lo_strumento(db, monkeypatch):
    mstr = models.Instrument(ticker="MSTR", isin=ISIN, name="Strategy", currency="USD")
    db.add(mstr); db.commit()
    svc = MarketService(db)

    async def boom(self, **kw):
        raise AssertionError("non deve chiamare Yahoo: lo strumento esiste già per ticker")
    monkeypatch.setattr(MarketService, "lookup_instrument", boom)

    got = asyncio.run(svc.get_or_create_instrument(isin=ISIN, ticker="MSTR", name="Strategy"))
    assert got.id == mstr.id
    assert db.query(models.Instrument).count() == 1

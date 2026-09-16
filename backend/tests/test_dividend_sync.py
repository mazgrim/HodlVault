"""
Sync dividendi da Yahoo: idempotenza. Ri-eseguire il sync NON deve duplicare gli
incassi già creati (regressione: i DB senza il vincolo uq_dividend_event
duplicavano lo stesso dividendo a ogni esecuzione).
"""
import asyncio
from datetime import date

from app import models
from app.services.calculations import DividendCalculator


def test_sync_dividendi_idempotente(db, user, monkeypatch):
    p = models.Portfolio(user_id=user.id, name="PF", broker="Test")
    db.add(p); db.flush()
    inst = models.Instrument(ticker="ACME", isin="TS0000000200", name="ACME",
                             currency="USD", price_source=models.PriceSource.YAHOO)
    db.add(inst); db.flush()
    db.add(models.Transaction(
        portfolio_id=p.id, instrument_id=inst.id, type=models.TransactionType.BUY,
        date=date(2025, 1, 1), quantity=10, price=100.0, fees=0.0, currency="USD", fx_rate=1.0,
    ))
    db.commit()

    # Mock della rete: due ex-date con quote detenute.
    async def fake_hist(self, ticker):
        return [(date(2025, 3, 10), 0.5), (date(2025, 6, 10), 0.5)]
    async def fake_fx(self, currency, d):
        return 1.0
    from app.services.market import MarketService
    monkeypatch.setattr(MarketService, "fetch_dividend_history", fake_hist)
    monkeypatch.setattr(MarketService, "get_fx_rate_for_date", fake_fx)

    calc = DividendCalculator(db, user.id)

    created1 = asyncio.run(calc.sync_from_market(p.id))
    assert created1 == 2
    assert db.query(models.DividendEvent).filter_by(portfolio_id=p.id).count() == 2

    # Seconda esecuzione: nessun nuovo evento, nessun duplicato.
    created2 = asyncio.run(calc.sync_from_market(p.id))
    assert created2 == 0
    assert db.query(models.DividendEvent).filter_by(portfolio_id=p.id).count() == 2

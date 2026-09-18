"""
Mediolanum import — export "Elenco movimenti" (CSV/Excel), senza ISIN.
Dati di esempio FITTIZI.

Copre: skip del preambolo dossier, riconoscimento acquisto/vendita/dividendo,
prezzo in EUR = |Controvalore| / Q.tà, i movimenti "Versamento/Prelevamento
titoli" (cambio denominativo) emessi con warning ed esclusi dall'import, il
suggerimento del ticker per nome in anteprima e la precedenza del nome editato
per gli strumenti nuovi senza ISIN.
"""
from datetime import date

from app import models
from app.services.parsers.mediolanum import MediolanumParser


# Preambolo dossier (7 righe) + header a tripla "Divisa" + movimenti. Valori fittizi.
MEDIOLANUM_CSV = """Dossier;Intestatari;Controvalore;Valore di carico;Guadagni/Perdite €;Guadagni/Perdite %;Saldo trading
000/00000000/00;Tutti gli intestatari;1.000,00 EUR;900,00 EUR;100,00 EUR;11,11 %;500,00 EUR
"
"
"
"
Filtri applicati: 2024-01-01 - 2024-12-31
Titolo;Data ordine;Movimento;Q.tà;Prezzo;Divisa;Controvalore;Divisa;Data valuta;Importo;Divisa
Acme Corp Usd;13/09/2024 00:00:00;Dividendi titoli;20;0.5000;USD;10.0000;EUR;11/09/2024;0.00;EUR
Beta Inc;01/06/2024 15:31:01;Acquisto estero;10;70.0000;USD;-700.0000;EUR;04/06/2024;7.00;EUR
Gamma Spa;09/05/2024 09:04:18;Vendita per contante;100;12.0000;EUR;1200.0000;EUR;14/05/2024;7.00;EUR
Delta Spa;23/04/2024 00:00:00;Versamento titoli;50;10.0000;EUR;-500.0000;EUR;26/04/2024;0.00;EUR
Delta Spa Az Fraz;23/04/2024 00:00:00;Prelevamento titoli;50;10.0000;EUR;500.0000;EUR;26/04/2024;0.00;EUR
Gamma Spa;18/01/2024 09:00:16;Acquisto per contante;100;10.0000;EUR;-1000.0000;EUR;23/01/2024;7.00;EUR
"""


def _by(rows, name, mov_date):
    return next(r for r in rows if r.name == name and r.date == mov_date)


def test_parsing_completo():
    rows = MediolanumParser().parse(MEDIOLANUM_CSV.encode("utf-8"))

    # 6 movimenti riconosciuti (preambolo e "Filtri applicati" saltati).
    assert len(rows) == 6
    assert all(r.isin is None and r.ticker is None for r in rows)
    assert all(r.currency == "EUR" for r in rows)

    # Dividendo: Controvalore EUR è il netto, quantità mantenuta, niente commissioni.
    div = _by(rows, "Acme Corp Usd", date(2024, 9, 13))
    assert div.is_dividend is True
    assert div.price == 10.00
    assert div.fees == 0.0

    # Acquisto estero → BUY, prezzo in EUR = |Controvalore| / Q.tà, commissioni da Importo.
    buy = _by(rows, "Beta Inc", date(2024, 6, 1))
    assert buy.is_dividend is False
    assert buy.type == models.TransactionType.BUY
    assert buy.quantity == 10
    assert buy.price == round(700.0 / 10, 6)
    assert buy.fees == 7.00
    assert buy.excluded is False

    # Vendita per contante → SELL.
    sell = _by(rows, "Gamma Spa", date(2024, 5, 9))
    assert sell.type == models.TransactionType.SELL
    assert sell.price == round(1200.0 / 100, 6)


def test_versamento_prelevamento_esclusi_con_warning():
    rows = MediolanumParser().parse(MEDIOLANUM_CSV.encode("utf-8"))

    versamento = _by(rows, "Delta Spa", date(2024, 4, 23))
    assert versamento.excluded is True
    assert versamento.warning
    assert versamento.type == models.TransactionType.BUY

    prelevamento = _by(rows, "Delta Spa Az Fraz", date(2024, 4, 23))
    assert prelevamento.excluded is True
    assert prelevamento.type == models.TransactionType.SELL

    # Le uniche righe escluse sono i trasferimenti.
    assert sum(1 for r in rows if r.excluded) == 2


def test_file_senza_header_valido_restituisce_vuoto():
    assert MediolanumParser().parse(b"foo;bar;baz\n1;2;3\n") == []


# ── Anteprima: match per nome (nessun ISIN nel file Mediolanum) ───────────────

PREVIEW_HEADER = (
    "Titolo;Data ordine;Movimento;Q.tà;Prezzo;Divisa;"
    "Controvalore;Divisa;Data valuta;Importo;Divisa\n"
)


def _held(db, portfolio, name, ticker, isin):
    inst = models.Instrument(ticker=ticker, isin=isin, name=name, currency="EUR")
    db.add(inst)
    db.flush()
    db.add(models.Transaction(
        portfolio_id=portfolio.id, instrument_id=inst.id,
        type=models.TransactionType.BUY, date=date(2023, 1, 1),
        quantity=100, price=3.0, fees=0.0, currency="EUR", fx_rate=1.0,
    ))
    db.commit()
    return inst


def test_preview_suggerisce_ticker_per_nome_su_compravendite(client, db, portfolio):
    # Gamma Spa già in portafoglio → l'anteprima suggerisce il suo ticker anche per
    # la compravendita Mediolanum (senza ISIN). Un titolo non presente resta vuoto.
    _held(db, portfolio, name="Gamma Spa", ticker="GAMMA.MI", isin="TS0000000009")

    csv = PREVIEW_HEADER + (
        "Gamma Spa;18/01/2024 09:00:16;Acquisto per contante;100;10.0000;EUR;-1000.0000;EUR;23/01/2024;7.00;EUR\n"
        "Beta Inc;01/06/2024 15:31:01;Acquisto estero;10;70.0000;USD;-700.0000;EUR;04/06/2024;7.00;EUR\n"
    )
    resp = client.post(
        "/api/import/preview",
        data={"broker": "mediolanum", "portfolio_id": str(portfolio.id)},
        files={"file": ("movimenti.csv", csv, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    rows = {r["name"]: r for r in resp.json()["rows"]}
    assert rows["Gamma Spa"]["ticker"] == "GAMMA.MI"   # suggerito per nome
    assert rows["Beta Inc"]["ticker"] is None          # non in portafoglio


def test_confirm_nome_editato_vince_solo_senza_isin(client, db, portfolio, monkeypatch):
    # Senza ISIN il nome (editabile in anteprima) è autorevole per lo strumento
    # nuovo; con ISIN vince il nome di Yahoo (comportamento invariato per gli altri
    # broker).
    import app.routers.import_data as imp
    from app.services.market import MarketService

    async def _noop(ids):
        return None
    monkeypatch.setattr(imp, "_fetch_history_for_instruments", _noop)

    async def fake_lookup(self, isin=None, ticker=None):
        return {"ticker": ticker, "name": f"{ticker} Yahoo", "currency": "EUR",
                "isin": isin, "sector": None, "country": None,
                "asset_class": models.AssetClass.EQUITY}
    monkeypatch.setattr(MarketService, "lookup_instrument", fake_lookup)

    def _trade(ticker, isin, name):
        return {"date": "2024-04-23", "type": "BUY", "ticker": ticker, "isin": isin,
                "name": name, "quantity": 50, "price": 10.0, "fees": 0.0,
                "currency": "EUR", "is_dividend": False, "duplicate": False,
                "excluded": False}

    resp = client.post("/api/import/confirm", json={
        "portfolio_id": portfolio.id,
        "rows": [
            _trade("DTA.MI", None, "Delta"),                 # niente ISIN → nome editato
            _trade("OMG.MI", "TS0000000005", "Omega Broker"),  # con ISIN → nome Yahoo
        ],
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["imported"] == 2

    assert db.query(models.Instrument).filter_by(ticker="DTA.MI").one().name == "Delta"
    assert db.query(models.Instrument).filter_by(ticker="OMG.MI").one().name == "OMG.MI Yahoo"

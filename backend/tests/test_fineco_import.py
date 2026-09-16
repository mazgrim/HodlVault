"""
Fineco import — copre i due layout di export (dati di esempio FITTIZI):

- "Movimenti Dossier Titoli" (con ISIN) → compravendite/dividendi (regressione)
- "Movimenti conto" (senza ISIN) → SOLO dividendi, con accoppiamento della
  ritenuta estera e annullamento degli storni. Il match dello strumento avviene
  per nome tra i titoli già presenti nel portafoglio; se assente, la riga è saltata.
"""
from datetime import date

from app import models
from app.services.parsers.fineco import FinecoParser


# ── Parser: "Movimenti conto" (dividendi) ─────────────────────────────────────

MOVEMENTS_CSV = """Data_Operazione;Data_Valuta;Entrate;Uscite;Descrizione;Descrizione_Completa;Stato
2026-07-01;2026-06-26;5,00;;Dividendo estero;Div.su 10,000 ACME;Contabilizzato
2026-07-01;2026-06-26;;-1,00;Ritenuta dividendo estero;Rit.div.su 10,000 ACME;Contabilizzato
2026-07-01;2026-06-26;;-5,00;Dividendo estero;Storno Div.su 10,000 ACME;Contabilizzato
2026-07-01;2026-06-26;1,00;;Ritenuta dividendo estero;Storno Rit.div.su 10,000 ACME;Contabilizzato
2026-07-01;2026-06-26;5,00;;Dividendo estero;Div.su 10,000 ACME;Contabilizzato
2026-07-01;2026-06-26;;-1,00;Ritenuta dividendo estero;Rit.div.su 10,000 ACME;Contabilizzato
2026-01-09;2025-12-31;;-4,2;Imposta bollo dossier titoli;Addebito imposta di bollo Dossier: 9999999;Contabilizzato
2026-01-02;2025-12-29;0,80;;Dividendo estero;Div.su 10,000 ACME;Contabilizzato
2026-01-02;2025-12-29;;-0,20;Ritenuta dividendo estero;Rit.div.su 10,000 ACME;Contabilizzato
2025-02-05;2025-02-07;500,00;;Compravendita Titoli;Compravendita Titoli GLOBEX ETF Qta/Val.nom. 100;Contabilizzato
"""


def test_movimenti_conto_solo_dividendi_con_ritenuta_e_storni():
    rows = FinecoParser().parse(MOVEMENTS_CSV.encode("utf-8"))

    # Solo dividendi: bolli e compravendite ignorati in questo layout.
    assert all(r.is_dividend for r in rows)
    # 2 dividendi netti: lo storno del 2026-07-01 annulla una delle tre coppie.
    assert len(rows) == 2

    by_date = {r.date: r for r in rows}

    luglio = by_date[date(2026, 7, 1)]
    assert luglio.name == "ACME"
    assert luglio.isin is None and luglio.ticker is None
    assert luglio.foreign_tax == 1.00
    assert luglio.price == 6.00           # lordo = netto 5,00 + ritenuta 1,00
    assert luglio.currency == "EUR"

    gennaio = by_date[date(2026, 1, 2)]
    assert gennaio.foreign_tax == 0.20
    assert gennaio.price == 1.00          # 0,80 + 0,20


def test_movimenti_conto_senza_ritenuta_associata():
    csv = (
        "Data_Operazione;Data_Valuta;Entrate;Uscite;Descrizione;Descrizione_Completa;Stato\n"
        "2025-07-07;2025-07-02;0,80;;Dividendo estero;Div.su 10,000 ACME;Contabilizzato\n"
    )
    rows = FinecoParser().parse(csv.encode("utf-8"))
    assert len(rows) == 1
    assert rows[0].foreign_tax == 0.0
    assert rows[0].price == 0.80


# ── Parser: "Movimenti Dossier Titoli" (regressione) ──────────────────────────

DOSSIER_CSV = """Operazione;Data valuta;Descrizione;Titolo;ISIN;Segno;Quantita;Divisa;Prezzo;Cambio;Controvalore
04/03/2026;06/03/2026;Compravendita;GLOBEX ETF;TS0000000001;A;10;EUR;100,00;1;1000,00
"""


def test_dossier_titoli_ancora_riconosciuto():
    rows = FinecoParser().parse(DOSSIER_CSV.encode("utf-8"))
    assert len(rows) == 1
    tx = rows[0]
    assert tx.is_dividend is False
    assert tx.type == models.TransactionType.BUY
    assert tx.isin == "TS0000000001"
    assert tx.quantity == 10
    assert tx.price == 100.0             # controvalore / quantità


# ── Flusso import: match per nome nel portafoglio ─────────────────────────────

def _held_instrument(db, portfolio, name, ticker="ACME", isin="TS0000000002"):
    inst = models.Instrument(ticker=ticker, isin=isin, name=name, currency="USD")
    db.add(inst)
    db.flush()
    db.add(models.Transaction(
        portfolio_id=portfolio.id, instrument_id=inst.id,
        type=models.TransactionType.BUY, date=date(2025, 1, 1),
        quantity=10, price=100.0, fees=0.0, currency="EUR", fx_rate=1.0,
    ))
    db.commit()
    return inst


def _dividend_row(name="ACME", gross=1.00, foreign=0.20, d="2026-01-02"):
    return {
        "date": d, "type": "BUY", "ticker": None, "isin": None, "name": name,
        "quantity": 10, "price": gross, "fees": 0.0, "foreign_tax": foreign,
        "currency": "EUR", "is_dividend": True, "duplicate": False,
    }


def test_confirm_match_per_nome_crea_dividendo(client, db, portfolio, monkeypatch):
    import app.routers.import_data as imp
    async def _noop(ids):
        return None
    monkeypatch.setattr(imp, "_fetch_history_for_instruments", _noop)

    inst = _held_instrument(db, portfolio, name="ACME CORPORATION")

    resp = client.post("/api/import/confirm", json={
        "portfolio_id": portfolio.id,
        "rows": [_dividend_row()],
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["imported"] == 1

    ev = db.query(models.DividendEvent).filter_by(instrument_id=inst.id).one()
    assert ev.gross_amount == 1.00
    assert ev.foreign_tax_amount == 0.20
    assert ev.tax_amount == 0.0
    assert ev.amount == 0.80                       # netto = lordo − ritenuta
    assert ev.type == models.DividendType.DIVIDEND
    assert ev.source == models.DividendSource.IMPORT


def test_preview_suggerisce_ticker_per_nome(client, db, portfolio):
    # Strumento già in portafoglio: l'anteprima deve suggerire il suo ticker per
    # i dividendi "Movimenti conto" (senza ISIN), agganciandoli per nome.
    _held_instrument(db, portfolio, name="ACME CORPORATION")
    csv = (
        "Data_Operazione;Data_Valuta;Entrate;Uscite;Descrizione;Descrizione_Completa;Stato\n"
        "2026-01-02;2025-12-29;0,80;;Dividendo estero;Div.su 10,000 ACME;Contabilizzato\n"
    )
    resp = client.post(
        "/api/import/preview",
        data={"broker": "fineco", "portfolio_id": str(portfolio.id)},
        files={"file": ("movimenti.csv", csv, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["is_dividend"] is True
    assert rows[0]["ticker"] == "ACME"      # suggerito per nome, non vuoto


def test_confirm_nome_non_trovato_salta_riga(client, db, portfolio, monkeypatch):
    import app.routers.import_data as imp
    async def _noop(ids):
        return None
    monkeypatch.setattr(imp, "_fetch_history_for_instruments", _noop)

    # Strumento presente ma diverso: "ACME" non deve agganciarsi a "GLOBEX".
    _held_instrument(db, portfolio, name="GLOBEX", ticker="GLBX", isin="TS0000000003")

    resp = client.post("/api/import/confirm", json={
        "portfolio_id": portfolio.id,
        "rows": [_dividend_row()],
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["imported"] == 0
    assert body["no_ticker"] == 1
    assert db.query(models.DividendEvent).count() == 0

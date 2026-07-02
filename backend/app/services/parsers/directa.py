"""
Directa SIM — parser del file "Movimenti" (storico operazioni), in CSV o XLSX.

Il file ha alcune righe di intestazione, poi una tabella con colonne:
    Data operazione | Data valuta | Tipo operazione | Ticker | Isin | Protocollo |
    Descrizione | Quantità | Importo euro | Importo Divisa | Divisa | Riferimento ordine

Si importano solo le righe Acquisto/Vendita; le altre (bolli, conferimenti, …) sono
ignorate. Directa non riporta un prezzo unitario: prezzo = |Importo euro| / Quantità,
quindi il prezzo è sempre in EUR (currency="EUR", fx_rate=1) anche per titoli esteri.
Nessuna commissione separata (es. il PAC su ETF è gratuito) → fees = 0.
"""
import csv
import io
from datetime import datetime, date
from typing import Any, List, Optional

from ...schemas import ParsedTransaction
from ...models import TransactionType

HEADER_KEY = "Data operazione"


def _to_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _to_float(v: Any) -> float:
    """Numero da cella xlsx (già float) o da testo con formato italiano (1.234,56)."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("\xa0", "").replace(" ", "").strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _to_date(v: Any) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


class DirectaParser:
    def parse(self, content: bytes) -> List[ParsedTransaction]:
        rows = self._read_rows(content)

        header_idx = next(
            (i for i, r in enumerate(rows) if r and _to_str(r[0]) == HEADER_KEY),
            None,
        )
        if header_idx is None:
            raise ValueError("Formato Directa non riconosciuto (manca l'intestazione 'Data operazione')")

        col = {_to_str(name): i for i, name in enumerate(rows[header_idx])}

        def cell(row: list, name: str) -> Any:
            i = col.get(name)
            return row[i] if i is not None and i < len(row) else None

        result: List[ParsedTransaction] = []
        for row in rows[header_idx + 1:]:
            if not row or not any(_to_str(c) for c in row):
                continue

            tipo = _to_str(cell(row, "Tipo operazione")).lower()
            if tipo == "acquisto":
                tx_type = TransactionType.BUY
            elif tipo == "vendita":
                tx_type = TransactionType.SELL
            else:
                continue  # bolli, conferimenti, giroconti… non sono transazioni su titoli

            qty = abs(_to_float(cell(row, "Quantità")))
            importo = abs(_to_float(cell(row, "Importo euro")))
            tx_date = _to_date(cell(row, "Data operazione"))
            if qty <= 0 or importo <= 0 or not tx_date:
                continue

            result.append(ParsedTransaction(
                date=tx_date,
                type=tx_type,
                ticker=None,                       # risolto dall'ISIN a valle (VWCE non è un simbolo Yahoo)
                isin=_to_str(cell(row, "Isin")) or None,
                name=_to_str(cell(row, "Descrizione")) or None,
                quantity=qty,
                price=round(importo / qty, 6),     # Directa dà il totale, non il prezzo unitario
                fees=0.0,
                # Il prezzo deriva da "Importo euro", quindi è SEMPRE in EUR: usare la
                # colonna "Divisa" (valuta del titolo) farebbe dividere un prezzo già
                # in EUR per il cambio, sbagliando i valori dei titoli esteri.
                currency="EUR",
            ))
        return result

    # ── Lettura file: xlsx (openpyxl) o csv/tsv (delimitatore auto) ─────────────
    def _read_rows(self, content: bytes) -> List[list]:
        if content[:2] == b"PK":  # xlsx = archivio zip
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
            try:
                return [list(r) for r in wb.active.iter_rows(values_only=True)]
            finally:
                wb.close()

        text = content.decode("utf-8-sig", errors="replace")
        sample = "\n".join(text.splitlines()[:20])
        delimiter = max((";", "\t", ","), key=sample.count)
        return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]

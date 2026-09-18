"""
Mediolanum parser — export "Elenco movimenti" (CSV o Excel).

Il file NON contiene ISIN: il titolo è identificato solo per NOME. Come per il
Fineco "Movimenti conto", il match dello strumento avviene a valle nell'import
router; in anteprima il ticker resta editabile dall'utente (obbligatorio per
importare un titolo nuovo, l'ISIN è facoltativo).

Struttura del file:
  - righe 1-N di intestazione dossier + una riga "Filtri applicati: …" → saltate
  - riga header con: Titolo | Data ordine | Movimento | Q.tà | Prezzo | Divisa
                     | Controvalore | Divisa | Data valuta | Importo | Divisa
  - righe movimento

L'header ha TRE colonne "Divisa" (prezzo, controvalore, importo): non si può
indicizzare per nome (verrebbero collassate), quindi si legge PER POSIZIONE.

Colonne usate (per indice):
  0 Titolo         → name
  2 Movimento      → tipo operazione
  3 Q.tà           → quantità
  6 Controvalore   → importo regolato, SEMPRE in EUR (col. 7 = "EUR")
  9 Importo        → commissioni/spese in EUR

Prezzo unitario in EUR = |Controvalore| / Q.tà (fx=1.0, currency=EUR), come per
il dossier Fineco: evita ogni ambiguità sulla valuta nativa (col. 5, es. USD).

Movimenti riconosciuti (col. Movimento):
  "Acquisto …" (estero / per contante)  → BUY
  "Vendita …"  (per contante)           → SELL
  "Dividendi titoli"                    → dividendo (Controvalore = netto in EUR;
                                           il file non scompone le imposte → net=gross)
  "Versamento titoli" / "Prelevamento titoli" → trasferimento/cambio denominativo:
       emesso con un warning ed ESCLUSO dall'import di default (excluded=True).
Ogni altro movimento è ignorato.
"""
import io
from datetime import date as date_type
from datetime import datetime
from typing import List, Optional

try:
    import xlrd as _xlrd
    _HAS_XLRD = True
except ImportError:
    _HAS_XLRD = False

from ...schemas import ParsedTransaction
from ...models import TransactionType


# Indici di colonna (posizionali) nel corpo del report.
_COL_TITOLO = 0
_COL_MOVIMENTO = 2
_COL_QTA = 3
_COL_CONTROVALORE = 6
_COL_IMPORTO = 9
_MIN_COLS = 10   # servono almeno le colonne fino a "Importo"


def _parse_float(s: str) -> float:
    """Numero in formato con punto decimale (Mediolanum: 1743.0000) oppure
    italiano (1.234,56). Restituisce 0.0 se non parsabile."""
    s = (s or "").replace("\n", "").strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")   # 1.234,56 → 1234.56
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_date(s: str) -> Optional[date_type]:
    """Data ordine: "13/09/2024 00:00:00" (o senza ora), oppure ISO da Excel."""
    s = (s or "").strip()
    if not s:
        return None
    s = s.split(" ")[0]   # scarta l'ora
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _is_header(cells: list) -> bool:
    low = {str(c).strip().lower() for c in cells}
    return "titolo" in low and "movimento" in low and "controvalore" in low


class MediolanumParser:

    # ── Entry point ───────────────────────────────────────────────────────────

    def parse(self, content: bytes) -> List[ParsedTransaction]:
        magic = content[:8]
        if magic[:4] == b"\xd0\xcf\x11\xe0":      # BIFF OLE (.xls)
            rows = self._rows_from_xls(content)
        elif magic[:2] == b"PK":                    # ZIP (.xlsx / .xlsm)
            rows = self._rows_from_xlsx(content)
        else:
            rows = self._rows_from_csv(content)     # text fallback
        return self._parse_rows(rows)

    # ── Readers: ogni reader restituisce list[list[str]] (per posizione) ───────

    def _rows_from_csv(self, content: bytes) -> List[list]:
        import csv
        text = content.decode("utf-8-sig", errors="replace")
        for sep in (";", ",", "\t"):
            reader = csv.reader(io.StringIO(text), delimiter=sep)
            all_rows = [[c.strip() for c in r] for r in reader]
            if any(_is_header(r) for r in all_rows):
                return all_rows
        return []

    def _rows_from_xlsx(self, content: bytes) -> List[list]:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        out: List[list] = []
        for row in ws.iter_rows(values_only=True):
            out.append([self._cell_str(c) for c in row])
        return out

    def _rows_from_xls(self, content: bytes) -> List[list]:
        if not _HAS_XLRD:
            raise RuntimeError(
                "xlrd is required to import Mediolanum .xls files — "
                "add 'xlrd' to requirements.txt and rebuild the backend."
            )
        wb = _xlrd.open_workbook(file_contents=content)
        ws = wb.sheet_by_index(0)
        out: List[list] = []
        for r in range(ws.nrows):
            cells = []
            for c in range(ws.ncols):
                if ws.cell_type(r, c) == _xlrd.XL_CELL_DATE:
                    dt = _xlrd.xldate.xldate_as_datetime(ws.cell_value(r, c), wb.datemode)
                    cells.append(dt.strftime("%Y-%m-%d %H:%M:%S"))
                else:
                    cells.append(self._cell_str(ws.cell_value(r, c)))
            out.append(cells)
        return out

    @staticmethod
    def _cell_str(v) -> str:
        if v is None:
            return ""
        if isinstance(v, float):
            return str(int(v)) if v == int(v) else str(v)
        return str(v).strip()

    # ── Core ───────────────────────────────────────────────────────────────────

    def _parse_rows(self, all_rows: List[list]) -> List[ParsedTransaction]:
        header_idx = next((i for i, r in enumerate(all_rows) if _is_header(r)), None)
        if header_idx is None:
            return []

        result: List[ParsedTransaction] = []
        for cells in all_rows[header_idx + 1:]:
            try:
                tx = self._parse_row(cells)
                if tx:
                    result.append(tx)
            except Exception:
                continue
        return result

    def _parse_row(self, cells: list) -> Optional[ParsedTransaction]:
        if len(cells) < _MIN_COLS or not any(str(c).strip() for c in cells):
            return None

        mov = str(cells[_COL_MOVIMENTO]).strip().lower()
        if not mov:
            return None

        is_dividend = "dividend" in mov
        is_transfer = ("versamento titoli" in mov) or ("prelevamento titoli" in mov)
        is_buy = mov.startswith("acquisto")
        is_sell = mov.startswith("vendita")
        if not (is_dividend or is_transfer or is_buy or is_sell):
            return None

        tx_date = _parse_date(str(cells[1]))
        if not tx_date:
            return None

        name = str(cells[_COL_TITOLO]).strip() or None
        qty = _parse_float(str(cells[_COL_QTA]))
        controvalore = abs(_parse_float(str(cells[_COL_CONTROVALORE])))
        fees = abs(_parse_float(str(cells[_COL_IMPORTO])))

        # ── Dividendo ───────────────────────────────────────────────────────
        if is_dividend:
            if controvalore <= 0:
                return None
            return ParsedTransaction(
                date=tx_date,
                type=TransactionType.BUY,   # ignorato per i dividendi
                ticker=None,
                isin=None,
                name=name,
                quantity=qty,
                price=round(controvalore, 6),   # netto in EUR
                fees=0.0,
                currency="EUR",
                is_dividend=True,
            )

        # ── Trade / trasferimento ───────────────────────────────────────────
        if qty <= 0 or controvalore <= 0:
            return None
        price_eur = round(controvalore / qty, 6)

        if is_transfer:
            # Versamento (carico) ≈ BUY, Prelevamento (scarico) ≈ SELL, ma di norma
            # è un cambio di denominativo/trasferimento: mostrato con warning ed
            # escluso dall'import di default.
            tx_type = TransactionType.BUY if "versamento" in mov else TransactionType.SELL
            return ParsedTransaction(
                date=tx_date,
                type=tx_type,
                ticker=None,
                isin=None,
                name=name,
                quantity=qty,
                price=price_eur,
                fees=round(fees, 4),
                currency="EUR",
                excluded=True,
                warning="Trasferimento/cambio denominativo titoli — di norma non va "
                        "importato. Escluso di default; abilitalo solo se serve.",
            )

        tx_type = TransactionType.BUY if is_buy else TransactionType.SELL
        return ParsedTransaction(
            date=tx_date,
            type=tx_type,
            ticker=None,
            isin=None,
            name=name,
            quantity=qty,
            price=price_eur,
            fees=round(fees, 4),
            currency="EUR",
        )

"""
Fineco "Movimenti Dossier Titoli" parser — supports both XLS export variants.

Two report layouts are handled automatically:

  Variant A (11 columns, no commissions):
    Operazione | Data valuta | Descrizione | Titolo | ISIN | Segno
    Quantita | Divisa | Prezzo | Cambio | Controvalore

  Variant B (15 columns, with commissions):
    …same 11… | Commissioni Fondi Sw/Ingr/Uscita
               | Commissioni Fondi Banca Corrispondente
               | Spese Fondi Sgr
               | Commissioni amministrato

Both compravendita (buy/sell) and dividendo rows are parsed.

Prices are normalised to EUR:
  price_eur = Controvalore / Quantita   (uses the settled EUR amount)
  fx_rate   = 1.0
  currency  = EUR

This avoids any ambiguity about which currency "Divisa" refers to in each variant
while keeping the calculation (avg cost, P&L) accurate.
"""
import io
from datetime import datetime
from typing import List

try:
    import xlrd as _xlrd
    _HAS_XLRD = True
except ImportError:
    _HAS_XLRD = False

from ...schemas import ParsedTransaction
from ...models import TransactionType


# All possible commission / fee column names in the 15-col variant
_FEE_COLS = (
    "Commissioni Fondi Sw/Ingr/Uscita",
    "Commissioni Fondi Banca Corrispondente",
    "Spese Fondi Sgr",
    "Commissioni amministrato",
)


def _parse_float(s: str) -> float:
    """Parse a number that may use Italian (1.234,56) or plain (1234.56) format."""
    s = s.replace("\n", "").strip()
    if "," in s and "." in s:
        # Italian thousands separator + decimal comma: 1.234,56 → 1234.56
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


class FinecoParser:

    # ── Entry point ───────────────────────────────────────────────────────────

    def parse(self, content: bytes) -> List[ParsedTransaction]:
        magic = content[:8]
        if magic[:4] == b'\xd0\xcf\x11\xe0':   # BIFF OLE (.xls)
            return self._parse_xls(content)
        if magic[:2] == b'PK':                   # ZIP (.xlsx / .xlsm)
            return self._parse_xlsx(content)
        return self._parse_csv(content)          # plain text fallback

    # ── XLS (classic binary) ─────────────────────────────────────────────────

    def _parse_xls(self, content: bytes) -> List[ParsedTransaction]:
        if not _HAS_XLRD:
            raise RuntimeError(
                "xlrd is required to import Fineco .xls files — "
                "add 'xlrd' to requirements.txt and rebuild the backend."
            )
        wb = _xlrd.open_workbook(file_contents=content)
        ws = wb.sheet_by_index(0)

        # Locate the header row (contains "Operazione" or "ISIN")
        header_idx = self._find_header_row_xls(ws)
        if header_idx is None:
            return []

        headers = [str(ws.cell_value(header_idx, c)).strip() for c in range(ws.ncols)]
        rows: list[dict] = []
        for r in range(header_idx + 1, ws.nrows):
            d = {}
            for c, h in enumerate(headers):
                raw = ws.cell_value(r, c)
                # xlrd returns floats for numeric cells; keep as string for uniformity
                if isinstance(raw, float):
                    # Integer-valued floats → no decimal
                    d[h] = str(int(raw)) if raw == int(raw) else str(raw)
                else:
                    d[h] = str(raw).strip()
            rows.append(d)

        return self._parse_rows(rows)

    def _find_header_row_xls(self, ws) -> int | None:
        for r in range(min(15, ws.nrows)):
            vals = [str(ws.cell_value(r, c)).strip() for c in range(ws.ncols)]
            if "Operazione" in vals or "ISIN" in vals:
                return r
        return None

    # ── XLSX ─────────────────────────────────────────────────────────────────

    def _parse_xlsx(self, content: bytes) -> List[ParsedTransaction]:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))

        header_idx = None
        for i, row in enumerate(all_rows):
            vals = [str(c).strip() if c is not None else '' for c in row]
            if "Operazione" in vals or "ISIN" in vals:
                header_idx = i
                break
        if header_idx is None:
            return []

        headers = [str(c).strip() if c is not None else '' for c in all_rows[header_idx]]
        rows = [
            {h: (str(v).strip() if v is not None else '') for h, v in zip(headers, row)}
            for row in all_rows[header_idx + 1:]
        ]
        return self._parse_rows(rows)

    # ── CSV (text fallback) ───────────────────────────────────────────────────

    def _parse_csv(self, content: bytes) -> List[ParsedTransaction]:
        import csv
        text = content.decode("utf-8-sig", errors="replace")
        for sep in (';', ',', '\t'):
            try:
                reader = csv.reader(io.StringIO(text), delimiter=sep)
                all_rows = list(reader)
            except Exception:
                continue

            header_idx = None
            for i, row in enumerate(all_rows):
                if "Operazione" in row or "ISIN" in row:
                    header_idx = i
                    break
            if header_idx is None:
                continue

            headers = [c.strip() for c in all_rows[header_idx]]
            dicts = [
                {h: v.strip() for h, v in zip(headers, row)}
                for row in all_rows[header_idx + 1:]
            ]
            return self._parse_rows(dicts)
        return []

    # ── Core row processing ───────────────────────────────────────────────────

    def _parse_rows(self, rows: list) -> List[ParsedTransaction]:
        result = []
        for row in rows:
            if not any(v for v in row.values()):
                continue
            try:
                tx = self._parse_row(row)
                if tx:
                    result.append(tx)
            except Exception:
                continue
        return result

    def _parse_row(self, row: dict) -> ParsedTransaction | None:
        # Normalise Descrizione (may contain newlines)
        desc = row.get("Descrizione", "").replace("\n", " ").strip().lower()

        is_dividend   = "dividendo" in desc
        is_trade      = "compravendita" in desc

        if not is_dividend and not is_trade:
            return None

        # ── Date ──────────────────────────────────────────────────────────────
        date_str = row.get("Operazione", "").strip()
        tx_date = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                tx_date = datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                continue
        if not tx_date:
            return None

        # ── Quantity ──────────────────────────────────────────────────────────
        qty = _parse_float(row.get("Quantita", "0"))
        if qty <= 0:
            return None

        # ── Settled EUR amount ────────────────────────────────────────────────
        controvalore = abs(_parse_float(row.get("Controvalore", "0")))

        # ── Fees (sum all commission columns that are present and non-zero) ───
        fees = 0.0
        for col in _FEE_COLS:
            raw = row.get(col, "").strip()
            if raw:
                fees += abs(_parse_float(raw))

        isin = row.get("ISIN", "").strip() or None
        name = row.get("Titolo", "").strip() or None

        # ── Dividend ──────────────────────────────────────────────────────────
        if is_dividend:
            if controvalore <= 0:
                return None
            return ParsedTransaction(
                date=tx_date,
                type=TransactionType.BUY,   # field is ignored for dividends
                ticker=None,
                isin=isin,
                name=name,
                quantity=qty,
                price=round(controvalore, 6),
                fees=0.0,
                currency="EUR",
                is_dividend=True,
            )

        # ── Buy / Sell ────────────────────────────────────────────────────────
        segno = row.get("Segno", "").strip().upper()
        if segno not in ("A", "V"):
            return None
        tx_type = TransactionType.BUY if segno == "A" else TransactionType.SELL

        if controvalore <= 0:
            return None

        # Price per unit in EUR, derived from settled amount
        price_eur = round(controvalore / qty, 6)

        return ParsedTransaction(
            date=tx_date,
            type=tx_type,
            ticker=None,
            isin=isin,
            name=name,
            quantity=qty,
            price=price_eur,
            fees=round(fees, 4),
            currency="EUR",
        )

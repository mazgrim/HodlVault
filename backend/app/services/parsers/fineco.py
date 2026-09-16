"""
Fineco parser — riconosce automaticamente due export diversi.

1) "Movimenti Dossier Titoli" (ha ISIN) — compravendite E dividendi.
   Due varianti di colonne:

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
     fx_rate   = 1.0 ; currency = EUR
   This avoids any ambiguity about which currency "Divisa" refers to in each
   variant while keeping the calculation (avg cost, P&L) accurate.

2) "Movimenti conto" / lista movimenti (NIENTE ISIN) — SOLO dividendi.
   Colonne: Data_Operazione | Data_Valuta | Entrate | Uscite | Descrizione
            | Descrizione_Completa | Stato
   Si accoppia ogni "Dividendo estero" (netto in Entrate) con la sua "Ritenuta
   dividendo estero" (in Uscite) su stessa data+titolo → lordo = netto+ritenuta,
   foreign_tax = ritenuta. Le righe "Storno …" annullano il movimento originale.
   Titolo identificato solo per NOME (da Descrizione_Completa): il match dello
   strumento avviene a valle nell'import router, ristretto ai titoli già in
   portafoglio. Compravendite, bolli e altre imposte NON vengono importati qui.
"""
import io
import re
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

# "Descrizione_Completa" del report "Movimenti conto" (esempio fittizio):
#   "Div.su 10,000 ACME"            → dividendo (netto in colonna Entrate)
#   "Rit.div.su 10,000 ACME"        → ritenuta estera (in colonna Uscite)
#   "Storno Div.su 10,000 ACME"     → storno che annulla il movimento originale
_MOV_DESC_RE = re.compile(
    r"^(?P<storno>storno\s+)?(?:div\.su|rit\.div\.su)\s+"
    r"(?P<qty>[\d.,]+)\s+(?P<name>.+?)\s*$",
    re.IGNORECASE,
)


def _apply_storni(entries: list) -> list:
    """Cancel each "Storno …" row against one matching original (same date, title
    and amount to the cent). Returns the surviving real movements, storni removed."""
    normals = [e for e in entries if not e["storno"]]
    storni = [e for e in entries if e["storno"]]
    for s in storni:
        key = (s["date"], s["key_name"], round(s["amount"], 2))
        for i, n in enumerate(normals):
            if (n["date"], n["key_name"], round(n["amount"], 2)) == key:
                normals.pop(i)
                break
    return normals


def _detect_layout(vals) -> str | None:
    """Classify a candidate header row.

    - "dossier"   → "Movimenti Dossier Titoli" (compravendite + dividendi, con ISIN)
    - "movements" → "Movimenti conto" / lista movimenti (solo cassa: dividendi,
      ritenute, bolli… senza ISIN né quantità in colonna)
    """
    s = {str(v).strip() for v in vals}
    if "Operazione" in s or "ISIN" in s:
        return "dossier"
    if "Descrizione" in s and ("Entrate" in s or "Uscite" in s):
        return "movements"
    return None


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

        # Locate the header row and classify the report layout
        header_idx, layout = self._find_header_row_xls(ws)
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

        return self._dispatch(layout, rows)

    def _find_header_row_xls(self, ws):
        for r in range(min(15, ws.nrows)):
            vals = [str(ws.cell_value(r, c)).strip() for c in range(ws.ncols)]
            layout = _detect_layout(vals)
            if layout:
                return r, layout
        return None, None

    # ── XLSX ─────────────────────────────────────────────────────────────────

    def _parse_xlsx(self, content: bytes) -> List[ParsedTransaction]:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))

        header_idx = None
        layout = None
        for i, row in enumerate(all_rows):
            vals = [str(c).strip() if c is not None else '' for c in row]
            layout = _detect_layout(vals)
            if layout:
                header_idx = i
                break
        if header_idx is None:
            return []

        headers = [str(c).strip() if c is not None else '' for c in all_rows[header_idx]]
        rows = [
            {h: (str(v).strip() if v is not None else '') for h, v in zip(headers, row)}
            for row in all_rows[header_idx + 1:]
        ]
        return self._dispatch(layout, rows)

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
            layout = None
            for i, row in enumerate(all_rows):
                layout = _detect_layout(row)
                if layout:
                    header_idx = i
                    break
            if header_idx is None:
                continue

            headers = [c.strip() for c in all_rows[header_idx]]
            dicts = [
                {h: v.strip() for h, v in zip(headers, row)}
                for row in all_rows[header_idx + 1:]
            ]
            return self._dispatch(layout, dicts)
        return []

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def _dispatch(self, layout: str | None, rows: list) -> List[ParsedTransaction]:
        if layout == "movements":
            return self._parse_movements_rows(rows)
        return self._parse_rows(rows)

    # ── "Movimenti conto" (cash statement) ────────────────────────────────────
    #
    # Only dividends are imported here (per product decision): a "Dividendo estero"
    # credit paired with its "Ritenuta dividendo estero" debit on the same date and
    # security. Compravendite, bolli e altre imposte NON hanno ISIN/quantità/prezzo
    # utili e non vengono importate da questo layout.

    def _parse_movements_rows(self, rows: list) -> List[ParsedTransaction]:
        dividends: list[dict] = []   # {date, name, key_name, qty, amount, storno}
        withholdings: list[dict] = []

        for row in rows:
            if not any(v for v in row.values()):
                continue
            entry = self._parse_movement_entry(row)
            if entry is None:
                continue
            (withholdings if entry["kind"] == "ritenuta" else dividends).append(entry)

        # Storni: ogni riga "Storno …" annulla un movimento originale identico
        # (stessa data, titolo e importo). Ciò che resta sono gli eventi reali.
        real_div = _apply_storni(dividends)
        real_wht = _apply_storni(withholdings)

        # Accoppia ogni dividendo con la ritenuta su stessa data + titolo.
        wht_by_key: dict = {}
        for w in real_wht:
            wht_by_key.setdefault((w["date"], w["key_name"]), []).append(w["amount"])

        result: List[ParsedTransaction] = []
        for d in real_div:
            k = (d["date"], d["key_name"])
            foreign_tax = 0.0
            bucket = wht_by_key.get(k)
            if bucket:
                foreign_tax = round(bucket.pop(0), 4)   # una ritenuta per dividendo
            net = round(d["amount"], 4)
            gross = round(net + foreign_tax, 4)
            if gross <= 0:
                continue
            result.append(ParsedTransaction(
                date=d["date"],
                type=TransactionType.BUY,   # ignorato per i dividendi
                ticker=None,
                isin=None,
                name=d["name"],
                quantity=d["qty"],
                price=gross,                # LORDO
                fees=0.0,                   # imposta italiana non presente nel file
                foreign_tax=foreign_tax,    # ritenuta estera reale
                currency="EUR",
                is_dividend=True,
            ))
        return result

    def _parse_movement_entry(self, row: dict) -> dict | None:
        desc = (row.get("Descrizione", "") or "").replace("\n", " ").strip().lower()
        is_ritenuta = "ritenuta" in desc and "dividend" in desc
        is_dividend = ("dividendo" in desc) and not is_ritenuta
        if not is_ritenuta and not is_dividend:
            return None

        m = _MOV_DESC_RE.match((row.get("Descrizione_Completa", "") or "").strip())
        if not m:
            return None
        name = m.group("name").strip()
        if not name:
            return None
        qty = _parse_float(m.group("qty"))

        date_str = (row.get("Data_Operazione", "") or "").strip()
        # Excel/openpyxl può restituire "2026-07-01 00:00:00"
        date_str = date_str.split(" ")[0]
        tx_date = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                tx_date = datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                continue
        if not tx_date:
            return None

        # Importo: il netto sta in Entrate (dividendo) o in Uscite (ritenuta).
        raw_amount = row.get("Entrate", "") or row.get("Uscite", "") or "0"
        amount = abs(_parse_float(raw_amount))
        if amount <= 0:
            return None

        return {
            "kind": "ritenuta" if is_ritenuta else "dividendo",
            "date": tx_date,
            "name": name,
            "key_name": name.upper(),
            "qty": qty,
            "amount": amount,
            "storno": bool(m.group("storno")),
        }

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

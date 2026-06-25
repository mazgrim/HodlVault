"""
Directa SIM CSV parser.
Expected columns: Data, Ora, Descrizione, Quantità, Prezzo, Importo, Commissioni, Valuta
The Descrizione field contains the instrument name and ISIN in parentheses: "Titolo (ISIN)"
"""
import csv
import io
import re
from datetime import datetime
from typing import List, Optional

from ...schemas import ParsedTransaction
from ...models import TransactionType

ISIN_RE = re.compile(r"\(([A-Z]{2}[A-Z0-9]{10})\)")


def _parse_float(s: str) -> float:
    """Parse a number that may use Italian (1.234,56) or plain (1234.56) format."""
    s = (s or "").replace("\n", "").strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        # Italian thousands separator + decimal comma: 1.234,56 → 1234.56
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


class DirectaParser:
    def parse(self, content: bytes) -> List[ParsedTransaction]:
        text = content.decode("utf-8-sig", errors="replace")
        # Try semicolon first
        for sep in (";", ",", "\t"):
            reader = csv.DictReader(io.StringIO(text), delimiter=sep)
            rows = [{k.strip(): v.strip() for k, v in r.items() if k} for r in reader]
            if rows and "Descrizione" in rows[0]:
                return self._parse_rows(rows)
        raise ValueError("Formato CSV Directa non riconosciuto")

    def _parse_rows(self, rows: list) -> List[ParsedTransaction]:
        result = []
        for row in rows:
            try:
                tx = self._parse_row(row)
                if tx:
                    result.append(tx)
            except Exception:
                continue
        return result

    def _parse_row(self, row: dict) -> Optional[ParsedTransaction]:
        desc = row.get("Descrizione", "")
        quantity = _parse_float(row.get("Quantità", "0"))
        if quantity == 0:
            return None
        # Positive = buy, negative = sell
        tx_type = TransactionType.BUY if quantity > 0 else TransactionType.SELL
        quantity = abs(quantity)

        price = _parse_float(row.get("Prezzo", "0"))
        fees = abs(_parse_float(row.get("Commissioni", "0")))

        date_str = row.get("Data", "").strip()
        tx_date = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                tx_date = datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                continue
        if not tx_date:
            return None

        # Extract ISIN from description
        isin_match = ISIN_RE.search(desc)
        isin = isin_match.group(1) if isin_match else None
        name = ISIN_RE.sub("", desc).strip(" -()") or None

        return ParsedTransaction(
            date=tx_date,
            type=tx_type,
            ticker=None,
            isin=isin,
            name=name,
            quantity=quantity,
            price=price,
            fees=fees,
            currency=row.get("Valuta", "EUR").strip() or "EUR",
        )

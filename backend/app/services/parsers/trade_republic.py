"""
Trade Republic CSV parser – handles both formats:

New format (mod 2 / v2):
  Tab-separated. Columns: datetime, date, account_type, category, type, asset_class,
  name, symbol, shares, price, amount, fee, tax, currency, original_amount,
  original_currency, fx_rate, description, transaction_id, ...
  Numbers have a trailing .00 artifact: '985.24.00' → 985.24
  Quantity is embedded in the description: 'quantity: 0.605015'

Old format:
  Comma/semicolon-separated. Columns: Date, Type, Instrument, ISIN, Shares, Price, Amount, Fee

Imported row types:
  TRADING / BUY            → BUY transaction
  TRADING / SELL           → SELL transaction
  CASH / DIVIDEND          → dividend event (is_dividend=True)
  CASH / BENEFITS_SAVEBACK → BUY transaction (acquista quote ETF, is_dividend=False)
"""
import csv
import io
import re
from datetime import date as date_type
from datetime import datetime
from typing import List, Optional

from ...schemas import ParsedTransaction
from ...models import TransactionType


# BENEFITS_SAVEBACK acquista quote ETF → trattato come BUY, non come dividendo
_CASH_DIVIDENDS = {"DIVIDEND"}
_CASH_BUY       = {"BENEFITS_SAVEBACK"}


def _parse_tr_number(s: str) -> float:
    """
    Parse malformed Trade Republic number.
    Pattern: '985.24.00' (three dot-separated groups) → 985.24
             '-20.00.00'                               → -20.00
             '24.50.00'                                → 24.50
    """
    if not s or not s.strip():
        return 0.0
    s = s.strip()
    parts = s.split(".")
    if len(parts) >= 3:
        # Re-join only the first two segments as integer.decimal
        return float(f"{parts[0]}.{parts[1]}")
    return float(s)


def _parse_date_new(row: dict) -> Optional[date_type]:
    """Parse date from 'datetime' (ISO) or 'date' (DD/MM/YY) column."""
    dt = row.get("datetime", "").strip()
    if dt:
        try:
            return datetime.fromisoformat(dt.replace("Z", "+00:00")).date()
        except (ValueError, AttributeError):
            pass
    d = row.get("date", "").strip()
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(d, fmt).date()
        except ValueError:
            continue
    return None


def _extract_quantity(description: str) -> Optional[float]:
    """Extract transaction quantity from description, e.g. 'quantity: 0.605015'."""
    m = re.search(r"quantity[:\s]+([0-9]+(?:\.[0-9]+)?)", description, re.IGNORECASE)
    return float(m.group(1)) if m else None


class TradeRepublicParser:

    def parse(self, content: bytes) -> List[ParsedTransaction]:
        text = content.decode("utf-8-sig", errors="replace")
        for sep in ("\t", ",", ";"):
            reader = csv.DictReader(io.StringIO(text), delimiter=sep)
            rows = [
                {k.strip(): (v.strip() if v else "") for k, v in r.items() if k}
                for r in reader
            ]
            if not rows:
                continue
            first = rows[0]
            # New format detection
            if "datetime" in first and "category" in first:
                return self._parse_new(rows)
            # Old format detection
            if "Date" in first or "Type" in first:
                return self._parse_old(rows)
        raise ValueError("Formato CSV Trade Republic non riconosciuto")

    # ── New format ─────────────────────────────────────────────────────────────

    def _parse_new(self, rows: list) -> List[ParsedTransaction]:
        result = []
        for row in rows:
            try:
                tx = self._row_new(row)
                if tx:
                    result.append(tx)
            except Exception:
                continue
        return result

    def _row_new(self, row: dict) -> Optional[ParsedTransaction]:
        category    = row.get("category", "").upper()
        tx_type_str = row.get("type",     "").upper()

        is_trade = (
            (category == "TRADING" and tx_type_str in ("BUY", "SELL")) or
            (category == "CASH"    and tx_type_str in _CASH_BUY)
        )
        is_div = category == "CASH" and tx_type_str in _CASH_DIVIDENDS

        if not (is_trade or is_div):
            return None

        tx_date = _parse_date_new(row)
        if not tx_date:
            return None

        isin     = row.get("symbol",   "").strip() or None
        name     = row.get("name",     "").strip() or None
        currency = row.get("currency", "EUR").strip() or "EUR"
        amount   = _parse_tr_number(row.get("amount", ""))
        fee      = _parse_tr_number(row.get("fee",    ""))

        if is_trade:
            # BENEFITS_SAVEBACK is always a BUY; TRADING rows use their own type
            if tx_type_str == "BENEFITS_SAVEBACK":
                trade_type = TransactionType.BUY
            else:
                trade_type = TransactionType.BUY if tx_type_str == "BUY" else TransactionType.SELL

            # Quantity: first try description, then shares column
            qty = _extract_quantity(row.get("description", ""))
            if not qty or qty <= 0:
                shares_str = row.get("shares", "").strip()
                if shares_str:
                    try:
                        qty = _parse_tr_number(shares_str)
                    except Exception:
                        qty = None

            if not qty or qty <= 0:
                return None

            # 'amount' è il movimento di cassa contabilizzato: per un BUY include la
            # fee (addebito totale), per una SELL è già al netto della fee. Il prezzo
            # "pulito" quindi si ottiene togliendo la fee sul BUY e riaggiungendola
            # sulla SELL — il calcolatore poi fa costo = prezzo·qta + fee e
            # proventi = prezzo·qta − fee, ricostruendo esattamente la cassa reale.
            if trade_type == TransactionType.BUY:
                price = (abs(amount) - abs(fee)) / qty
            else:
                price = (abs(amount) + abs(fee)) / qty
            return ParsedTransaction(
                date=tx_date,
                type=trade_type,
                ticker=None,
                isin=isin,
                name=name,
                quantity=round(qty, 8),
                price=round(max(price, 0), 4),
                fees=round(abs(fee), 2),
                currency=currency,
                is_dividend=False,
            )

        # ── True dividend (CASH / DIVIDEND) ──────────────────────────────────
        # Prefer original_amount + original_currency when available
        orig_amount   = _parse_tr_number(row.get("original_amount",   ""))
        orig_currency = row.get("original_currency", "").strip() or None
        tax = abs(_parse_tr_number(row.get("tax", "")))

        if orig_amount > 0 and orig_currency:
            div_amount   = orig_amount
            div_currency = orig_currency
        else:
            div_amount   = abs(amount)
            div_currency = currency

        if div_amount <= 0:
            return None

        return ParsedTransaction(
            date=tx_date,
            type=TransactionType.BUY,   # placeholder; is_dividend=True overrides
            ticker=None,
            isin=isin,
            name=name,
            quantity=0.0,
            price=round(div_amount, 4),
            fees=round(tax, 2),         # ritenuta fiscale
            currency=div_currency,
            is_dividend=True,
        )

    # ── Old format ─────────────────────────────────────────────────────────────

    def _parse_old(self, rows: list) -> List[ParsedTransaction]:
        result = []
        for row in rows:
            try:
                tx_type_str = row.get("Type", "").lower()
                if tx_type_str not in ("buy", "sell"):
                    continue
                tx_type = TransactionType.BUY if tx_type_str == "buy" else TransactionType.SELL

                d = row.get("Date", "").strip()
                tx_date = None
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                    try:
                        tx_date = datetime.strptime(d[:10], fmt).date()
                        break
                    except ValueError:
                        continue
                if not tx_date:
                    continue

                result.append(ParsedTransaction(
                    date=tx_date,
                    type=tx_type,
                    ticker=None,
                    isin=row.get("ISIN") or None,
                    name=row.get("Instrument") or None,
                    quantity=float(row.get("Shares", "0").replace(",", ".")),
                    price=float(row.get("Price", "0").replace(",", ".")),
                    fees=abs(float(row.get("Fee", "0").replace(",", "."))),
                    currency="EUR",
                ))
            except Exception:
                continue
        return result

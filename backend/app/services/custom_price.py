"""
Fetch del prezzo da un endpoint JSON configurabile (price_source = CUSTOM_JSON).

Ogni strumento CUSTOM_JSON ha:
  custom_url            — endpoint HTTP; i placeholder {ISIN} e {TICKER} sono
                          sostituiti a runtime con i dati dello strumento
  custom_jsonpath_price — espressione JSONPath per estrarre il prezzo
  custom_jsonpath_date  — (opzionale) JSONPath per la data della quotazione;
                          se assente si usa la data corrente

JSONPath via jsonpath-ng (sintassi estesa: filtri `[?...]`, slice, ecc.).
Tutti gli errori (rete, HTTP, JSON malformato, path senza match, valore non
numerico) sollevano CustomPriceError con un messaggio leggibile: il chiamante
decide se mostrarlo (endpoint di test) o registrarlo sullo strumento senza
rompere il refresh degli altri (refresh notturno).
"""
import logging
from datetime import date, datetime
from typing import Optional, Tuple

import httpx
from jsonpath_ng.ext import parse as jsonpath_parse

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}
FETCH_TIMEOUT = 10.0


class CustomPriceError(Exception):
    """Errore di configurazione o di fetch di una fonte prezzo custom."""


def render_url(url: str, isin: Optional[str] = None, ticker: Optional[str] = None) -> str:
    """Sostituisce {ISIN} e {TICKER} nella URL. Replace semplice (non str.format):
    eventuali altre graffe nella URL non devono esplodere."""
    out = (url or "").strip()
    if "{ISIN}" in out:
        if not isin:
            raise CustomPriceError("La URL usa {ISIN} ma lo strumento non ha un ISIN")
        out = out.replace("{ISIN}", isin)
    if "{TICKER}" in out:
        if not ticker:
            raise CustomPriceError("La URL usa {TICKER} ma lo strumento non ha un ticker")
        out = out.replace("{TICKER}", ticker)
    return out


def extract_value(data, jsonpath_expr: str):
    """Primo match dell'espressione JSONPath su `data` (JSON già decodificato)."""
    try:
        expr = jsonpath_parse(jsonpath_expr)
    except Exception as exc:
        raise CustomPriceError(f"JSONPath non valido {jsonpath_expr!r}: {exc}") from exc
    matches = expr.find(data)
    if not matches:
        raise CustomPriceError(f"Nessun valore trovato per il JSONPath {jsonpath_expr!r}")
    return matches[0].value


def _to_price(value) -> float:
    """Converte il valore estratto in float. Accetta numeri e stringhe, anche
    con la virgola decimale italiana ("102,35") e separatori di migliaia."""
    if isinstance(value, bool) or value is None:
        raise CustomPriceError(f"Il valore estratto non è un prezzo: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(" ", "")
        if "," in s:
            # "1.234,56" → "1234.56"; "102,35" → "102.35"
            s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            pass
    raise CustomPriceError(f"Il valore estratto non è un prezzo: {value!r}")


def _to_date(value) -> date:
    """Converte il valore estratto in data: ISO (con o senza ora), epoch in
    secondi o millisecondi."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ts = float(value)
        if ts > 1e12:   # epoch in millisecondi
            ts /= 1000.0
        try:
            return datetime.utcfromtimestamp(ts).date()
        except (OverflowError, OSError, ValueError) as exc:
            raise CustomPriceError(f"Timestamp non valido: {value!r}") from exc
    if isinstance(value, str):
        s = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s).date()
        except ValueError:
            for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y%m%d"):
                try:
                    return datetime.strptime(value.strip(), fmt).date()
                except ValueError:
                    continue
    raise CustomPriceError(f"Il valore estratto non è una data riconoscibile: {value!r}")


async def fetch_custom_price(
    url: str,
    jsonpath_price: str,
    jsonpath_date: Optional[str] = None,
    isin: Optional[str] = None,
    ticker: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[float, date, str]:
    """
    Fetch + estrazione: ritorna (prezzo, data_quotazione, url_risolta).
    Senza jsonpath_date la data è quella corrente. Solleva CustomPriceError
    per qualunque problema (mai un'eccezione httpx grezza).
    """
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        raise CustomPriceError("URL mancante o non http(s)")
    if not jsonpath_price:
        raise CustomPriceError("JSONPath del prezzo mancante")

    resolved = render_url(url, isin=isin, ticker=ticker)

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True)
    try:
        try:
            resp = await client.get(resolved, headers=_HEADERS)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CustomPriceError(f"HTTP {exc.response.status_code} da {resolved}") from exc
        except httpx.HTTPError as exc:
            raise CustomPriceError(f"Errore di rete verso {resolved}: {exc}") from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise CustomPriceError("La risposta non è JSON valido") from exc

        price = _to_price(extract_value(data, jsonpath_price))
        if price <= 0:
            raise CustomPriceError(f"Prezzo estratto non positivo: {price}")
        quote_date = _to_date(extract_value(data, jsonpath_date)) if jsonpath_date else date.today()
        return price, quote_date, resolved
    finally:
        if own_client:
            await client.aclose()

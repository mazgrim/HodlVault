"""Test dell'estrazione JSONPath e del fetch da fonte JSON custom."""
import asyncio
import json
from datetime import date

import httpx
import pytest

from app.services.custom_price import (
    CustomPriceError,
    extract_value,
    fetch_custom_price,
    render_url,
    _to_date,
    _to_price,
)


# ── render_url ────────────────────────────────────────────────────────────────

def test_render_url_placeholders():
    url = "https://api.example.com/quote/{ISIN}?sym={TICKER}"
    assert render_url(url, isin="XS1234567890", ticker="CERT1") == \
        "https://api.example.com/quote/XS1234567890?sym=CERT1"


def test_render_url_missing_isin_raises():
    with pytest.raises(CustomPriceError):
        render_url("https://x.it/{ISIN}", isin=None, ticker="T")


def test_render_url_leaves_other_braces_alone():
    # Un replace semplice non deve esplodere su graffe estranee nella URL
    assert render_url("https://x.it/q?f={json}", isin=None) == "https://x.it/q?f={json}"


# ── extract_value / JSONPath ──────────────────────────────────────────────────

def test_extract_nested_path():
    data = {"quote": {"last": {"price": 102.35}}}
    assert extract_value(data, "$.quote.last.price") == 102.35


def test_extract_array_index():
    data = {"data": [{"close": 99.1}, {"close": 98.7}]}
    assert extract_value(data, "$.data[0].close") == 99.1


def test_extract_with_filter():
    data = {"results": [
        {"isin": "XS0000000001", "price": 50.0},
        {"isin": "XS0000000002", "price": 75.5},
    ]}
    assert extract_value(data, '$.results[?(@.isin=="XS0000000002")].price') == 75.5


def test_extract_no_match_raises():
    with pytest.raises(CustomPriceError):
        extract_value({"a": 1}, "$.missing.path")


def test_extract_invalid_jsonpath_raises():
    with pytest.raises(CustomPriceError):
        extract_value({"a": 1}, "$..[[[")


# ── Conversioni ───────────────────────────────────────────────────────────────

def test_to_price_accepts_italian_decimal():
    assert _to_price("102,35") == 102.35
    assert _to_price("1.234,56") == 1234.56
    assert _to_price(88) == 88.0


def test_to_price_rejects_garbage():
    for bad in (None, True, "abc", {}):
        with pytest.raises(CustomPriceError):
            _to_price(bad)


def test_to_date_formats():
    assert _to_date("2026-07-10") == date(2026, 7, 10)
    assert _to_date("2026-07-10T16:30:00Z") == date(2026, 7, 10)
    assert _to_date("10/07/2026") == date(2026, 7, 10)
    assert _to_date(1783641600) == date(2026, 7, 10)          # epoch secondi
    assert _to_date(1783641600000) == date(2026, 7, 10)       # epoch millisecondi


# ── fetch_custom_price (httpx.MockTransport) ─────────────────────────────────

def _client_returning(payload, status_code=200, raw=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if raw is not None:
            return httpx.Response(status_code, text=raw)
        return httpx.Response(status_code, text=json.dumps(payload))
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _fetch(client, **kwargs):
    return asyncio.run(fetch_custom_price(client=client, **kwargs))


def test_fetch_success_with_date():
    client = _client_returning({"quote": {"price": "101,20", "date": "2026-07-10"}})
    price, d, resolved = _fetch(
        client,
        url="https://api.example.com/q/{ISIN}",
        jsonpath_price="$.quote.price",
        jsonpath_date="$.quote.date",
        isin="XS1",
    )
    assert price == 101.20
    assert d == date(2026, 7, 10)
    assert resolved == "https://api.example.com/q/XS1"


def test_fetch_without_date_uses_today():
    client = _client_returning({"price": 55.5})
    price, d, _ = _fetch(client, url="https://x.it/q", jsonpath_price="$.price")
    assert price == 55.5
    assert d == date.today()


def test_fetch_http_error_raises_custom_error():
    client = _client_returning({}, status_code=500)
    with pytest.raises(CustomPriceError):
        _fetch(client, url="https://x.it/q", jsonpath_price="$.price")


def test_fetch_invalid_json_raises_custom_error():
    client = _client_returning(None, raw="<html>not json</html>")
    with pytest.raises(CustomPriceError):
        _fetch(client, url="https://x.it/q", jsonpath_price="$.price")


def test_fetch_nonpositive_price_raises():
    client = _client_returning({"price": 0})
    with pytest.raises(CustomPriceError):
        _fetch(client, url="https://x.it/q", jsonpath_price="$.price")


def test_fetch_rejects_non_http_url():
    with pytest.raises(CustomPriceError):
        asyncio.run(fetch_custom_price(url="file:///etc/passwd", jsonpath_price="$.p"))

"""
Calcolo della tassazione su dividendi e cedole per un residente fiscale italiano.

Modello "netto frontiera": un dividendo estero subisce prima la ritenuta alla
fonte del paese di origine, poi l'imposta sostitutiva italiana (26% sui dividendi
azionari/ETF, 12,5% sulle cedole di titoli di Stato/obbligazioni white-list)
calcolata sul lordo già al netto della ritenuta estera.

    base       = max(0, gross - accrued_interest)   # rateo cedolare deducibile
    foreign    = gross * foreign_rate(paese)
    italian    = (base - foreign) * italian_rate(tipo/asset_class)
    net        = gross - foreign - italian

Le aliquote estere sono STIME per i principali paesi (le convenzioni reali /
moduli W-8BEN possono differire) e sono override-abili via env FOREIGN_WHT_<...>.
"""
from __future__ import annotations

import os
from typing import NamedTuple, Optional

from ..models import DividendType, AssetClass


# ── Aliquote italiane (imposta sostitutiva) ───────────────────────────────────
def _italian_rate(div_type: DividendType, asset_class: Optional[AssetClass]) -> float:
    # Cedole di certificati: 26% a prescindere dall'asset class (quelle
    # condizionate sono redditi diversi, quelle garantite redditi di capitale,
    # ma l'aliquota è comunque il 26% — il sottotipo CERT_COUPON resta
    # tracciato per future distinzioni, es. compensazione minusvalenze).
    if div_type == DividendType.CERT_COUPON:
        return float(os.getenv("TAX_RATE_CERTIFICATE", os.getenv("TAX_RATE_DIVIDEND", "0.26")))
    is_bond = div_type == DividendType.COUPON or asset_class == AssetClass.BOND
    if is_bond:
        return float(os.getenv("TAX_RATE_COUPON", "0.125"))
    return float(os.getenv("TAX_RATE_DIVIDEND", "0.26"))


# ── Ritenute alla fonte estere (stime) ────────────────────────────────────────
# Chiave = nome paese inglese di Yahoo (Instrument.country), in minuscolo.
_FOREIGN_WHT = {
    "united states": 0.15, "usa": 0.15, "us": 0.15, "u.s.": 0.15,
    "canada": 0.15,
    "germany": 0.26375,
    "france": 0.26,
    "switzerland": 0.35,
    "netherlands": 0.15,
    "spain": 0.19,
    "united kingdom": 0.0, "uk": 0.0,          # niente ritenuta UK sui dividendi
    "ireland": 0.0, "luxembourg": 0.0,         # ETF UCITS domiciliati: no WHT sulle distribuzioni
    "italy": 0.0, "italia": 0.0,               # domestico: solo imposta italiana
    "japan": 0.15315,
    "belgium": 0.30,
    "denmark": 0.27,
    "finland": 0.35,
    "sweden": 0.30,
    "norway": 0.25,
    "austria": 0.275,
    "portugal": 0.28,
    "australia": 0.30,
}

# Codici ISO per gli override via env (FOREIGN_WHT_US=0.30, ...).
_COUNTRY_TO_ISO = {
    "united states": "US", "usa": "US", "us": "US", "u.s.": "US",
    "canada": "CA", "germany": "DE", "france": "FR", "switzerland": "CH",
    "netherlands": "NL", "spain": "ES", "united kingdom": "GB", "uk": "GB",
    "ireland": "IE", "luxembourg": "LU", "italy": "IT", "italia": "IT",
    "japan": "JP", "belgium": "BE", "denmark": "DK", "finland": "FI",
    "sweden": "SE", "norway": "NO", "austria": "AT", "portugal": "PT",
    "australia": "AU",
}


def foreign_rate(country: Optional[str]) -> float:
    """Ritenuta alla fonte stimata per il paese (0.0 se sconosciuto)."""
    if not country:
        return 0.0
    key = country.strip().lower()
    iso = _COUNTRY_TO_ISO.get(key)
    if iso:
        override = os.getenv(f"FOREIGN_WHT_{iso}")
        if override is not None:
            try:
                return float(override)
            except ValueError:
                pass
    return _FOREIGN_WHT.get(key, 0.0)


class TaxBreakdown(NamedTuple):
    net: float            # netto incassato (orig ccy)
    foreign_tax: float    # ritenuta estera (orig ccy)
    italian_tax: float    # imposta sostitutiva italiana (orig ccy)
    foreign_rate: float   # aliquota estera usata (es. 0.15)
    italian_rate: float   # aliquota italiana usata (es. 0.26)


def compute_net(
    gross: float,
    div_type: DividendType,
    asset_class: Optional[AssetClass],
    country: Optional[str] = None,
    accrued_interest: float = 0.0,
    known_tax: Optional[float] = None,
) -> TaxBreakdown:
    """
    Calcola il netto e la scomposizione delle imposte su un lordo.

    Se `known_tax` è fornito (es. ritenuta reale dal CSV del broker) lo si usa
    come tassa TOTALE senza stimare nulla; altrimenti si stima la doppia
    imposizione estera + italiana.
    """
    i_rate = _italian_rate(div_type, asset_class)

    if known_tax is not None:
        known_tax = max(0.0, float(known_tax))
        net = gross - known_tax
        eff_rate = (known_tax / gross) if gross else 0.0
        # La tassa reale dal CSV non è scomposta: la attribuiamo all'imposta italiana.
        return TaxBreakdown(
            net=round(net, 4),
            foreign_tax=0.0,
            italian_tax=round(known_tax, 4),
            foreign_rate=0.0,
            italian_rate=round(eff_rate, 5),
        )

    # Le cedole dei certificati non subiscono ritenuta alla fonte estera
    # (l'emittente paga il lordo, tassato solo in Italia).
    f_rate = 0.0 if div_type == DividendType.CERT_COUPON else foreign_rate(country)
    base = max(0.0, gross - max(0.0, accrued_interest))
    foreign_tax = gross * f_rate
    italian_tax = max(0.0, base - foreign_tax) * i_rate
    net = gross - foreign_tax - italian_tax
    return TaxBreakdown(
        net=round(net, 4),
        foreign_tax=round(foreign_tax, 4),
        italian_tax=round(italian_tax, 4),
        foreign_rate=f_rate,
        italian_rate=i_rate,
    )

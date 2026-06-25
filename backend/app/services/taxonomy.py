"""
Tassonomia e traduzioni in italiano per la sezione Analisi.

- Macro asset class: Azioni, Obbligazioni, Materie Prime, Crypto, Liquidità, Altro
  (gli ETF NON sono una categoria a sé: vengono ricondotti a Azioni/Obbligazioni/…
   in base alla loro composizione di look-through).
- Settori e Paesi tradotti dai codici/nomi inglesi di Yahoo all'italiano.
"""
from typing import Optional

# Macro asset class (etichette mostrate all'utente)
AZIONI = "Azioni"
OBBLIGAZIONI = "Obbligazioni"
MATERIE_PRIME = "Materie Prime"
CRYPTO = "Crypto"
LIQUIDITA = "Liquidità"
ALTRO = "Altro"

# ── Settori (chiavi Yahoo e nomi visualizzati) → italiano ──────────────────────
_SECTOR_IT = {
    "technology": "Tecnologia",
    "financial_services": "Finanza",
    "financial services": "Finanza",
    "healthcare": "Salute",
    "consumer_cyclical": "Beni ciclici",
    "consumer cyclical": "Beni ciclici",
    "consumer_defensive": "Beni difensivi",
    "consumer defensive": "Beni difensivi",
    "communication_services": "Comunicazioni",
    "communication services": "Comunicazioni",
    "industrials": "Industria",
    "energy": "Energia",
    "utilities": "Utility",
    "real_estate": "Immobiliare",
    "realestate": "Immobiliare",
    "real estate": "Immobiliare",
    "basic_materials": "Materiali di base",
    "basic materials": "Materiali di base",
}

# ── Paesi (nomi Yahoo e codici ISO usati internamente) → italiano ──────────────
_COUNTRY_IT = {
    "united states": "Stati Uniti", "usa": "Stati Uniti", "us": "Stati Uniti", "u.s.": "Stati Uniti",
    "italy": "Italia", "ita": "Italia", "it": "Italia",
    "ireland": "Irlanda", "irl": "Irlanda", "ie": "Irlanda",
    "germany": "Germania", "deu": "Germania", "de": "Germania",
    "france": "Francia", "fra": "Francia", "fr": "Francia",
    "united kingdom": "Regno Unito", "gbr": "Regno Unito", "gb": "Regno Unito", "uk": "Regno Unito",
    "switzerland": "Svizzera", "che": "Svizzera", "ch": "Svizzera",
    "netherlands": "Paesi Bassi", "nld": "Paesi Bassi", "nl": "Paesi Bassi",
    "spain": "Spagna", "esp": "Spagna", "es": "Spagna",
    "japan": "Giappone", "jpn": "Giappone", "jp": "Giappone",
    "china": "Cina", "chn": "Cina", "cn": "Cina",
    "canada": "Canada", "can": "Canada", "ca": "Canada",
    "australia": "Australia", "aus": "Australia", "au": "Australia",
    "sweden": "Svezia", "swe": "Svezia", "se": "Svezia",
    "denmark": "Danimarca", "dnk": "Danimarca", "dk": "Danimarca",
    "norway": "Norvegia", "nor": "Norvegia", "no": "Norvegia",
    "finland": "Finlandia", "fin": "Finlandia", "fi": "Finlandia",
    "belgium": "Belgio", "bel": "Belgio", "be": "Belgio",
    "india": "India", "ind": "India", "in": "India",
    "brazil": "Brasile", "bra": "Brasile", "br": "Brasile",
    "south korea": "Corea del Sud", "kor": "Corea del Sud", "kr": "Corea del Sud",
    "taiwan": "Taiwan", "twn": "Taiwan", "tw": "Taiwan",
    "hong kong": "Hong Kong", "hkg": "Hong Kong", "hk": "Hong Kong",
}


# ── Aree geografiche ───────────────────────────────────────────────────────────
NORD_AMERICA = "Nord America"
EUROPA = "Europa"
GIAPPONE = "Giappone"
ASIA_PACIFICO = "Asia-Pacifico"
MERCATI_EMERGENTI = "Mercati Emergenti"
ALTRI_MERCATI = "Altri mercati"

_REGION = {
    "united states": NORD_AMERICA, "usa": NORD_AMERICA, "us": NORD_AMERICA, "u.s.": NORD_AMERICA,
    "canada": NORD_AMERICA, "can": NORD_AMERICA, "ca": NORD_AMERICA,
    "italy": EUROPA, "italia": EUROPA, "ita": EUROPA, "it": EUROPA,
    "germany": EUROPA, "germania": EUROPA, "deu": EUROPA, "de": EUROPA,
    "france": EUROPA, "francia": EUROPA, "fra": EUROPA, "fr": EUROPA,
    "united kingdom": EUROPA, "regno unito": EUROPA, "gbr": EUROPA, "gb": EUROPA, "uk": EUROPA,
    "switzerland": EUROPA, "svizzera": EUROPA, "che": EUROPA, "ch": EUROPA,
    "netherlands": EUROPA, "paesi bassi": EUROPA, "nld": EUROPA, "nl": EUROPA,
    "spain": EUROPA, "spagna": EUROPA, "esp": EUROPA, "es": EUROPA,
    "sweden": EUROPA, "svezia": EUROPA, "denmark": EUROPA, "danimarca": EUROPA,
    "norway": EUROPA, "norvegia": EUROPA, "finland": EUROPA, "finlandia": EUROPA,
    "belgium": EUROPA, "belgio": EUROPA, "ireland": EUROPA, "irlanda": EUROPA, "irl": EUROPA,
    "austria": EUROPA, "portugal": EUROPA, "portogallo": EUROPA,
    "japan": GIAPPONE, "giappone": GIAPPONE, "jpn": GIAPPONE, "jp": GIAPPONE,
    "australia": ASIA_PACIFICO, "aus": ASIA_PACIFICO,
    "hong kong": ASIA_PACIFICO, "hkg": ASIA_PACIFICO, "singapore": ASIA_PACIFICO,
    "new zealand": ASIA_PACIFICO,
    "china": MERCATI_EMERGENTI, "cina": MERCATI_EMERGENTI, "chn": MERCATI_EMERGENTI, "cn": MERCATI_EMERGENTI,
    "india": MERCATI_EMERGENTI, "ind": MERCATI_EMERGENTI,
    "brazil": MERCATI_EMERGENTI, "brasile": MERCATI_EMERGENTI,
    "taiwan": MERCATI_EMERGENTI, "twn": MERCATI_EMERGENTI,
    "south korea": MERCATI_EMERGENTI, "corea del sud": MERCATI_EMERGENTI, "kor": MERCATI_EMERGENTI,
    "mexico": MERCATI_EMERGENTI, "south africa": MERCATI_EMERGENTI,
    "indonesia": MERCATI_EMERGENTI, "thailand": MERCATI_EMERGENTI, "malaysia": MERCATI_EMERGENTI,
    "saudi arabia": MERCATI_EMERGENTI, "turkey": MERCATI_EMERGENTI,
}


def region_for(country_raw: Optional[str]) -> str:
    if not country_raw:
        return ALTRI_MERCATI
    return _REGION.get(country_raw.strip().lower(), ALTRI_MERCATI)


def sector_it(raw: Optional[str]) -> str:
    if not raw:
        return ALTRO
    return _SECTOR_IT.get(raw.strip().lower(), raw.strip())


def country_it(raw: Optional[str]) -> str:
    if not raw:
        return ALTRO
    return _COUNTRY_IT.get(raw.strip().lower(), raw.strip())


def macro_for_simple(asset_class_value: str) -> str:
    """Macro asset class per uno strumento non-ETF (azione, bond, crypto, ecc.)."""
    v = (asset_class_value or "").upper()
    if v == "CRYPTO":
        return CRYPTO
    if v == "COMMODITY":
        return MATERIE_PRIME
    if v == "BOND":
        return OBBLIGAZIONI
    if v == "CASH":
        return LIQUIDITA
    if v in ("EQUITY", "REAL_ESTATE"):
        return AZIONI
    return ALTRO


def etf_macro_split(profile) -> dict:
    """Ripartizione del valore di un ETF tra le macro asset class (frazioni che sommano ~1).

    `profile` è un EtfProfile (o None). Se mancano dati, ricade su 'Altro'.
    """
    if not profile:
        return {ALTRO: 1.0}
    cat = (profile.category or "").lower()
    if any(k in cat for k in ("crypto", "bitcoin", "ethereum", "digital asset")):
        return {CRYPTO: 1.0}
    split = {
        AZIONI: profile.equity_pct or 0.0,
        OBBLIGAZIONI: profile.bond_pct or 0.0,
        MATERIE_PRIME: profile.commodity_pct or 0.0,
        LIQUIDITA: profile.cash_pct or 0.0,
        ALTRO: profile.other_pct or 0.0,
    }
    total = sum(split.values())
    if total <= 0:
        return {ALTRO: 1.0}
    return {k: v / total for k, v in split.items() if v > 0}

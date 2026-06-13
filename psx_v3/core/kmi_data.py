"""
KMI All Share Index constituents and Shariah reference data.
Source: Pakistan Stock Exchange / Al Meezan Investment Management
Last manually verified: 2024. Always cross-check with the live KMI list at
https://www.almeezangroup.com/kmi-shariah-screener/
"""

# ── KMI All Share Index constituents (PSX tickers, no suffix) ─────────────────
KMI_ALL_SHARE = [
    # Technology & Telecom
    "SYS", "TRG", "NETSOL", "AVN", "TELE", "PTC", "WTL", "OCTOPUS", "AIRLINK",
    # Oil & Gas Exploration
    "OGDC", "PPL", "MARI", "POL",
    # Oil & Gas Marketing
    "PSO", "HASCOL", "APL", "SNGP", "SSGC", "SHEL",
    # Refineries
    "ATR", "PRL", "NRL", "CNERGY",
    # Cement
    "LUCK", "DGKC", "MLCF", "PIOC", "CHCC", "FCCL", "KOHC", "BWCL", "SGWL", "FLYNG", "PAEL",
    # Fertilizer
    "ENGRO", "EFERT", "FATIMA", "FFC", "FFBL",
    # Power Generation & Distribution
    "HUBC", "NCPL", "KAPCO", "PKGP", "LTPH", "NPL", "SPEL", "EPQL", "KEL",
    # Chemicals & Paper
    "ICI", "LOTCHEM", "SITC", "DYNO", "EPCL", "SPL",
    # Textile
    "NML", "GATM", "KTML", "NCL", "ANL", "DSFL", "ILP", "MSOT", "HAWL",
    # Food & Beverages / Personal Care
    "NESTLE", "QUICE", "UNITY", "NATF", "FCEPL", "SHEZ", "MFFL", "UPFL",
    # Pharmaceuticals
    "SEARL", "HINOON", "GLAXO", "ABOT", "FEROZ", "AGP", "IBFL",
    # Steel & Engineering
    "ISL", "ASTL", "MUGHAL", "CSAP", "ASL", "INIL", "KSBP", "ITTEFAQ",
    # Automobile Assembler / Parts
    "HCAR", "INDU", "MTL", "GHNI", "GHNL", "GTYR", "THALL", "LOADS",
    # Glass & Ceramics
    "GHGL", "TGL",
    # Transport / Logistics
    "PIBTL", "TRIPF",
    # Miscellaneous / Real Estate
    "MEDIA", "PACE", "TPL", "TPLP", "GTECH"
]

# ── Shariah screening thresholds ──────────────────────────────────────────────
SHARIAH_THRESHOLDS = {
    "max_debt_to_assets":        0.33,   # Interest-bearing debt / total assets
    "max_non_halal_income":      0.05,   # Non-halal revenue / total revenue
    "min_illiquid_assets":       0.25,   # Illiquid assets / total assets (conservative: 0.50)
    "min_illiquid_assets_strict":0.50,   # Stricter scholar standard
    "market_cap_gt_net_assets":  True,   # Market cap must exceed net liquid assets
}

# ── Sectors considered haram (core business screen) ──────────────────────────
HARAM_SECTORS = [
    "conventional banking",
    "insurance (conventional)",
    "alcohol",
    "tobacco",
    "gambling",
    "pork",
    "pornography",
    "weapons of mass destruction",
    "interest-based finance",
]

# ── Known non-compliant PSX tickers (conventional banks etc.) ─────────────────
# These will immediately fail core business screen.
KNOWN_NON_COMPLIANT = [
    "HBL", "UBL", "MCB", "ABL", "BAFL", "BAHL", "SNBL",
    "MEBL", "AKBL", "NBP", "BOP", "SILK", "JSBL",
    # Conventional insurance
    "EFU", "JUBILEE", "ADAMJEE",
    # Tobacco
    "PMPKL",
]

# ── Islamic banking (compliant by structure) ─────────────────────────────────
ISLAMIC_BANKS = ["MEBL", "BIPL"]  # Meezan Bank, Bank Islami

# ── Default watchlist shown on startup ───────────────────────────────────────
DEFAULT_WATCHLIST = [
    "SYS", "ENGRO", "LUCK", "OGDC", "PPL", "MARI",
    "HUBC", "FFC", "EFERT", "NESTLE", "SEARL", "ICI",
]

# ── PSX trading hours (PKT = UTC+5) ─────────────────────────────────────────
PSX_OPEN_HOUR   = 9    # 09:30 PKT
PSX_OPEN_MINUTE = 30
PSX_CLOSE_HOUR  = 15   # 15:30 PKT
PSX_CLOSE_MINUTE= 30

from pathlib import Path
import json
import requests
import re
import logging
from datetime import datetime, timedelta

_KMI_CACHE = Path("data/kmi_live_cache.json")
_CACHE_TTL_HOURS = 24
_CACHE_STALE_DAYS = 7
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
_last_fetch_source = "hardcoded_fallback"
_last_fetched_at = ""

def fetch_live_kmi_constituents() -> list[str]:
    global _last_fetch_source, _last_fetched_at
    _KMI_CACHE.parent.mkdir(parents=True, exist_ok=True)
    
    # Step 0 — Cache check
    if _KMI_CACHE.exists():
        try:
            with open(_KMI_CACHE) as f:
                cache = json.load(f)
            fetched_at = datetime.fromisoformat(cache["fetched_at"])
            if datetime.now() - fetched_at < timedelta(hours=_CACHE_TTL_HOURS):
                _last_fetch_source = "cached"
                _last_fetched_at = cache.get("fetched_at", datetime.now().isoformat())
                return cache["symbols"]
        except Exception as e:
            logging.getLogger("kmi_data").warning(f"Failed to read KMI cache: {e}")

    # Attempt 1 — PSX JSON API
    try:
        r = requests.get("https://dps.psx.com.pk/marginsymbols/KMI", headers=_HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            symbols = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        symbols.append(item.strip().upper())
                    elif isinstance(item, dict):
                        for field in ["symbol", "SYMBOL", "ticker", "scrip"]:
                            if field in item:
                                symbols.append(str(item[field]).strip().upper())
                                break
            elif isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, list):
                        for item in val:
                            if isinstance(item, dict):
                                for field in ["symbol", "SYMBOL", "ticker", "scrip"]:
                                    if field in item:
                                        symbols.append(str(item[field]).strip().upper())
                                        break
            symbols = list(set([s for s in symbols if s]))
            if len(symbols) >= 20:
                _last_fetched_at = datetime.now().isoformat()
                cache_data = {
                    "symbols": symbols,
                    "source": "live_psx_api",
                    "fetched_at": _last_fetched_at,
                    "count": len(symbols)
                }
                with open(_KMI_CACHE, "w") as f:
                    json.dump(cache_data, f, indent=2)
                _last_fetch_source = "live_psx_api"
                return symbols
    except Exception as e:
        logging.getLogger("kmi_data").warning(f"Attempt 1: PSX JSON API fetch failed: {e}")

    # Attempt 2 — Al Meezan screener page or PSX market indices page
    # Let's try Al Meezan screener page first
    try:
        from bs4 import BeautifulSoup
        r = requests.get("https://www.almeezangroup.com/kmi-shariah-screener/", headers=_HEADERS, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            symbols = []
            for row in soup.find_all("tr"):
                for cell in row.find_all(["td", "th"]):
                    text = cell.get_text().strip()
                    if re.match(r'^[A-Z]{2,6}$', text):
                        symbols.append(text)
            symbols = list(set(symbols))
            if len(symbols) >= 20:
                _last_fetched_at = datetime.now().isoformat()
                cache_data = {
                    "symbols": symbols,
                    "source": "live_meezan",
                    "fetched_at": _last_fetched_at,
                    "count": len(symbols)
                }
                with open(_KMI_CACHE, "w") as f:
                    json.dump(cache_data, f, indent=2)
                _last_fetch_source = "live_meezan"
                return symbols
    except Exception as e:
        logging.getLogger("kmi_data").warning(f"Attempt 2a: Al Meezan fetch failed: {e}")

    # If that fails, try PSX market-data indices page
    try:
        from bs4 import BeautifulSoup
        r = requests.get("https://www.psx.com.pk/market-data/indices", headers=_HEADERS, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            symbols = []
            for cell in soup.find_all(["td", "th", "span", "a"]):
                text = cell.get_text().strip()
                if re.match(r'^[A-Z]{2,6}$', text):
                    symbols.append(text)
            symbols = list(set(symbols))
            if len(symbols) >= 20:
                _last_fetched_at = datetime.now().isoformat()
                cache_data = {
                    "symbols": symbols,
                    "source": "live_meezan",
                    "fetched_at": _last_fetched_at,
                    "count": len(symbols)
                }
                with open(_KMI_CACHE, "w") as f:
                    json.dump(cache_data, f, indent=2)
                _last_fetch_source = "live_meezan"
                return symbols
    except Exception as e:
        logging.getLogger("kmi_data").warning(f"Attempt 2b: PSX indices page parse failed: {e}")

    # Attempt 3 — Stale cache
    if _KMI_CACHE.exists():
        try:
            with open(_KMI_CACHE) as f:
                cache = json.load(f)
            fetched_at = datetime.fromisoformat(cache["fetched_at"])
            age = datetime.now() - fetched_at
            if age < timedelta(days=_CACHE_STALE_DAYS):
                logging.getLogger("kmi_data").warning(f"KMI live fetch failed — using cache from {age} ago")
                _last_fetch_source = "cached"
                _last_fetched_at = cache.get("fetched_at", datetime.now().isoformat())
                return cache["symbols"]
        except Exception as e:
            pass

    # Fallback
    logging.getLogger("kmi_data").warning("WARNING: Using hardcoded KMI list — all live fetches failed. Shariah accuracy reduced.")
    _last_fetch_source = "hardcoded_fallback"
    _last_fetched_at = datetime.now().isoformat()
    return KMI_ALL_SHARE

def is_kmi_listed_live(symbol: str) -> dict:
    symbols = fetch_live_kmi_constituents()
    
    last_updated = _last_fetched_at
    if _last_fetch_source == "hardcoded_fallback":
        confidence = "LOW"
    elif _last_fetch_source == "cached":
        try:
            fetched_at = datetime.fromisoformat(last_updated)
            age = datetime.now() - fetched_at
            if age < timedelta(days=3):
                confidence = "MEDIUM"
            else:
                confidence = "LOW"
        except Exception:
            confidence = "MEDIUM"
    else:
        confidence = "HIGH"
        
    sym_upper = symbol.upper()
    listed = sym_upper in symbols
    
    return {
        "symbol": sym_upper,
        "kmi_listed": listed,
        "source": _last_fetch_source,
        "last_updated": last_updated,
        "confidence": confidence
    }

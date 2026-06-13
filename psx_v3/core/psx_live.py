"""
psx_live.py - Live PSX market data via the PSX public data portal.
No authentication required. All endpoints return JSON or parseable structure.

Base URL: https://dps.psx.com.pk

Falls back to yfinance for any failed request.
Never crashes — every function returns a safe fallback dict.
"""

import logging
import requests
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

PSX_API_BASE = "https://dps.psx.com.pk"
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Referer": "https://dps.psx.com.pk/",
    "Origin": "https://dps.psx.com.pk",
})
_TIMEOUT = 8

# Capital Stakes removed — required paid subscription. Replaced with PSX public API.

def get_live_quote(symbol: str) -> dict:
    """
    Fetch a live quote for a symbol from the PSX public portal.
    Falls back to yfinance if the request fails.
    """
    symbol = symbol.upper()
    url = f"{PSX_API_BASE}/quotes/{symbol}"
    
    try:
        resp = _SESSION.get(url, timeout=_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            # Try to extract the last price from common PSX JSON structures
            price = None
            for key in ["last", "close", "ldcp", "currentPrice", "price"]:
                if key in data and data[key] is not None:
                    price = float(str(data[key]).replace(",", ""))
                    break
            
            # Bid-Ask depth for Order Book Imbalance calculation
            bid = float(str(data.get("bid", 0)).replace(",", ""))
            ask = float(str(data.get("ask", 0)).replace(",", ""))
            bid_volume = float(str(data.get("bidVolume", 0)).replace(",", ""))
            ask_volume = float(str(data.get("askVolume", 0)).replace(",", ""))
            
            if price:
                return {
                    "symbol": symbol,
                    "last_price": price,
                    "bid": bid,
                    "ask": ask,
                    "bid_volume": bid_volume,
                    "ask_volume": ask_volume,
                    "source": "psx_live",
                    "timestamp": datetime.now().isoformat()
                }
    except Exception as e:
        logger.warning(f"Failed to fetch live PSX quote for {symbol}: {e}")
        
    # Fallback to yfinance
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{symbol}.KA")
        info = ticker.fast_info
        price = info.last_price
        if price:
            return {
                "symbol": symbol,
                "last_price": price,
                "bid": 0.0,
                "ask": 0.0,
                "bid_volume": 0.0,
                "ask_volume": 0.0,
                "source": "yfinance",
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        logger.error(f"Fallback yfinance failed for {symbol}: {e}")
        
    return {
        "symbol": symbol,
        "last_price": None,
        "bid": 0.0,
        "ask": 0.0,
        "bid_volume": 0.0,
        "ask_volume": 0.0,
        "source": "unavailable",
        "timestamp": datetime.now().isoformat()
    }

def get_live_quotes_batch(symbols: list[str]) -> dict[str, dict]:
    """Fetch live quotes for multiple symbols concurrently."""
    results = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(get_live_quote, sym): sym for sym in symbols}
        for future in futures:
            sym = futures[future]
            try:
                results[sym] = future.result()
            except Exception as e:
                logger.error(f"Thread execution failed for {sym}: {e}")
                results[sym] = {
                    "symbol": sym,
                    "last_price": None,
                    "bid": 0.0,
                    "ask": 0.0,
                    "bid_volume": 0.0,
                    "ask_volume": 0.0,
                    "source": "unavailable",
                    "timestamp": datetime.now().isoformat()
                }
    return results

def get_market_status() -> dict:
    """Fetch the current market status (open/closed, KSE-100 level, changes, decliners/advancers)."""
    url = f"{PSX_API_BASE}/online"
    try:
        resp = _SESSION.get(url, timeout=_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "status": data.get("status", "CLOSED").upper(),
                "kse100_value": float(str(data.get("kse100", {}).get("value", 0)).replace(",", "")),
                "kse100_change": float(str(data.get("kse100", {}).get("change", 0)).replace(",", "")),
                "kse100_pct": float(str(data.get("kse100", {}).get("percentage", 0)).replace("%", "").replace(",", "")),
                "total_volume": float(str(data.get("volume", 0)).replace(",", "")),
                "advancers": int(data.get("advancers", 0)),
                "decliners": int(data.get("decliners", 0)),
                "source": "psx_live",
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        logger.warning(f"Failed to fetch market status from PSX: {e}")
        
    return {
        "status": "UNKNOWN",
        "kse100_value": 0.0,
        "kse100_change": 0.0,
        "kse100_pct": 0.0,
        "total_volume": 0.0,
        "advancers": 0,
        "decliners": 0,
        "source": "unavailable",
        "timestamp": datetime.now().isoformat()
    }

def get_market_watch() -> list[dict]:
    """Fetch market watch summary of all symbols traded today."""
    url = f"{PSX_API_BASE}/mktwatch"
    try:
        resp = _SESSION.get(url, timeout=_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "data" in data:
                return data["data"]
    except Exception as e:
        logger.warning(f"Failed to fetch market watch from PSX: {e}")
    return []

def get_psx_announcements(symbol: Optional[str] = None) -> list[dict]:
    """Fetch recent announcements from the PSX portal. Optionally filter by symbol."""
    url = f"{PSX_API_BASE}/announcements"
    try:
        resp = _SESSION.get(url, timeout=_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            announcements = []
            raw_list = data if isinstance(data, list) else data.get("data", [])
            for item in raw_list:
                sym = str(item.get("symbol", "")).upper()
                if symbol and sym != symbol.upper():
                    continue
                
                # Try parsing announcement type based on headline
                headline = item.get("headline", "")
                ann_type = "GENERAL"
                if "dividend" in headline.lower():
                    ann_type = "DIVIDEND_ANNOUNCED"
                elif "financial result" in headline.lower() or "quarterly" in headline.lower():
                    ann_type = "QUARTERLY_RESULTS"
                elif "earnings" in headline.lower() or "profit" in headline.lower():
                    ann_type = "EARNINGS_BEAT" if "increase" in headline.lower() else "EARNINGS_MISS"
                elif "auditor" in headline.lower() and "resign" in headline.lower():
                    ann_type = "AUDITOR_RESIGNED"
                elif "default" in headline.lower():
                    ann_type = "DEFAULT_RISK"
                    
                announcements.append({
                    "symbol": sym,
                    "announcement_date": item.get("date", datetime.now().strftime("%Y-%m-%d")),
                    "announcement_type": ann_type,
                    "headline": headline,
                    "details": item.get("details", "")
                })
            return announcements
    except Exception as e:
        logger.warning(f"Failed to fetch announcements from PSX: {e}")
    return []

def get_kmi_constituents_live() -> list[str]:
    """Retrieve the KMI constituents list."""
    from core.kmi_data import fetch_live_kmi_constituents
    return fetch_live_kmi_constituents()

def record_live_prices(symbols: list[str], pipeline_results: dict) -> None:
    """Record current prices into the SQLite price_history database."""
    from memory.db import record_price
    today_str = datetime.now().strftime("%Y-%m-%d")
    for symbol in symbols:
        res = pipeline_results.get(symbol)
        if res and res.get("price_at_run") is not None:
            try:
                record_price(symbol, today_str, res["price_at_run"])
            except Exception as e:
                logger.error(f"Failed to record live price for {symbol}: {e}")

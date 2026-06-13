"""
core/psx_intraday.py — Real-time Intraday PSX Data Scraper.

Fetches and caches real-time intraday prices and volume from dps.psx.com.pk.
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import pandas as pd

logger = logging.getLogger("psx_intraday")

# Cache directory
CACHE_DIR = Path("data/cache/intraday")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Headers to mimic a browser request
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}

def _cache_path(symbol: str) -> Path:
    """Returns the cache file path for a given symbol."""
    return CACHE_DIR / f"{symbol.upper()}.json"

def _is_fresh(path: Path, max_age_seconds: int = 60) -> bool:
    """Checks if a cache file is fresh."""
    if not path.exists():
        return False
    age = datetime.now().timestamp() - path.stat().st_mtime
    return age < max_age_seconds

def fetch_intraday_data(symbol: str, force_refresh: bool = False) -> dict:
    """
    Fetches real-time intraday price and volume data for a single PSX symbol.
    Data is scraped from dps.psx.com.pk/timeseries/int/{SYMBOL}

    Args:
        symbol: The stock symbol (e.g., "SYS").
        force_refresh: If True, bypasses the cache.

    Returns:
        A dictionary with 'prices' (list of [timestamp_ms, price]) and 'volumes' (list of [timestamp_ms, volume]),
        or an empty dictionary if data cannot be fetched.
    """
    sym = symbol.upper()
    cache_file = _cache_path(sym)

    if not force_refresh and _is_fresh(cache_file, max_age_seconds=45): # Shorter cache for intraday
        try:
            with open(cache_file, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Corrupt JSON in intraday cache for {sym}, refreshing.")

    url = f"https://dps.psx.com.pk/timeseries/int/{sym}"
    data = {"prices": [], "volumes": []}
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status() # Raise an exception for HTTP errors
        raw_data = response.json().get("data", [])

        prices_list = []
        volumes_list = []

        for item in raw_data:
            if len(item) == 3:
                timestamp_ms = item[0] * 1000 # Convert Unix seconds to milliseconds
                price = item[1]
                volume = item[2]
                prices_list.append([timestamp_ms, price])
                volumes_list.append([timestamp_ms, volume])

        data["prices"] = prices_list
        data["volumes"] = volumes_list

        with open(cache_file, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Fetched and cached {len(prices_list)} intraday points for {sym}.")

    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch intraday data for {sym} from PSX: {e}")
    except json.JSONDecodeError:
        logger.warning(f"Failed to decode JSON response for {sym} from PSX.")
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching intraday data for {sym}: {e}")

    return data

def get_latest_intraday_price(symbol: str) -> Optional[float]:
    """Retrieves the latest intraday price from cache or fetches it."""
    data = fetch_intraday_data(symbol)
    if data and data["prices"]:
        return float(data["prices"][-1][1])
    return None

def get_latest_intraday_summary(symbol: str) -> Optional[dict]:
    """Retrieves latest price and total intraday volume."""
    data = fetch_intraday_data(symbol)
    if data and data["prices"] and data["volumes"]:
        latest_price = float(data["prices"][-1][1])
        # Sum all the incremental volumes in the intraday list to get today's total volume
        total_volume = sum(float(v[1]) for v in data["volumes"])
        return {
            "price": latest_price,
            "volume": total_volume
        }
    return None

# Example Usage (for testing)
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Fetching intraday data for SYS:")
    sys_data = fetch_intraday_data("SYS", force_refresh=True)
    if sys_data and sys_data["prices"]:
        print(f"Latest price for SYS: {sys_data['prices'][-1][1]}")
        print(f"Total intraday points: {len(sys_data['prices'])}")
    else:
        print("Could not retrieve intraday data for SYS.")

    print("\nFetching latest intraday price for LUCK:")
    luck_price = get_latest_intraday_price("LUCK")
    if luck_price:
        print(f"Latest price for LUCK: {luck_price}")
    else:
        print("Could not retrieve latest intraday price for LUCK.")

"""
core/psx_index_pipeline.py — Real-time index pipeline for Pakistan Stock Exchange.
Fetches indices data from dps.psx.com.pk with background daemon thread tracking.
"""

import os
import json
import time
import logging
import threading
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
from bs4 import BeautifulSoup

logger = logging.getLogger("psx_index_pipeline")

CACHE_FILE = Path("data/live_index_cache.json")
LOCK_FILE = Path("data/psx_tracker.lock")

# Threading control
_tracker_thread = None
_tracker_lock = threading.Lock()
_running = False

INDEX_SYMBOL_MAP = {
    "KSE100": "KSE-100",
    "KSE30": "KSE-30",
    "KMI30": "KMI-30",
    "ALLSHR": "KSE-ALL"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def _clean_num(val_str: str) -> float:
    """Helper to convert formatted string with commas/percentages to float."""
    if not val_str:
        return 0.0
    try:
        clean = val_str.replace(",", "").replace("%", "").replace("(", "").replace(")", "").strip()
        # Remove any leading plus/minus or unicode arrows
        for char in ["+", "▲", "▼", " "]:
            clean = clean.replace(char, "")
        return float(clean)
    except ValueError:
        return 0.0

def _clean_int(val_str: str) -> int:
    """Helper to convert formatted string with commas to int."""
    if not val_str:
        return 0
    try:
        clean = val_str.replace(",", "").strip()
        return int(clean)
    except ValueError:
        return 0

def fetch_live_indices_from_psx() -> dict:
    """
    Scrapes the PSX data portal home page for the latest index summary.
    If scraping fails, falls back to direct JSON timeseries endpoints.
    """
    url = "https://dps.psx.com.pk/"
    indices = {}
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            panels = soup.find_all("div", class_="marketIndices__details")
            
            for p in panels:
                name = p.get("data-name")
                # We only care about KSE100, KSE30, KMI30, and ALLSHR
                if name not in INDEX_SYMBOL_MAP:
                    continue
                    
                display_name = INDEX_SYMBOL_MAP[name]
                close_val = _clean_num(p.get("data-close"))
                date_str = p.get("data-date")
                
                # Parse Net Change and Percent Change
                price_h1 = p.find("h1", class_="marketIndices__price")
                change_val = 0.0
                pct_change = 0.0
                if price_h1:
                    change_span = price_h1.find("span", class_="marketIndices__change")
                    if change_span:
                        change_text = change_span.get_text().strip()
                        # Expected format: "-1,101.60 (-0.63%)" or "+21.48 (0.12%)"
                        parts = change_text.split("(")
                        if len(parts) == 2:
                            change_val = _clean_num(parts[0])
                            # If change_span has class neg or down-dir, ensure negative
                            if "neg" in change_span.get("class", []) or "-" in parts[0]:
                                if change_val > 0:
                                    change_val = -change_val
                            pct_change = _clean_num(parts[1])
                            if change_val < 0 and pct_change > 0:
                                pct_change = -pct_change
                
                # Parse stats
                stats = {"High": "0", "Low": "0", "Volume": "0", "Previous Close": "0"}
                stats_div = p.find("div", class_="stats")
                if stats_div:
                    items = stats_div.find_all("div", class_="stats_item")
                    for item in items:
                        label_el = item.find("div", class_="stats_label")
                        value_el = item.find("div", class_="stats_value")
                        if label_el and value_el:
                            stats[label_el.get_text().strip()] = value_el.get_text().strip()
                
                indices[name] = {
                    "name": display_name,
                    "value": close_val,
                    "change": change_val,
                    "pct_change": pct_change,
                    "high": _clean_num(stats.get("High")),
                    "low": _clean_num(stats.get("Low")),
                    "volume": _clean_int(stats.get("Volume")),
                    "prev_close": _clean_num(stats.get("Previous Close")) or (close_val - change_val),
                    "date": date_str or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            
            if len(indices) >= 3:
                logger.info(f"Successfully scraped {len(indices)} indices from PSX homepage.")
                return indices
            
    except Exception as e:
        logger.warning(f"Failed to scrape PSX homepage: {e}. Attempting JSON fallback.")

    # Fallback to direct JSON Timeseries endpoints
    logger.info("Running JSON timeseries endpoints fallback for indices...")
    for sym, display_name in INDEX_SYMBOL_MAP.items():
        try:
            # Fetch intraday timeseries for latest close & volume
            int_url = f"https://dps.psx.com.pk/timeseries/int/{sym}"
            int_resp = requests.get(int_url, headers=HEADERS, timeout=10)
            
            # Fetch EOD timeseries for previous close
            eod_url = f"https://dps.psx.com.pk/timeseries/eod/{sym}"
            eod_resp = requests.get(eod_url, headers=HEADERS, timeout=10)
            
            if int_resp.status_code == 200 and eod_resp.status_code == 200:
                int_data = int_resp.json().get("data", [])
                eod_data = eod_resp.json().get("data", [])
                
                if int_data and eod_data:
                    # Intraday newest is first element
                    latest_point = int_data[0]
                    # Format: [timestamp, value, volume]
                    latest_val = float(latest_point[1])
                    latest_ts = int(latest_point[0])
                    
                    # EOD newest is yesterday's close (or today's close if updated)
                    prev_close = float(eod_data[0][1])
                    # If EOD timestamp matches today's date, previous close is the next one
                    # EOD format: [timestamp, value, volume, avg]
                    
                    # Calculate stats from intraday series
                    vals = [float(x[1]) for x in int_data]
                    high_val = max(vals)
                    low_val = min(vals)
                    vol_val = sum(int(x[2]) for x in int_data)
                    
                    change = latest_val - prev_close
                    pct_change = (change / prev_close) * 100 if prev_close > 0 else 0.0
                    
                    dt_str = datetime.fromtimestamp(latest_ts).strftime("%Y-%m-%d %H:%M:%S")
                    
                    indices[sym] = {
                        "name": display_name,
                        "value": round(latest_val, 2),
                        "change": round(change, 2),
                        "pct_change": round(pct_change, 2),
                        "high": round(high_val, 2),
                        "low": round(low_val, 2),
                        "volume": vol_val,
                        "prev_close": round(prev_close, 2),
                        "date": dt_str
                    }
        except Exception as e:
            logger.error(f"Fallback fetch failed for index {sym}: {e}")

    return indices

def start_background_index_tracker(polling_interval_seconds: int = 45):
    """
    Spawns a background thread to fetch indices during Pakistan market hours.
    Safe against multiple calls. Pre-seeds the cache on first call.
    """
    global _tracker_thread, _running
    
    with _tracker_lock:
        if _running:
            return
        _running = True
        
    Path("data").mkdir(exist_ok=True)
    
    # Pre-seed: do an immediate fetch so the dashboard has data on first load
    try:
        indices_data = fetch_live_indices_from_psx()
        if indices_data:
            utc_now = datetime.now(timezone.utc)
            pkt_now = utc_now + timedelta(hours=5)
            cache_payload = {
                "last_updated": pkt_now.strftime("%Y-%m-%d %I:%M:%S %p PKT"),
                "indices": indices_data
            }
            with open(CACHE_FILE, "w") as f:
                json.dump(cache_payload, f, indent=4)
            logger.info(f"Pre-seeded live index cache with {len(indices_data)} indices.")
    except Exception as e:
        logger.warning(f"Pre-seed fetch failed (non-fatal): {e}")
    
    # Start thread
    _tracker_thread = threading.Thread(
        target=_tracker_loop,
        args=(polling_interval_seconds,),
        name="PSXIndexTracker",
        daemon=True
    )
    _tracker_thread.start()
    logger.info("Background PSX Index Tracker thread started successfully.")

def stop_background_index_tracker():
    """Stops the background tracking thread."""
    global _running
    with _tracker_lock:
        _running = False

def _tracker_loop(interval: int):
    """Internal loop that runs in the background thread."""
    global _running
    
    while _running:
        try:
            # 1. Check if market hours (09:00 AM to 04:30 PM PKT, Monday-Friday)
            utc_now = datetime.now(timezone.utc)
            pkt_now = utc_now + timedelta(hours=5)
            
            weekday = pkt_now.weekday()
            is_weekend = weekday >= 5
            
            # Hours range: 09:00 (540 mins) to 16:30 (990 mins)
            current_minutes = pkt_now.hour * 60 + pkt_now.minute
            is_market_active_hours = 540 <= current_minutes <= 990
            
            if is_weekend or not is_market_active_hours:
                # Sleep longer (5 minutes) if market is closed
                time.sleep(300)
                continue
                
            # 2. Fetch and write to cache
            indices_data = fetch_live_indices_from_psx()
            if indices_data:
                # Add overall update timestamp
                cache_payload = {
                    "last_updated": pkt_now.strftime("%Y-%m-%d %I:%M:%S %p PKT"),
                    "indices": indices_data
                }
                with open(CACHE_FILE, "w") as f:
                    json.dump(cache_payload, f, indent=4)
                logger.info("Updated live index cache from PSX portal.")
            
        except Exception as e:
            logger.error(f"Error in PSX tracker loop: {e}", exc_info=True)
            
        # Sleep for polling interval
        time.sleep(interval)

def get_cached_indices() -> dict:
    """Reads the current live index summary from cache."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
            
    # Return defaults if cache empty/not created
    return {
        "last_updated": "Never",
        "indices": {
            "KSE100": {"name": "KSE-100", "value": 0.0, "change": 0.0, "pct_change": 0.0, "high": 0.0, "low": 0.0, "volume": 0, "prev_close": 0.0, "date": ""},
            "KSE30": {"name": "KSE-30", "value": 0.0, "change": 0.0, "pct_change": 0.0, "high": 0.0, "low": 0.0, "volume": 0, "prev_close": 0.0, "date": ""},
            "KMI30": {"name": "KMI-30", "value": 0.0, "change": 0.0, "pct_change": 0.0, "high": 0.0, "low": 0.0, "volume": 0, "prev_close": 0.0, "date": ""},
            "ALLSHR": {"name": "KSE-ALL", "value": 0.0, "change": 0.0, "pct_change": 0.0, "high": 0.0, "low": 0.0, "volume": 0, "prev_close": 0.0, "date": ""}
        }
    }

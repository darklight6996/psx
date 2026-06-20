"""
core/browser_psx_reader.py — Browser Data Fallback for PSX.

Uses Playwright to fetch data from the PSX portal if the API is down or missing data.
Fails gracefully if Playwright is not installed.
"""

import logging
import pandas as pd
import hashlib
from pathlib import Path

logger = logging.getLogger("browser_psx_reader")
CACHE_DIR = Path("data/cache")

def get_cache_path(key: str) -> Path:
    h = hashlib.md5(key.encode()).hexdigest()[:10]
    return CACHE_DIR / f"{h}.parquet"

def parse_psx_timeseries_data(result_data) -> pd.DataFrame:
    """
    Parses the JSON data from PSX /timeseries/eod/{symbol} and returns a DataFrame.
    """
    if not result_data:
        return pd.DataFrame()
        
    if isinstance(result_data, dict) and "data" in result_data:
        data_list = result_data["data"]
    elif isinstance(result_data, list):
        data_list = result_data
    else:
        data_list = []
        
    records = []
    for point in data_list:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            ts = int(point[0])
            val = float(point[1])
            vol = float(point[2]) if len(point) > 2 else 0.0
            
            # If it has more fields (like OHLC), we can extract them
            if len(point) >= 6:
                op = float(point[1])
                hi = float(point[2])
                lo = float(point[3])
                cl = float(point[4])
                vo = float(point[5])
            else:
                op = val
                hi = val
                lo = val
                cl = val
                vo = vol
                
            if ts > 1e11: # milliseconds
                dt = pd.to_datetime(ts, unit='ms', utc=True)
            else:
                dt = pd.to_datetime(ts, unit='s', utc=True)
                
            records.append({
                "Date": dt,
                "Open": op,
                "High": hi,
                "Low": lo,
                "Close": cl,
                "Volume": vo
            })
        except Exception:
            continue
            
    if not records:
        return pd.DataFrame()
        
    df = pd.DataFrame(records)
    df.set_index("Date", inplace=True)
    df.index = df.index.tz_convert("Asia/Karachi")
    return df

def fetch_data_via_browser(symbol: str, period: str = "2y") -> pd.DataFrame:
    """
    Attempts to fetch historical data for a symbol via a headless browser.
    Returns an empty DataFrame if Playwright is not available or scraping fails.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("[Browser Reader] Playwright not installed. Skipping browser fallback.")
        return pd.DataFrame()
        
    sym = symbol.split(".")[0].strip().upper()
    logger.info(f"[Browser Reader] Attempting to fetch {sym} via Playwright...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Navigate to the company page to establish headers and session
            url = f"https://dps.psx.com.pk/company/{sym}"
            page.goto(url, timeout=20000)
            page.wait_for_timeout(2000)
            
            # Evaluate fetch within the page origin to bypass security blocks
            js_code = f"""
            async () => {{
                try {{
                    const response = await fetch('/timeseries/eod/{sym}');
                    const data = await response.json();
                    return data;
                }} catch (e) {{
                    return {{error: e.toString()}};
                }}
            }}
            """
            result = page.evaluate(js_code)
            browser.close()
            
            if isinstance(result, dict) and "error" in result:
                logger.error(f"[Browser Reader] JS execution error: {result['error']}")
                return pd.DataFrame()
                
            df = parse_psx_timeseries_data(result)
            if not df.empty:
                logger.info(f"[Browser Reader] Successfully scraped {len(df)} rows for {sym}")
            return df
            
    except Exception as e:
        logger.error(f"[Browser Reader] Playwright fetch failed for {sym}: {e}")
        return pd.DataFrame()

def save_js_bridge_data_to_cache(symbol: str, raw_data: dict) -> bool:
    """
    Saves parsed JS bridge data directly to the parquet cache file,
    so that data_engine.fetch_ohlcv will resolve it next time.
    """
    try:
        df = parse_psx_timeseries_data(raw_data)
        if df.empty:
            logger.warning(f"[Browser Reader] JS bridge data parsed to empty DataFrame for {symbol}")
            return False
            
        ticker = symbol.upper()
        if not ticker.endswith(".KA"):
            ticker = f"{ticker}.KA"
            
        # Write cache for 2y 1d and 1y 1d to be safe
        for p in ["1y", "2y"]:
            cache_key = f"{ticker}_{p}_1d"
            cache_file = get_cache_path(cache_key)
            df.to_parquet(cache_file)
            logger.info(f"[Browser Reader] Saved JS bridge cache to {cache_file} ({len(df)} rows)")
            
        return True
    except Exception as e:
        logger.error(f"[Browser Reader] Failed to save JS bridge data to cache for {symbol}: {e}")
        return False

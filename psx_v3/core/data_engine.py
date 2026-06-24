"""
data_engine.py — PSX data ingestion via yfinance with local caching.

PSX tickers on Yahoo Finance use the .KA suffix (e.g. SYS.KA, ENGRO.KA).
Some tickers may not be available on yfinance; the engine handles missing data
gracefully and logs failures for review.
"""

import os
import json
import logging
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _psx_ticker(symbol: str) -> str:
    """Convert a bare PSX symbol to Yahoo Finance format."""
    s = symbol.strip().upper()
    if s.startswith("^") or s.endswith(".KA"):
        return s
    return f"{s}.KA"


def _cache_path(key: str) -> Path:
    h = hashlib.md5(key.encode()).hexdigest()[:10]
    return CACHE_DIR / f"{h}.parquet"


def _is_fresh(path: Path, max_age_hours: float = 4.0) -> bool:
    if not path.exists():
        return False
    age = datetime.now().timestamp() - path.stat().st_mtime
    return age < max_age_hours * 3600


# ---------------------------------------------------------------------------
# Core fetch functions
# ---------------------------------------------------------------------------

def fetch_ohlcv(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    force_refresh: bool = False,
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV data for a PSX symbol.

    Args:
        symbol:        e.g. "SYS" or "SYS.KA"
        period:        yfinance period string  ("1d","5d","1mo","3mo","6mo","1y","2y","5y","10y","ytd","max")
        interval:      yfinance interval       ("1m","2m","5m","15m","30m","60m","90m","1h","1d","5d","1wk","1mo","3mo")
        force_refresh: bypass cache

    Returns:
        DataFrame with columns [Open, High, Low, Close, Volume] indexed by datetime,
        or None if data unavailable.
    """
    ticker = _psx_ticker(symbol)
    cache_key = f"{ticker}_{period}_{interval}"
    cache_file = _cache_path(cache_key)

    # Return cached data if fresh enough
    max_age = 0.25 if interval in ("1m", "2m", "5m", "15m") else 4.0
    if not force_refresh and _is_fresh(cache_file, max_age_hours=max_age):
        try:
            return pd.read_parquet(cache_file)
        except Exception:
            pass

    df = pd.DataFrame()
    yf_success = False
    try:
        ticker_obj = yf.Ticker(ticker)
        df = ticker_obj.history(period=period, interval=interval, auto_adjust=True)
        if not df.empty:
            yf_success = True
    except Exception as e:
        logger.warning(f"yfinance failed for {ticker}: {e}")

    if not yf_success or df.empty:
        logger.info(f"yfinance data unavailable for {ticker}. Trying browser fallback...")
        try:
            from core.browser_psx_reader import fetch_data_via_browser
            df = fetch_data_via_browser(symbol, period=period)
        except Exception as e:
            logger.error(f"Browser fallback failed to run for {symbol}: {e}")
            df = pd.DataFrame()

    if df.empty:
        logger.warning(f"No data returned for {ticker} ({period}/{interval}) from both yfinance and browser.")
        return None

    try:
        # Clean up index to be datetime with Asia/Karachi timezone
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert("Asia/Karachi")
        else:
            df.index = df.index.tz_convert("Asia/Karachi")
    except Exception as e:
        logger.warning(f"Timezone conversion failed for {ticker}: {e}")

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df = df[df["Volume"] >= 0]

    if df.empty:
        return None

    df.to_parquet(cache_file)
    logger.info(f"Fetched and cached {len(df)} rows for {ticker} ({period}/{interval})")
    return df


def fetch_multi_timeframe(symbol: str) -> dict[str, Optional[pd.DataFrame]]:
    """
    Fetch multiple timeframes at once for comprehensive technical analysis.
    Returns dict with keys: '1m', '15m', '1h', '1d', '1wk'
    """
    frames = {
        "1m":  ("5d",  "1m"),
        "15m": ("1mo", "15m"),
        "1h":  ("3mo", "60m"),
        "1d":  ("2y",  "1d"),
        "1wk": ("5y",  "1wk"),
    }
    result = {}
    for key, (period, interval) in frames.items():
        result[key] = fetch_ohlcv(symbol, period=period, interval=interval)
    return result


def fetch_fundamentals(symbol: str) -> dict:
    """
    Fetch fundamental data for Shariah screening.
    Returns a dict with balance sheet ratios or empty dict on failure.
    """
    ticker = _psx_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        # Balance sheet
        bs = t.balance_sheet
        income = t.income_stmt

        result = {
            "symbol": symbol,
            "company_name": info.get("longName", symbol),
            "sector": info.get("sector", "Unknown"),
            "industry": info.get("industry", "Unknown"),
            "market_cap": info.get("marketCap"),
            "total_assets": None,
            "total_debt": None,
            "total_equity": None,
            "total_revenue": None,
            "info_raw": {k: v for k, v in info.items() if isinstance(v, (str, int, float, bool))},
        }

        # Try to extract from balance sheet
        if bs is not None and not bs.empty:
            row_map = {r.lower(): r for r in bs.index}
            def _bs(key):
                r = row_map.get(key)
                if r and not bs.loc[r].empty:
                    return float(bs.loc[r].iloc[0])
                return None

            result["total_assets"]  = _bs("total assets")
            result["total_debt"]    = _bs("total debt") or _bs("long term debt")
            result["total_equity"]  = _bs("stockholders equity") or _bs("total equity gross minority interest")

        if income is not None and not income.empty:
            row_map_inc = {r.lower(): r for r in income.index}
            def _inc(key):
                r = row_map_inc.get(key)
                if r and not income.loc[r].empty:
                    return float(income.loc[r].iloc[0])
                return None
            result["total_revenue"] = _inc("total revenue")

        return result

    except Exception as e:
        logger.warning(f"Fundamentals fetch failed for {symbol}: {e}")
        return {"symbol": symbol, "company_name": symbol, "sector": "Unknown", "industry": "Unknown"}


def batch_fetch_returns(symbols: list[str]) -> pd.DataFrame:
    """
    Fetch 1-year daily closes for a list of symbols and compute
    1M / 3M / 6M / 12M returns for momentum scoring.
    Returns a DataFrame indexed by symbol.
    """
    records = []
    today = datetime.now()

    for sym in symbols:
        df = fetch_ohlcv(sym, period="2y", interval="1d")
        if df is None or len(df) < 20:
            logger.warning(f"Skipping {sym}: insufficient data")
            continue

        closes = df["Close"]
        now_price = closes.iloc[-1]

        def _ret(days):
            cutoff = today - timedelta(days=days)
            past = closes[closes.index.date <= cutoff.date()] if hasattr(closes.index[0], 'date') else closes
            try:
                past_price = past.iloc[-1] if not past.empty else closes.iloc[0]
            except Exception:
                past_price = closes.iloc[0]
            return (now_price - past_price) / past_price * 100 if past_price else None

        records.append({
            "symbol":      sym,
            "price":       round(now_price, 2),
            "return_1m":   _ret(30),
            "return_3m":   _ret(90),
            "return_6m":   _ret(180),
            "return_12m":  _ret(365),
            "volume_avg":  round(df["Volume"].tail(20).mean(), 0),
        })

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records).set_index("symbol")


def get_latest_price(symbol: str) -> Optional[float]:
    """Quick fetch of latest closing price."""
    df = fetch_ohlcv(symbol, period="5d", interval="1d")
    if df is not None and not df.empty:
        return float(df["Close"].iloc[-1])
    return None


def fetch_capitalstake_tickers() -> list[str]:
    """
    Fetch all active tickers from Capital Stake API endpoint /3.0/market/tickers.
    Falls back to KMI_ALL_SHARE index constituents on any failure or if API key is not set.
    """
    api_key = os.getenv("CAPITALSTAKE_API_KEY", "")
    from core.kmi_data import KMI_ALL_SHARE
    
    url = "https://csapis.com/3.0/market/tickers"
    headers = {}
    if api_key and api_key != "your_capitalstake_key_here":
        headers["Authorization"] = f"Bearer {api_key}"
        
    try:
        logger.info("Fetching tickers from Capital Stake API...")
        import requests
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            tickers_list = []
            
            # Capital Stake API can return a list of dicts, or {"data": [...]}, or {"tickers": [...]}
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict) and "data" in data:
                items = data["data"]
            elif isinstance(data, dict) and "tickers" in data:
                items = data["tickers"]
            else:
                items = []
                
            for item in items:
                ticker = None
                if isinstance(item, str):
                    ticker = item
                elif isinstance(item, dict):
                    ticker = item.get("ticker") or item.get("symbol")
                if ticker:
                    # Clean and standardize ticker (remove KA if any, remove indices)
                    ticker_clean = ticker.split(".")[0].strip().upper()
                    # Skip indices (which might start with ^)
                    if not ticker_clean.startswith("^") and ticker_clean != "KSE100":
                        tickers_list.append(ticker_clean)
            if tickers_list:
                tickers_unique = sorted(list(set(tickers_list)))
                logger.info(f"Successfully fetched {len(tickers_unique)} tickers from Capital Stake.")
                return tickers_unique
            else:
                logger.warning("Capital Stake API returned empty tickers list.")
        else:
            logger.warning(f"Capital Stake API returned code {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Capital Stake API fetch failed: {e}. Falling back to default watchlist.")
        
    return KMI_ALL_SHARE


def get_market_status() -> dict:
    """
    Check if the Pakistan Stock Exchange (PSX) is currently open or closed.
    Trading hours: Monday-Friday, 09:30 AM to 03:30 PM PKT (UTC+5).
    """
    # Pakistan Time is UTC + 5
    from datetime import timezone
    pkt_now = datetime.now(timezone.utc) + timedelta(hours=5)
    
    # Check day of week (0 = Monday, 6 = Sunday)
    weekday = pkt_now.weekday()
    is_weekend = weekday >= 5
    
    # Trading hours: 09:30 to 15:30
    current_minutes = pkt_now.hour * 60 + pkt_now.minute
    open_minutes = 9 * 60 + 30
    close_minutes = 15 * 60 + 30
    
    is_trading_hours = open_minutes <= current_minutes <= close_minutes
    
    if is_weekend:
        return {
            "status": "CLOSED",
            "reason": "Weekend (Saturday/Sunday)",
            "pkt_time": pkt_now.strftime("%I:%M %p PKT"),
            "date": pkt_now.strftime("%Y-%m-%d"),
        }
    elif not is_trading_hours:
        if current_minutes < open_minutes:
            reason = "Before Market Hours (Opens at 09:30 AM PKT)"
        else:
            reason = "After Hours (Closed at 03:30 PM PKT)"
        return {
            "status": "CLOSED",
            "reason": reason,
            "pkt_time": pkt_now.strftime("%I:%M %p PKT"),
            "date": pkt_now.strftime("%Y-%m-%d"),
        }
    else:
        return {
            "status": "OPEN",
            "reason": "Market is trading live",
            "pkt_time": pkt_now.strftime("%I:%M %p PKT"),
            "date": pkt_now.strftime("%Y-%m-%d"),
        }

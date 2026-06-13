"""
core/market_snapshot_builder.py — Market Snapshot Builder
Builds a strict JSON-compliant snapshot of the market data for the given symbol.
"""
import json
import logging
from datetime import datetime
from typing import Optional

from core.data_engine import fetch_ohlcv
from core.psx_intraday import get_latest_intraday_summary # NEW: Import intraday summary
from data.clean_market_data import compute_indicators
import pandas as pd
from datetime import timezone, timedelta

logger = logging.getLogger(__name__)

def build_snapshot(symbol: str) -> Optional[dict]:
    """
    Fetches raw market data, computes indicators deterministically,
    and returns a strict dictionary matching market_schema.json.
    """
    df = fetch_ohlcv(symbol, period="1y", interval="1d")

    if df is None or len(df) < 20:
        logger.warning(f"Not enough data to build snapshot for {symbol}")
        return None

    # NEW: Overlay real-time intraday data before computing indicators
    realtime = get_latest_intraday_summary(symbol)
    if realtime:
        pkt_tz = timezone(timedelta(hours=5))
        today_pkt = datetime.now(pkt_tz).date()
        
        # Check if today's date already exists in the daily DataFrame
        matching_indices = [i for i, d in enumerate(df.index.date) if d == today_pkt]
        if matching_indices:
            idx = df.index[matching_indices[0]]
            df.loc[idx, 'Close'] = realtime['price']
            df.loc[idx, 'High'] = max(df.loc[idx, 'High'], realtime['price'])
            df.loc[idx, 'Low'] = min(df.loc[idx, 'Low'], realtime['price'])
            df.loc[idx, 'Volume'] = realtime['volume']
            logger.info(f"Updated today's row in DataFrame for {symbol} with real-time Close: {realtime['price']}")
        else:
            # Append new row
            new_timestamp = pd.Timestamp(datetime.now(pkt_tz))
            new_row = pd.DataFrame([{
                'Open': realtime['price'],
                'High': realtime['price'],
                'Low': realtime['price'],
                'Close': realtime['price'],
                'Volume': realtime['volume']
            }], index=[new_timestamp])
            df = pd.concat([df, new_row])
            logger.info(f"Appended new real-time row to DataFrame for {symbol} Close: {realtime['price']}")

    indicators = compute_indicators(df)
    if not indicators:
        return None

    snapshot = {
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
        **indicators
    }

    # Optional: schema validation here if needed
    # For now, we assume compute_indicators provides all required keys.
    required_keys = [
        "symbol", "timestamp", "price", "open", "prev_close", 
        "volume", "avg_volume_20d", "rsi", "macd", "macd_signal", 
        "return_1d", "return_7d", "volatility", "vol_percentile_20d", 
        "ma_20", "low_52w", "high_52w"
    ]

    for key in required_keys:
        if key not in snapshot:
            logger.error(f"Snapshot missing required key: {key}")
            return None

    return snapshot

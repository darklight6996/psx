"""
core/selective_ml.py — Phase 2 Selective ML.

Instead of running ML inference inline during the standard pipeline for every stock,
this module allows running ML specifically on a subset of stocks.
Uses ThreadPoolExecutor for parallel execution of the ML pipeline.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from core.ml_engine import predict as ml_predict
from core.data_engine import fetch_ohlcv

logger = logging.getLogger("selective_ml")

def run_ml_on_stocks(symbols: list[str]) -> dict:
    """
    Runs ML prediction on the selected stocks in parallel.
    Returns a dictionary of symbol -> ml_prediction_result.
    """
    results = {}
    
    def process_stock(sym):
        try:
            df = fetch_ohlcv(sym, period="2y", interval="1d", force_refresh=False)
            if df is None or len(df) < 200:
                return sym, {"status": "insufficient_data", "direction": "NOT_UP"}
            
            price_now = float(df["Close"].iloc[-1])
            # simple RSI approximation for the snapshot required by predict
            rsi_val = float(df["Close"].pct_change().rolling(14).mean().iloc[-1] * 100) if len(df) >= 14 else 50.0
            
            snapshot = {
                "price": price_now,
                "rsi": rsi_val,
                "volume": float(df["Volume"].iloc[-1])
            }
            res = ml_predict(sym, snapshot, df)
            return sym, res
        except Exception as e:
            logger.error(f"[Selective ML] Failed on {sym}: {e}")
            return sym, {"status": "error", "error": str(e)}

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_sym = {executor.submit(process_stock, sym): sym for sym in symbols}
        for future in as_completed(future_to_sym):
            sym = future_to_sym[future]
            try:
                data = future.result()
                results[sym] = data[1]
            except Exception as exc:
                logger.error(f"[Selective ML] {sym} generated an exception: {exc}")
                results[sym] = {"status": "error", "error": str(exc)}
                
    return results

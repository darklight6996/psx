import os
import sys
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.data_engine import fetch_capitalstake_tickers, fetch_ohlcv
from core.ml_engine import train_pooled_model, MODELS_DIR

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("train_ml")

def download_data(symbol: str):
    logger.info(f"Downloading data for {symbol}...")
    try:
        # We need historical data for ML training (at least 200 rows)
        # Using 2y interval=1d
        df = fetch_ohlcv(symbol, period="2y", interval="1d", force_refresh=True)
        if df is not None and not df.empty and len(df) >= 200:
            return symbol, df
        else:
            logger.warning(f"Not enough data for {symbol}: {len(df) if df is not None else 0} rows")
            return symbol, None
    except Exception as e:
        logger.error(f"Error downloading {symbol}: {e}")
        return symbol, None

def main():
    logger.info("--- Starting ML Pooled Model Training ---")
    
    # 1. Fetch liquid tickers
    tickers = fetch_capitalstake_tickers()
    if not tickers:
        logger.error("No tickers found. Exiting.")
        return
        
    logger.info(f"Fetched {len(tickers)} tickers. Beginning data download...")
    
    dfs = {}
    
    # 2. Parallel data fetching
    # Limit max workers to avoid being rate-limited by Yahoo Finance
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(download_data, tickers)
        for sym, df in results:
            if df is not None:
                dfs[sym] = df
                
    valid_symbols = list(dfs.keys())
    logger.info(f"Downloaded sufficient data for {len(valid_symbols)} / {len(tickers)} symbols.")
    
    if len(valid_symbols) == 0:
        logger.error("No data collected. Exiting.")
        return
        
    # 3. Train pooled model
    logger.info("Training pooled ML model...")
    result = train_pooled_model(valid_symbols, dfs)
    
    if result.get("status") == "trained":
        acc = result.get("rf_cv_accuracy_pct", 0)
        reliable = result.get("ml_signal_reliable", False)
        logger.info(f"Training SUCCESS! Accuracy: {acc}%, Reliable: {reliable}")
        logger.info(f"Model saved to: {MODELS_DIR / 'pooled_rf.joblib'}")
    else:
        logger.error(f"Training failed: {result}")

if __name__ == "__main__":
    main()

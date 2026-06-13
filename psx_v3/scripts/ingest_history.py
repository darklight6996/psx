"""
scripts/ingest_history.py — 5-Year Historical Data Ingest Utility
Fetches and caches 5 years of daily historical data for all PSX stocks.
"""

import os
import sys
import logging
from pathlib import Path

# Add root directory to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.kmi_data import KMI_ALL_SHARE, KNOWN_NON_COMPLIANT, ISLAMIC_BANKS
from core.data_engine import fetch_ohlcv

# Configure logging to show progress in stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("ingest_history")

def ingest_all_stocks(period: str = "5y", force_refresh: bool = False):
    symbols = sorted(list(set(KMI_ALL_SHARE + KNOWN_NON_COMPLIANT + ISLAMIC_BANKS)))
    total = len(symbols)
    success_count = 0
    fail_count = 0

    logger.info(f"🚀 Starting 5-year data ingestion for {total} PSX stocks...")
    logger.info(f"Target Cache Directory: {PROJECT_ROOT / 'data' / 'cache'}")

    for idx, sym in enumerate(symbols, 1):
        logger.info(f"[{idx}/{total}] Fetching {sym} ({period} daily data)...")
        try:
            df = fetch_ohlcv(sym, period=period, interval="1d", force_refresh=force_refresh)
            if df is not None and not df.empty:
                logger.info(f"  ✅ Cached {len(df)} days of historical closes for {sym}")
                success_count += 1
            else:
                logger.warning(f"  ⚠️ No data retrieved for {sym}")
                fail_count += 1
        except Exception as e:
            logger.error(f"  ❌ Failed to fetch {sym}: {e}")
            fail_count += 1

    logger.info("=" * 60)
    logger.info(f"🎉 Ingestion Complete!")
    logger.info(f"  Successfully loaded: {success_count} stocks")
    logger.info(f"  Failed / No data:    {fail_count} stocks")
    logger.info("=" * 60)

if __name__ == "__main__":
    force = "--force" in sys.argv
    ingest_all_stocks(force_refresh=force)

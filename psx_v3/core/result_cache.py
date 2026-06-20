"""
core/result_cache.py — Database-to-UI data reconstruction bridge.
Provides methods to restore session state values without triggering slow, blocking analysis.

Fix #2: Added JSON flat-file fallback (data/last_results_cache.json) so that on page
refresh the UI always loads the last known good results, even if the DB query fails.
"""

import json
import logging
from pathlib import Path
from typing import Optional
from core.pipeline import load_pipeline_results
from core.portfolio import load_memory

logger = logging.getLogger("result_cache")

# Flat-file fallback path — written after every successful analysis
RESULTS_FLATFILE = Path("data/last_results_cache.json")


def _build_daily_results_from_pipeline(pipeline_results: list) -> dict:
    """Convert a list of pipeline result dicts into the daily_results dict the UI expects."""
    daily_results = {}
    for r in pipeline_results:
        sym = r["symbol"]

        advisory = {
            "rating": r["verdict"],
            "score": r["final_score"],
            "composite": r["final_score"],
            "rationale": r["reasons"]
        }

        daily_results[sym] = {
            "symbol": sym,
            "company_name": r.get("company_name", sym),
            "sector": r.get("sector", "Unknown"),
            "current_price": r["price_at_run"],
            "daily_df": None,
            "hour_df": None,
            "hqm": {"hqm_score": r["final_score"]},
            "technicals": {"signals": r["signals"]},
            "regime": r["regime"],
            "shariah": r["shariah_report"],
            "advisory": advisory,
            "stop_check": None,
            "ml_signals": r["ml_signals"],
            "fundamentals": r["fundamentals"],
            "date": r.get("date", ""),
            "confidence": r["confidence"],
            "confidence_label": r["confidence_label"],
            "horizon": r["horizon"],
            "council_run": r["council_run"],
            "council_result": r["council_result"]
        }
    return daily_results


def save_results_to_flatfile(daily_results: dict):
    """
    Persist the daily_results dict to a JSON flat file as a cache fallback.
    Called after every successful analysis run. Skips un-serialisable keys (DataFrames).
    """
    RESULTS_FLATFILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        serialisable = {}
        for sym, r in daily_results.items():
            serialisable[sym] = {k: v for k, v in r.items() if k not in ("daily_df", "hour_df")}
        with open(RESULTS_FLATFILE, "w") as f:
            json.dump(serialisable, f, indent=2, default=str)
        logger.info(f"Saved {len(serialisable)} results to flat-file cache: {RESULTS_FLATFILE}")
    except Exception as e:
        logger.warning(f"Could not save results to flat-file cache: {e}")


def _load_from_flatfile() -> dict:
    """Load the last known good results from the flat-file fallback."""
    if not RESULTS_FLATFILE.exists():
        return {}
    try:
        with open(RESULTS_FLATFILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            logger.info(f"Loaded {len(data)} results from flat-file cache (DB fallback).")
            return data
    except Exception as e:
        logger.warning(f"Failed to load flat-file cache: {e}")
    return {}


def load_latest_results() -> dict:
    """
    Read the latest pipeline results from SQLite and reconstruct the full backward-compatible
    daily_results dictionary structure expected by all Streamlit UI tabs.

    Falls back to the flat-file JSON cache (data/last_results_cache.json) if the DB
    returns empty or raises an error.
    """
    # --- Primary: SQLite DB ---
    try:
        pipeline_results = load_pipeline_results(None)
        if pipeline_results:
            daily_results = _build_daily_results_from_pipeline(pipeline_results)
            logger.info(f"Loaded {len(daily_results)} results from SQLite DB.")
            # Keep the flat-file in sync with the DB
            save_results_to_flatfile(daily_results)
            return daily_results
        else:
            logger.warning("SQLite DB returned 0 pipeline results. Trying flat-file fallback...")
    except Exception as e:
        logger.error(f"Failed to load latest pipeline results from DB: {e}. Trying flat-file fallback...")

    # --- Fallback: flat-file JSON cache ---
    return _load_from_flatfile()


def load_latest_macro() -> dict:
    """
    Reads the most recent macro sentiment dictionary from data/macro_cache.json.
    Falls back to a default neutral state if the cache is missing or corrupt.
    """
    cache_file = Path("data/macro_cache.json")
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read macro_cache.json: {e}")

    return {
        "sentiment": "neutral",
        "score": 0.0,
        "summary": "Run daily analysis to fetch macro sentiment.",
        "headlines": []
    }


def load_latest_accuracy() -> dict:
    """
    Retrieves the prediction accuracy stats from the local JSON memory file (data/memory_store.json)
    without running a slow yfinance prediction audit.
    """
    try:
        memory = load_memory()
        acc = memory.get("prediction_accuracy", {})
        total = acc.get("total", 0)
        hits = acc.get("hits", 0)
        misses = acc.get("misses", 0)
        hit_rate = (hits / total * 100) if total > 0 else 0.0

        return {
            "total_checked": total,
            "hits": hits,
            "misses": misses,
            "hit_rate_pct": round(hit_rate, 1),
            "confusion_matrix": {
                "buy_hits": acc.get("buy_hits", 0),
                "buy_misses": acc.get("buy_misses", 0),
                "sell_hits": acc.get("sell_hits", 0),
                "sell_misses": acc.get("sell_misses", 0),
                "hold_hits": acc.get("hold_hits", 0),
                "hold_misses": acc.get("hold_misses", 0),
            }
        }
    except Exception as e:
        logger.error(f"Failed to load prediction accuracy stats: {e}")
        return {"total_checked": 0, "hits": 0, "misses": 0, "hit_rate_pct": 0.0}


def get_alerts_from_results(results: dict) -> list:
    """
    Derives alerts from the loaded daily results dict.
    Matches the logic inside agent.py.
    """
    alerts = []
    for sym, r in results.items():
        if "error" in r:
            continue
        # Check advisory rating
        rating = r.get("advisory", {}).get("rating")
        if rating == "SELL":
            rationale = r.get("advisory", {}).get("rationale", [])
            alerts.append({
                "type": "SELL",
                "symbol": sym,
                "reason": "; ".join(rationale) if isinstance(rationale, list) else str(rationale)
            })
        # Check Shariah risk flags
        shariah = r.get("shariah", {})
        if shariah.get("risk_flag"):
            alerts.append({
                "type": "SHARIAH_RISK",
                "symbol": sym,
                "reason": shariah["risk_flag"]
            })
    return alerts

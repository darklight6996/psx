"""
agent.py — Main PSX Advisory Agent orchestrator.

DEPRECATED / REDIRECTED: Core logic is migrated to core/pipeline.py.
This file routes all requests to core/pipeline.py for backward compatibility with UI/CLI.
"""

import logging
import os
from datetime import date
from typing import Optional
from pathlib import Path

# Configure logging
Path("data").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("data/agent.log", mode="a"),
    ],
    force=True,
)
logger = logging.getLogger("psx_agent")

from core.data_engine      import fetch_ohlcv, fetch_fundamentals, batch_fetch_returns, get_latest_price
from core.shariah_engine   import screen_stock
from core.macro_sentiment  import get_macro_sentiment
from core.portfolio        import (
    load_portfolio, get_positions, get_total_capital,
    portfolio_summary, save_daily_snapshot,
    get_yesterday_snapshot, evaluate_predictions,
)
from core.kmi_data import KMI_ALL_SHARE, DEFAULT_WATCHLIST


def analyse_stock(
    symbol: str,
    universe_df=None,
    macro_sentiment: str = "neutral",
    force_refresh: bool = False,
    run_ml: bool = False,
) -> dict:
    """
    Deprecated: Main analysis is handled via core.pipeline.run_pipeline_for_stock.
    Routes to pipeline for backward compatibility.
    """
    from core.pipeline import run_pipeline_for_stock
    from core.data_engine import fetch_ohlcv, fetch_fundamentals
    
    sym = symbol.upper()
    daily_df = fetch_ohlcv(sym, period="2y", interval="1d", force_refresh=force_refresh)
    
    if daily_df is None or daily_df.empty:
        return {
            "symbol": sym,
            "error": f"No price data available for {sym}."
        }
        
    pipeline_res = run_pipeline_for_stock(sym, daily_df, run_ml=run_ml)
    fundamentals = fetch_fundamentals(sym)
    
    # Format backward-compatible dictionary
    advisory = {
        "rating": pipeline_res["verdict"],
        "score": pipeline_res["final_score"],
        "composite": pipeline_res["final_score"],
        "rationale": pipeline_res["reasons"]
    }
    
    return {
        "symbol": sym,
        "company_name": fundamentals.get("company_name", sym),
        "sector": fundamentals.get("sector", "Unknown"),
        "current_price": pipeline_res["price_at_run"],
        "daily_df": daily_df,
        "hqm": {"hqm_score": pipeline_res["final_score"]},
        "technicals": {"signals": pipeline_res["signals"]},
        "regime": pipeline_res["regime"],
        "shariah": pipeline_res["shariah_report"],
        "advisory": advisory,
        "stop_check": None,
        "ml_signals": pipeline_res["ml_signals"],
        "fundamentals": {k: v for k, v in fundamentals.items() if k not in ("info_raw",)},
        "date": date.today().isoformat(),
        "confidence": pipeline_res["confidence"],
        "confidence_label": pipeline_res["confidence_label"],
        "horizon": pipeline_res["horizon"],
        "council_run": pipeline_res["council_run"],
        "council_result": pipeline_res["council_result"],
        "news": pipeline_res.get("news", {"verified_facts": [], "retail_sentiment": [], "discarded_noise": []})
    }

def _pipeline_result_to_advisory_dict(db_row: dict) -> dict:
    """Helper to deserialize a pipeline_results DB row into the large UI dictionary format."""
    import json
    sym = db_row["symbol"]
    try:
        shariah_report = json.loads(db_row["shariah_report"])
    except Exception:
        shariah_report = {"overall_status": "UNKNOWN", "risk_flag": None}
    
    try:
        ml_signals = json.loads(db_row.get("ml_signals", "{}") or "{}")
    except Exception:
        ml_signals = {}
        
    try:
        signals = json.loads(db_row.get("signals", "{}") or "{}")
    except Exception:
        signals = {}
        
    try:
        reasons = json.loads(db_row.get("reasons", "[]") or "[]")
    except Exception:
        reasons = []
        
    advisory = {
        "rating": db_row["verdict"],
        "score": db_row["final_score"],
        "composite": db_row["final_score"],
        "rationale": reasons
    }
    
    return {
        "symbol": sym,
        "company_name": sym,
        "sector": "Unknown",
        "current_price": db_row["price_at_run"],
        "daily_df": None,
        "hour_df": None,
        "hqm": {"hqm_score": db_row["final_score"]},
        "technicals": {"signals": signals},
        "regime": db_row.get("market_regime", "Unknown"),
        "shariah": shariah_report,
        "advisory": advisory,
        "stop_check": None,
        "ml_signals": ml_signals,
        "fundamentals": {},
        "date": db_row["run_date"],
        "confidence": db_row.get("confidence_score", 0.0),
        "confidence_label": "N/A",
        "horizon": "N/A",
        "council_run": False,
        "council_result": {}
    }

def run_price_refresh(symbols: list[str], results_dict: dict) -> dict:
    """
    Fetches ONLY live prices/status via psx_live.py, updating the in-memory results dictionary
    without re-running the ML or scraping yahoo history. Extremely fast.
    """
    from core.psx_live import get_live_quotes_batch, get_market_status
    
    logger.info(f"Running fast price refresh for {len(symbols)} symbols...")
    live_data = get_live_quotes_batch(symbols)
    mkt_status = get_market_status()
    
    for sym in symbols:
        if sym in live_data and live_data[sym]["last_price"] is not None:
            if sym in results_dict:
                results_dict[sym]["current_price"] = live_data[sym]["last_price"]
                # Optional: update advisory logic slightly if price hits stop loss, etc.
    
    return {
        "market_status": mkt_status,
        "results": results_dict
    }




def run_daily_analysis(
    watchlist:     Optional[list[str]] = None,
    force_refresh: bool = False,
    include_portfolio: bool = True,
) -> dict:
    """
    Deprecated: Runs daily analysis by looping watchlist through the unified 3-tiered pipeline.
    """
    logger.info("=" * 60)
    logger.info(f"PSX Advisory Agent (Pipeline Route) — Daily Run: {date.today()}")
    logger.info("=" * 60)

    try:
        from core.background_worker import update_status
    except ImportError:
        update_status = None

    symbols = list(set((watchlist or DEFAULT_WATCHLIST) + (
        list(get_positions().keys()) if include_portfolio else []
    )))

    # Step 1: Accuracy evaluation
    if update_status:
        update_status(progress="Evaluating predictions...")
    logger.info("Evaluating yesterday's predictions...")
    current_prices_quick = {}
    for sym in symbols:
        p = get_latest_price(sym)
        if p:
            current_prices_quick[sym] = p

    accuracy = evaluate_predictions(current_prices_quick)
    logger.info(f"Accuracy: {accuracy['hit_rate_pct']}% ({accuracy['hits']}/{accuracy['total_checked']})")

    try:
        from advisor_memory import evaluate_advisor_conversations
        from advisor_engine import write_lesson
        adv_eval = evaluate_advisor_conversations(
            price_getter=get_latest_price,
            lesson_writer=write_lesson,
            lookback_days=5,
        )
        if adv_eval["evaluated"] > 0:
            logger.info(f"Advisor evaluation: {adv_eval['evaluated']} conversations evaluated, {adv_eval['lessons_written']} lessons written.")
    except Exception as e:
        logger.warning(f"Advisor conversation evaluation failed (non-fatal): {e}")

    # Evaluate individual analyst predictions and update weights
    try:
        from memory.analyst_tracker import evaluate_analyst_predictions
        evaluate_analyst_predictions(current_prices_quick)
    except Exception as e:
        logger.error(f"Failed to evaluate individual analyst predictions: {e}")

    # Step 2: Macro sentiment
    if update_status:
        update_status(progress="Fetching macro sentiment...")
    logger.info("Fetching macro sentiment...")
    macro = get_macro_sentiment()
    logger.info(f"Macro: {macro['sentiment']} (score: {macro['score']})")

    # Cache macro sentiment to disk
    try:
        import json
        from pathlib import Path
        Path("data").mkdir(exist_ok=True)
        with open("data/macro_cache.json", "w") as f:
            json.dump(macro, f, indent=4)
        logger.info("Cached macro sentiment to data/macro_cache.json")
    except Exception as e:
        logger.warning(f"Failed to cache macro sentiment: {e}")

    # Step 3: Ensure ML pooled model exists
    if update_status:
        update_status(progress="Ensuring ML pooled features exist...")
    logger.info("Ensuring ML pooled model exists...")

    try:
        from core.ml_engine import ensure_pooled_model_exists
        ensure_pooled_model_exists(symbols)
    except Exception as err:
        logger.error(f"Failed to train pooled model: {err}")

    # Step 4: Run pipeline for each stock in parallel
    results = {}
    total_syms = len(symbols)
    completed = 0
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    progress_lock = threading.Lock()

    def _worker(sym):
        nonlocal completed
        try:
            res = analyse_stock(sym, force_refresh=force_refresh)
        except Exception as e:
            logger.error(f"Analysis failed for {sym}: {e}")
            res = {"symbol": sym, "error": str(e)}
        
        with progress_lock:
            completed += 1
            if update_status:
                update_status(progress=f"Analysing stocks ({completed}/{total_syms}): {sym}...")
        return sym, res

    logger.info(f"Starting parallel analysis of {total_syms} stocks with 8 worker threads...")
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_worker, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym, res = future.result()
            results[sym] = res

    # Step 5: Save snapshot
    if update_status:
        update_status(progress="Finalizing summary...")
    snapshot = {}
    for sym, r in results.items():
        if "error" not in r:
            snapshot[sym] = {
                "rating": r["advisory"]["rating"],
                "score":  r["advisory"]["score"],
                "price":  r["current_price"],
                "hqm":    r["advisory"]["score"],
            }

    save_daily_snapshot(snapshot)
    logger.info(f"Snapshot saved: {len(snapshot)} stocks")

    # Step 6: Portfolio summary
    port_summary = portfolio_summary(current_prices_quick) if include_portfolio else {}

    # Alerts
    alerts = []
    for sym, r in results.items():
        if "error" in r:
            continue
        if r["advisory"]["rating"] == "SELL":
            alerts.append({"type": "SELL", "symbol": sym, "reason": "; ".join(r["advisory"]["rationale"])})
        if r.get("shariah", {}).get("risk_flag"):
            alerts.append({"type": "SHARIAH_RISK", "symbol": sym, "reason": r["shariah"]["risk_flag"]})

    logger.info(f"Daily run complete. {len(alerts)} alerts generated.")

    # Persist results to flat-file cache for resilient page-refresh loading (Fix #2)
    try:
        from core.result_cache import save_results_to_flatfile
        save_results_to_flatfile(results)
        logger.info("Flat-file results cache updated after daily run.")
    except Exception as _cache_err:
        logger.warning(f"Failed to update flat-file cache (non-fatal): {_cache_err}")

    return {
        "date":          date.today().isoformat(),
        "results":       results,
        "macro":         macro,
        "accuracy":      accuracy,
        "portfolio":     port_summary,
        "alerts":        alerts,
        "symbols":       symbols,
        "universe_hqm":  {},
    }


if __name__ == "__main__":
    import json, sys
    symbols = sys.argv[1:] if len(sys.argv) > 1 else None
    output  = run_daily_analysis(watchlist=symbols)

    # Print summary table
    print("\n" + "=" * 70)
    print(f"{'SYMBOL':<10} {'RATING':<8} {'SCORE':<8} {'SHARIAH':<15} {'PRICE (PKR)'}")
    print("-" * 70)
    for sym, r in output["results"].items():
        if "error" in r:
            print(f"{sym:<10} ERROR: {r['error'][:50]}")
            continue
        shariah = r["shariah"]["overall_status"]
        print(f"{sym:<10} {r['advisory']['rating']:<8} {r['advisory']['score']:<8.1f} "
              f"{shariah:<15} {r['current_price']:.2f}")

    print(f"\nMacro: {output['macro']['sentiment'].upper()}")
    print(f"Prediction accuracy: {output['accuracy']['hit_rate_pct']}%")

    if output["alerts"]:
        print("\n[!] ALERTS:")
        for a in output["alerts"]:
            print(f"  [{a['type']}] {a['symbol']}: {a['reason']}")

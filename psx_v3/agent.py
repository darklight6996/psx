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
) -> dict:
    """
    Deprecated: Main analysis is handled via core.pipeline.run_pipeline_for_stock.
    Routes to pipeline for backward compatibility.
    """
    from core.pipeline import run_pipeline_for_stock
    from core.data_engine import fetch_ohlcv, fetch_fundamentals
    
    sym = symbol.upper()
    daily_df = fetch_ohlcv(sym, period="2y", interval="1d", force_refresh=force_refresh)
    hour_df  = fetch_ohlcv(sym, period="3mo", interval="60m", force_refresh=force_refresh)
    
    if daily_df is None or daily_df.empty:
        return {
            "symbol": sym,
            "error": f"No price data available for {sym}."
        }
        
    pipeline_res = run_pipeline_for_stock(sym, daily_df)
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
        "hour_df": hour_df,
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
        "council_result": pipeline_res["council_result"]
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

    symbols = list(set((watchlist or DEFAULT_WATCHLIST) + (
        list(get_positions().keys()) if include_portfolio else []
    )))

    # Step 1: Accuracy evaluation
    logger.info("Evaluating yesterday's predictions...")
    current_prices_quick = {}
    for sym in symbols:
        p = get_latest_price(sym)
        if p:
            current_prices_quick[sym] = p

    accuracy = evaluate_predictions(current_prices_quick)
    logger.info(f"Accuracy: {accuracy['hit_rate_pct']}% ({accuracy['hits']}/{accuracy['total_checked']})")

    # Evaluate individual analyst predictions and update weights
    try:
        from memory.analyst_tracker import evaluate_analyst_predictions
        evaluate_analyst_predictions(current_prices_quick)
    except Exception as e:
        logger.error(f"Failed to evaluate individual analyst predictions: {e}")

    # Step 2: Macro sentiment
    logger.info("Fetching macro sentiment...")
    macro = get_macro_sentiment()
    logger.info(f"Macro: {macro['sentiment']} (score: {macro['score']})")

    # Step 3: Ensure ML pooled model exists
    logger.info("Ensuring ML pooled model exists...")
    dfs = {}
    for sym in symbols:
        try:
            df = fetch_ohlcv(sym, period="2y", interval="1d", force_refresh=force_refresh)
            if df is not None and not df.empty:
                dfs[sym] = df
        except Exception as e:
            logger.warning(f"Failed to fetch daily EOD data for {sym} to build pooled features: {e}")

    try:
        from core.ml_engine import ensure_pooled_model_exists
        ensure_pooled_model_exists(symbols, dfs)
    except Exception as err:
        logger.error(f"Failed to train pooled model: {err}")

    # Step 4: Run pipeline for each stock
    results = {}
    for sym in symbols:
        try:
            results[sym] = analyse_stock(sym, force_refresh=force_refresh)
        except Exception as e:
            logger.error(f"Analysis failed for {sym}: {e}")
            results[sym] = {"symbol": sym, "error": str(e)}

    # Step 5: Save snapshot
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
        if r["shariah"]["risk_flag"]:
            alerts.append({"type": "SHARIAH_RISK", "symbol": sym, "reason": r["shariah"]["risk_flag"]})

    logger.info(f"Daily run complete. {len(alerts)} alerts generated.")

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

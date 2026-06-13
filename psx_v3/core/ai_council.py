"""
core/ai_council.py — AI Council Integration (with ML Layer)
"""

import json
import logging
from core.market_snapshot_builder import build_snapshot
from core.data_engine import fetch_ohlcv
from core.rule_engine import compute_quant_score, compute_bull_score, compute_bear_score, compute_risk_score, compute_final_score, get_decision
from core.shariah_engine import screen_stock
from council.ollama_council import run_ai_council
from memory.analyst_tracker import get_analyst_weights
from core.psx_scrapers import fetch_psx_announcements, fetch_forum_discussions
from core.macro_sentiment import fetch_company_news
from core.news_filter import filter_and_format_news, format_filtered_news_to_markdown
from core.ml_engine import predict as ml_predict

logger = logging.getLogger(__name__)


def _format_ml_block(ml: dict) -> str:
    """Format ML predictions as a clean text block for LLM prompts."""
    if not ml or ml.get("status") == "error" or not ml.get("ml_signal_reliable", False) or ml.get("signal") == "INSUFFICIENT_DATA":
        return "ML PREDICTIONS: Insufficient data or below-threshold accuracy — analysts should rely on technical indicators only."

    direction = ml.get("direction", "SIDEWAYS")
    conf = ml.get("confidence_pct", 0)
    move = ml.get("expected_move_pct", 0)
    strength = ml.get("signal_strength", "WEAK")
    accuracy = ml.get("model_accuracy_pct", 0)
    mae = ml.get("xgb_cv_mae_pct", 0)

    proba = ml.get("direction_proba", {})
    proba_str = " | ".join(f"{k}: {v*100:.0f}%" for k, v in sorted(proba.items()))

    top_feats = ml.get("top_features", {})
    feats_str = ", ".join(f"{k} ({v:.2f})" for k, v in list(top_feats.items())[:3])

    sign = "+" if move >= 0 else ""
    return (
        f"ML SIGNALS (trained on {ml.get('training_rows', 0)} days of PSX data):\n"
        f"  - Random Forest Direction: {direction} (confidence: {conf}%) [{strength} signal]\n"
        f"  - Direction probabilities: {proba_str}\n"
        f"  - XGBoost Expected Move:   {sign}{move}%\n"
        f"  - Model CV accuracy:       {accuracy}% | MAE: {mae}%\n"
        f"  - Key predictors:          {feats_str}"
    )


def run_council(symbol: str, analysis_data: dict, macro_sentiment: str = "neutral", progress_callback=None) -> dict:
    """
    Main entry point for the AI Council.

    Step 0: ML predictions (RF direction + XGBoost magnitude)
    Step 1: Build real-time market snapshot
    Step 2: Scrape news/announcements/forums
    Step 3: Apply strict news filtering heuristics
    Step 4: Deterministic rule-engine baseline scores
    Step 5: Deterministic Shariah screening
    Step 6: Construct independent analyst inputs (injecting ML signals)
    Step 7: Convene AI Board Room debate
    """
    total_steps = 7

    # ── Step 0: ML Predictions ────────────────────────────────────────────────
    if progress_callback: progress_callback(0, total_steps, "Running ML models (RF + XGBoost)...")
    daily_df = fetch_ohlcv(symbol, period="2y", interval="1d")
    ml_signals: dict = {"status": "error", "reason": "No historical data for ML"}
    if daily_df is not None and len(daily_df) >= 80:
        # We need the snapshot first for features — do a quick build now
        from data.clean_market_data import compute_indicators
        quick_snap = compute_indicators(daily_df)
        if quick_snap:
            ml_signals = ml_predict(symbol, quick_snap, daily_df)
    ml_block = _format_ml_block(ml_signals)
    logger.info(f"[ML] {symbol} → {ml_signals.get('direction', 'N/A')} ({ml_signals.get('confidence_pct', 0)}% conf, {ml_signals.get('expected_move_pct', 0):+.1f}% expected move)")

    # ── Step 1: Build real-time snapshot ─────────────────────────────────────
    if progress_callback: progress_callback(1, total_steps, "Building real-time market snapshot...")
    snapshot = build_snapshot(symbol)
    if not snapshot:
        logger.warning(f"Could not build snapshot for {symbol}")
        return {
            "symbol": symbol,
            "council_verdict": "HOLD",
            "council_score": 50.0,
            "scores": {"quant": 50, "bull": 50, "bear": 50, "risk": 50, "final_score": 50, "decision": "HOLD"},
            "snapshot": {},
            "shariah": {"overall_status": "UNKNOWN", "recommendation": "No data for Shariah screen.", "criteria": []},
            "explainer": {"explanation": "Insufficient data.", "key_drivers": [], "risk_factors": []},
            "analyst_verdicts": {},
            "chairman_notes": "Insufficient data to perform full analysis.",
            "ml_signals": ml_signals,
            "error": "Insufficient data to build snapshot.",
        }

    # ── Step 2: Scrape external news ─────────────────────────────────────────
    if progress_callback: progress_callback(2, total_steps, "Scraping news, announcements & forums...")
    company_news   = fetch_company_news(symbol, max_items=5)
    announcements  = fetch_psx_announcements(symbol)
    discussions    = fetch_forum_discussions(symbol)

    # ── Step 3: Apply filtering heuristics ───────────────────────────────────
    if progress_callback: progress_callback(3, total_steps, "Applying credibility & hype filters...")
    all_items = []
    for ns in company_news:
        src = "Bloomberg" if "bloomberg" in ns.lower() else "Reuters"
        all_items.append({"source": src, "content": ns, "sentiment": "neutral"})
    for ann in announcements:
        all_items.append({"source": ann["source"], "content": ann["content"], "sentiment": "neutral"})
    for disc in discussions:
        all_items.append({"source": disc["source"], "user": disc.get("user", "anon"),
                          "content": disc["content"], "sentiment": disc["sentiment"]})
    filtered_res = filter_and_format_news(all_items)
    filtered_news_md = format_filtered_news_to_markdown(filtered_res)

    # ── Step 4: Rule-engine baseline ─────────────────────────────────────────
    if progress_callback: progress_callback(4, total_steps, "Computing deterministic rule-engine scores...")
    q = compute_quant_score(snapshot)
    b = compute_bull_score(snapshot)
    br = compute_bear_score(snapshot)
    r = compute_risk_score(snapshot)
    final_sys = compute_final_score(q, b, br, r)
    sys_dec = get_decision(final_sys)
    deterministic_scores = {"quant": q, "bull": b, "bear": br, "risk": r,
                             "final_score": final_sys, "decision": sys_dec}

    # ── Step 5: Shariah screening ─────────────────────────────────────────────
    if progress_callback: progress_callback(5, total_steps, "Running Shariah screening...")
    sh_obj = screen_stock(symbol, snapshot)
    shariah_verdict = sh_obj.overall_status
    shariah_report  = sh_obj.to_dict()

    # ── Step 6: Independent analyst inputs (ML injected) ─────────────────────
    # Quant Analyst gets BOTH rule scores AND ML predictions (the most data-driven role)
    quant_input = {
        "rsi": snapshot.get("rsi"), "macd": snapshot.get("macd"),
        "macd_signal": snapshot.get("macd_signal"), "ma_20": snapshot.get("ma_20"),
        "return_1d": snapshot.get("return_1d"), "return_7d": snapshot.get("return_7d"),
        "rule_engine_scores": deterministic_scores,
    }

    # Bull Analyst sees price momentum + positive ML signals
    bull_input = {
        "price": snapshot.get("price"), "rsi": snapshot.get("rsi"),
        "return_1d": snapshot.get("return_1d"), "return_7d": snapshot.get("return_7d"),
        "ma_20": snapshot.get("ma_20"), "avg_volume_20d": snapshot.get("avg_volume_20d"),
        "volume": snapshot.get("volume"),
    }

    # Bear Analyst sees downside indicators
    bear_input = {
        "price": snapshot.get("price"), "rsi": snapshot.get("rsi"),
        "macd": snapshot.get("macd"), "macd_signal": snapshot.get("macd_signal"),
        "return_1d": snapshot.get("return_1d"), "volatility": snapshot.get("volatility"),
    }

    # Risk Analyst sees volatility, stop proximity, 52-week range
    risk_input = {
        "price": snapshot.get("price"), "volatility": snapshot.get("volatility"),
        "vol_percentile_20d": snapshot.get("vol_percentile_20d"),
        "low_52w": snapshot.get("low_52w"), "high_52w": snapshot.get("high_52w"),
    }

    # Macro Analyst sees sector sensitivity + filtered macro news
    macro_input = {
        "macro_sentiment": macro_sentiment,
        "sector": snapshot.get("fundamentals", {}).get("sector", "Unknown"),
    }

    analyst_inputs = {
        "Bull Analyst": (
            f"STOCK: {symbol}\n"
            f"BULLISH TECHNICAL DATA:\n{json.dumps(bull_input, indent=2)}\n\n"
            f"{ml_block}\n\n"
            f"FILTERED STOCK FILINGS & DISCUSSIONS:\n{filtered_news_md}"
        ),
        "Bear Analyst": (
            f"STOCK: {symbol}\n"
            f"BEARISH TECHNICAL DATA:\n{json.dumps(bear_input, indent=2)}\n\n"
            f"{ml_block}\n\n"
            f"FILTERED STOCK FILINGS & DISCUSSIONS:\n{filtered_news_md}"
        ),
        "Quant Analyst": (
            f"STOCK: {symbol}\n"
            f"QUANTITATIVE METRICS:\n{json.dumps(quant_input, indent=2)}\n\n"
            f"{ml_block}"
        ),
        "Risk Analyst": (
            f"STOCK: {symbol}\n"
            f"RISK METRICS:\n{json.dumps(risk_input, indent=2)}\n\n"
            f"{ml_block}"
        ),
        "Macro Analyst": (
            f"STOCK: {symbol}\n"
            f"MACRO METRICS:\n{json.dumps(macro_input, indent=2)}\n\n"
            f"FILTERED NEWS & SENTIMENT:\n{filtered_news_md}"
        ),
    }

    analyst_weights = get_analyst_weights()

    # ── Step 7: Convene AI Board Room ─────────────────────────────────────────
    if progress_callback: progress_callback(6, total_steps, "Convening AI Board Room (LLM debate)...")
    council_results = run_ai_council(
        symbol=symbol,
        snapshot_data=snapshot,
        shariah_engine_verdict=shariah_verdict,
        shariah_engine_report=shariah_report,
        macro_sentiment=macro_sentiment,
        analyst_weights=analyst_weights,
        progress_callback=progress_callback,
        analyst_inputs=analyst_inputs,
    )

    council_results["system_scores_baseline"] = deterministic_scores
    council_results["snapshot"]               = snapshot
    council_results["filtered_news_markdown"] = filtered_news_md
    council_results["ml_signals"]             = ml_signals

    if progress_callback: progress_callback(total_steps, total_steps, "Done.")
    return council_results

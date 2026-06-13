"""
core/pipeline.py — Unified three-tiered execution pipeline for PSX Advisory Agent v3.

Tiers:
- Tier 1: Quant Screener (Super Fast)
  - Technical scoring, Shariah screening, Mathematical confidence, ATR horizon.
- Tier 1.5: Micro-Agent Spotter (Fast AI check)
  - Single-prompt Ollama check to detect hidden structural patterns on anomaly/high-score candidates.
  - JSON output: {"interesting": true/false, "structural_patterns": [...], "investigate_further": true/false, "explanation": "..."}
- Tier 2: AI Board Room (Deep AI Debate)
  - Runs the 6 Ollama analysts + Chairman only on Tier 1.5 approved candidates (shortlisted).
  - Chairman cannot override Tier 1 verdict, Shariah status, target price, or stop loss.
"""

import json
import logging
from datetime import datetime, date
import time
from typing import Optional

import pandas as pd
from memory.db import get_conn
from core.data_engine import fetch_ohlcv
from core.scoring_engine import score_stock
from core.shariah_engine import screen_stock
from core.confidence_engine import compute_confidence
from core.horizon_engine import compute_horizon
from core.ml_engine import predict as ml_predict
from council.ollama_council import run_ai_council, ollama_chat, pick_model, get_available_models, parse_json_response

logger = logging.getLogger("pipeline")


# Tier 1.5 Spotter System Prompt
SPOTTER_SYSTEM = """You are a Micro-Agent Spotter for the Pakistan Stock Exchange.
Your task is to analyze the stock metrics, indicators, and recent anomalies to detect hidden structural patterns (e.g., volume consolidation before breakout, accumulation, divergence).
Do NOT output scores, ratings, or overrides.
Output a strict JSON structure ONLY. No extra text or markdown formatting outside the JSON block.

Expected Output Format:
{
  "interesting": true,
  "structural_patterns": ["Pattern 1", "Pattern 2"],
  "investigate_further": true,
  "explanation": "Brief explanation of what was spotted."
}"""


def run_tier1_5_spotter(symbol: str, t1_result: dict) -> dict:
    """Run a fast single-prompt Ollama check to see if the stock is worth debating in Tier 2."""
    available_models = get_available_models()
    model_name = pick_model("qwen2.5:7b", available_models)
    if not model_name:
        logger.warning(f"Ollama not available. Skipping Tier 1.5 for {symbol}.")
        return {"interesting": False, "structural_patterns": [], "investigate_further": False, "explanation": "Ollama unavailable."}

    user_msg = f"""Analyze this stock snapshot for structural patterns:
Symbol: {symbol}
Current Price: {t1_result.get('price_at_run')}
Verdict: {t1_result.get('verdict')}
Score: {t1_result.get('final_score')}
Trend: {t1_result.get('trend')}
Anomalies: {json.dumps(t1_result.get('anomaly_flags', []))}
Signals: {json.dumps(t1_result.get('signals', {}))}
"""
    raw_response = ollama_chat(model_name, SPOTTER_SYSTEM, user_msg)
    if not raw_response:
        return {"interesting": False, "structural_patterns": [], "investigate_further": False, "explanation": "Ollama call failed."}
    
    parsed = parse_json_response(raw_response)
    # Ensure keys are present
    return {
        "interesting": bool(parsed.get("interesting", False)),
        "structural_patterns": list(parsed.get("structural_patterns", [])),
        "investigate_further": bool(parsed.get("investigate_further", False)),
        "explanation": str(parsed.get("explanation", "No explanation provided."))
    }


def run_pipeline_for_stock(symbol: str, df: pd.DataFrame, force_council: bool = False) -> dict:
    """Runs the full 3-tiered pipeline for a single stock and logs results to DB."""
    symbol = symbol.upper()
    start_time = time.time()
    
    # ----------------- TIER 1: Quant Screen -----------------
    price_now = float(df["Close"].iloc[-1])
    
    # ML inference (if minimum 200 rows guard passed)
    ml_res = ml_predict(symbol, {
        "price": price_now,
        "rsi": float(df["Close"].pct_change().rolling(14).mean().iloc[-1] * 100), # placeholder check
        "volume": float(df["Volume"].iloc[-1]),
    }, df)
    
    # Scoring
    t1_score = score_stock(
        symbol=symbol,
        df=df,
        ml_prediction=ml_res.get("direction"),
        ml_probability=ml_res.get("direction_proba", {}).get("UP", 0.5),
        ml_reliable=ml_res.get("ml_signal_reliable", False),
        announcements=[] # TODO: announcements
    )
    
    # Shariah Screen
    shariah_rep = screen_stock(symbol, fundamentals={}, sector=None, industry=None)
    
    # Mathematical Confidence
    adx_val = t1_score.get("regime", {}).get("adx_value", 20.0)
    conf_res = compute_confidence(
        verdict=t1_score["verdict"],
        rsi_bullish=t1_score["raw_data"].get("rsi_bullish"),
        macd_bullish=t1_score["raw_data"].get("macd_bullish"),
        ema_trend=t1_score["trend"],
        bb_position=t1_score["raw_data"].get("bb_pct_b"),
        volume_notable=t1_score["raw_data"].get("volume_notable", False),
        anomaly_flags=t1_score["anomaly_flags"],
        ml_probability=ml_res.get("direction_proba", {}).get("UP", 0.5),
        adx_value=adx_val
    )
    
    # ATR Horizon
    hor_res = compute_horizon(
        df=df,
        entry_price=price_now,
        verdict=t1_score["verdict"],
        adx_value=adx_val
    )
    
    # Construct complete Tier 1 output package
    pipeline_res = {
        "symbol": symbol,
        "price_at_run": price_now,
        "verdict": t1_score["verdict"],
        "final_score": t1_score["final_score"],
        "technical_score": t1_score["technical_score"],
        "signals": t1_score["signals"],
        "trend": t1_score["trend"],
        "regime": t1_score["regime"],
        "anomaly_flags": t1_score["anomaly_flags"],
        "anomaly_details": t1_score["anomaly_details"],
        "score_breakdown": t1_score["score_breakdown"],
        "reasons": t1_score["reasons"],
        "shariah_status": shariah_rep.overall_status,
        "shariah_report": shariah_rep.to_dict(),
        "confidence": conf_res["confidence_score"],
        "confidence_label": conf_res["confidence_label"],
        "confidence_components": conf_res["components"],
        "horizon": hor_res,
        "ml_signals": ml_res,
        "council_run": 0,
        "council_result": None,
        "challenge_result": None
    }
    
    # ----------------- TIER 1.5: Spotter -----------------
    has_anomalies = len(pipeline_res["anomaly_flags"]) > 0
    high_score = pipeline_res["final_score"] >= 50
    
    spotter_res = {"interesting": False}
    if has_anomalies or high_score or force_council:
        spotter_res = run_tier1_5_spotter(symbol, pipeline_res)
        
    # ----------------- TIER 2: Board Room -----------------
    should_run_t2 = force_council or (spotter_res.get("interesting") and pipeline_res["shariah_status"] == "COMPLIANT")
    
    if should_run_t2:
        logger.info(f"Shortlisted candidate {symbol} routed to Tier 2 AI Board Room.")
        t2_res = run_ai_council(
            symbol=symbol,
            snapshot_data={
                "price": price_now,
                "fundamentals": {},
                "indicators": t1_score["signals"]
            },
            shariah_engine_verdict=shariah_rep.overall_status,
            shariah_engine_report=shariah_rep.to_dict(),
            quant_verdict=pipeline_res["verdict"],
            quant_score=pipeline_res["final_score"]
        )
        
        # Enforce that Chairman CANNOT override Tier 1 verdict or Shariah or target/stop
        if t2_res and "error" not in t2_res:
            pipeline_res["council_run"] = 1
            pipeline_res["council_result"] = {
                "validation_status": t2_res.get("validation_status", "VALIDATED"),
                "chairman_notes": t2_res.get("chairman_notes"),
                "key_drivers": t2_res.get("chairman_key_drivers", []),
                "risk_factors": t2_res.get("chairman_risk_factors", []),
                "analyst_consensus": t2_res.get("analyst_consensus", ""),
                "local_verdicts": t2_res.get("analyst_verdicts", {})
            }
            logger.info(f"Tier 2 complete for {symbol}. Rationale summarized.")
            
    # Compute run duration
    duration = time.time() - start_time
    
    # Save canonical package to SQLite `pipeline_results`
    save_pipeline_result(pipeline_res, duration)
    
    return pipeline_res


def save_pipeline_result(res: dict, duration_s: float):
    """Save the final recommendation package to SQLite database."""
    run_date_str = date.today().isoformat()
    now_str = datetime.now().isoformat()
    
    with get_conn() as conn:
        # Check if already exists for run_date & symbol
        exists = conn.execute("""
            SELECT id FROM pipeline_results WHERE run_date = ? AND symbol = ?
        """, (run_date_str, res["symbol"])).fetchone()
        
        vote_breakdown = json.dumps(res.get("score_breakdown", {}))
        ml_signals_json = json.dumps(res.get("ml_signals", {}))
        council_result_json = json.dumps(res.get("council_result") or {})
        risk_matrix = json.dumps({
            "confidence_label": res.get("confidence_label"),
            "confidence_components": res.get("confidence_components")
        })
        entry_exit = json.dumps(res.get("horizon", {}))
        
        # Expiry is 14 calendar days from now by default
        expiry_date = (datetime.now() + pd.Timedelta(days=14)).isoformat()
        
        if exists:
            conn.execute("""
                UPDATE pipeline_results
                SET run_timestamp = ?, final_verdict = ?, final_score = ?,
                    vote_breakdown = ?, ml_signals = ?, council_result = ?,
                    risk_matrix = ?, shariah_status = ?, entry_exit = ?,
                    price_at_run = ?, council_run = ?, run_duration_s = ?
                WHERE id = ?
            """, (
                now_str, res["verdict"], res["final_score"],
                vote_breakdown, ml_signals_json, council_result_json,
                risk_matrix, res["shariah_status"], entry_exit,
                res["price_at_run"], res["council_run"], duration_s,
                exists["id"]
            ))
        else:
            conn.execute("""
                INSERT INTO pipeline_results (
                    run_date, run_timestamp, symbol, final_verdict, final_score,
                    vote_breakdown, ml_signals, council_result, risk_matrix,
                    shariah_status, entry_exit, price_at_run, council_run,
                    run_duration_s, recommendation_created_at, recommendation_expiry_at,
                    target_hit, stop_hit, outcome_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'OPEN')
            """, (
                run_date_str, now_str, res["symbol"], res["verdict"], res["final_score"],
                vote_breakdown, ml_signals_json, council_result_json, risk_matrix,
                res["shariah_status"], entry_exit, res["price_at_run"], res["council_run"],
                duration_s, now_str, expiry_date
            ))
        conn.commit()

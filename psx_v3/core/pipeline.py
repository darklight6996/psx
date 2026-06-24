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
from core.data_engine import fetch_ohlcv, fetch_fundamentals
from core.scoring_engine import score_stock
from core.shariah_engine import screen_stock
from core.confidence_engine import compute_confidence
from core.horizon_engine import compute_horizon
from core.ml_engine import predict as ml_predict
from council.ollama_council import run_ai_council, ollama_chat, pick_model, get_available_models, parse_json_response
from core.personal_advisor import get_personal_portfolio_context, get_personal_signal

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


def run_pipeline_for_stock(symbol: str, df: pd.DataFrame, force_council: bool = False, run_ml: bool = False) -> dict:
    """Runs the full 3-tiered pipeline for a single stock and logs results to DB."""
    from core.indicators import calc_rsi
    symbol = symbol.upper()
    start_time = time.time()
    
    # ----------------- TIER 1: Quant Screen -----------------
    price_now = float(df["Close"].iloc[-1])
    
    if len(df) < 200:
        logger.info(f"[Pipeline] {symbol} has < 200 rows. Routing to New Listings handler.")
        from core.new_listings import analyze_new_listing
        fundamentals = fetch_fundamentals(symbol)
        nl_res = analyze_new_listing(symbol, df, fundamentals)
        # Construct pipeline_res format for new listings
        pipeline_res = {
            "symbol": symbol,
            "company_name": fundamentals.get("company_name", symbol),
            "sector": fundamentals.get("sector", "Unknown"),
            "price_at_run": price_now,
            "verdict": nl_res["verdict"],
            "final_score": nl_res["final_score"],
            "technical_score": nl_res["technical_score"],
            "signals": nl_res["signals"],
            "trend": nl_res["trend"],
            "regime": nl_res["regime"],
            "anomaly_flags": nl_res["anomaly_flags"],
            "anomaly_details": nl_res["anomaly_details"],
            "score_breakdown": nl_res["score_breakdown"],
            "reasons": nl_res["reasons"],
            "shariah_status": "UNKNOWN",
            "shariah_report": {},
            "confidence": nl_res["confidence"],
            "confidence_label": nl_res["confidence_label"],
            "confidence_components": nl_res["confidence_components"],
            "horizon": nl_res["horizon"],
            "ml_signals": nl_res["ml_signals"],
            "council_run": False,
            "council_result": None,
            "news": {"verified_facts": [], "retail_sentiment": [], "discarded_noise": []}
        }
        return pipeline_res

    # ML inference (if run_ml is True and minimum 200 rows guard passed)
    ml_res = {}
    if run_ml:
        # Use proper RSI from the indicators module
        rsi_series = calc_rsi(df)
        rsi_val = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50.0
        
        ml_res = ml_predict(symbol, {
            "price": price_now,
            "rsi": rsi_val,
            "volume": float(df["Volume"].iloc[-1]),
        }, df)
    else:
        ml_res = {
            "direction": "UNKNOWN",
            "direction_proba": {"UP": 0.5, "NOT_UP": 0.5},
            "ml_signal_reliable": False,
            "status": "skipped",
            "reason": "Selective ML disabled"
        }
    
    # Scoring
    t1_score = score_stock(
        symbol=symbol,
        df=df,
        ml_prediction=ml_res.get("direction"),
        ml_probability=ml_res.get("direction_proba", {}).get("UP", 0.5),
        ml_reliable=ml_res.get("ml_signal_reliable", False),
        announcements=[] # TODO: announcements
    )
    
    # Fetch fundamentals
    fundamentals = fetch_fundamentals(symbol)

    # Shariah Screen
    shariah_rep = screen_stock(symbol, fundamentals=fundamentals, sector=fundamentals.get("sector"), industry=fundamentals.get("industry"))
    
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
    
    # ── Personal Signal (Layer on top of market signal) ──────────────────────
    portfolio_ctx = get_personal_portfolio_context(symbol, price_now)
    personal_signal = get_personal_signal(
        symbol=symbol,
        market_signal=t1_score["verdict"],
        market_score=t1_score["final_score"],
        current_price=price_now,
        df=df,
        portfolio_context=portfolio_ctx,
    )

    # Construct complete Tier 1 output package
    pipeline_res = {
        "symbol": symbol,
        "company_name": fundamentals.get("company_name", symbol),
        "sector": fundamentals.get("sector", "Unknown"),
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
        "fundamentals": fundamentals,
        "council_run": 0,
        "council_result": None,
        "challenge_result": None,
        "personal_signal": personal_signal,
        "portfolio_context": portfolio_ctx,
    }
    
    # ── News Enrichment: X Feed + Google Search ──────────────────────────────
    try:
        from core.x_feed import fetch_recent_tweets
        from core.news_filter import filter_and_format_news
        tweets = fetch_recent_tweets(f"{symbol} PSX")
        formatted_news = [
            {
                "source": "X",
                "content": t["text"],
                "url": f"https://x.com/user/status/{t['id']}",
                "user": "X User",
                "sentiment": "neutral",
            }
            for t in tweets
        ]
        filtered_news = filter_and_format_news(formatted_news)
        pipeline_res["news"] = filtered_news
    except Exception as e:
        logger.warning(f"[Pipeline] X news fetch failed for {symbol}: {e}")
        pipeline_res["news"] = {"verified_facts": [], "retail_sentiment": [], "discarded_noise": []}

    # Google Search enrichment (additive — no crash risk)
    try:
        from core.google_search import search_stock_news, format_search_results_for_llm
        company_name = fundamentals.get("company_name", "") if fundamentals else ""
        gsearch_results = search_stock_news(symbol, company_name, lookback_days=7)
        pipeline_res["google_news"] = gsearch_results
        # Also expose as text for LLM consumption
        pipeline_res["google_news_summary"] = format_search_results_for_llm(gsearch_results, max_chars=2000)
    except Exception as e:
        logger.debug(f"[Pipeline] Google search skipped for {symbol}: {e}")
        pipeline_res["google_news"] = []
        pipeline_res["google_news_summary"] = ""


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
                "fundamentals": fundamentals,
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

        # New fields serialization
        company_name = res.get("company_name", res["symbol"])
        sector = res.get("sector", "Unknown")
        signals_json = json.dumps(res.get("signals", {}))
        trend = res.get("trend", "")
        anomaly_flags_json = json.dumps(res.get("anomaly_flags", []))
        anomaly_details_json = json.dumps(res.get("anomaly_details", []))
        reasons_json = json.dumps(res.get("reasons", []))
        confidence = res.get("confidence")
        confidence_label = res.get("confidence_label", "MODERATE")
        confidence_components_json = json.dumps(res.get("confidence_components", {}))
        regime_json = json.dumps(res.get("regime", {}))
        shariah_report_json = json.dumps(res.get("shariah_report", {}))
        fundamentals_json = json.dumps(res.get("fundamentals", {}))
        
        # Expiry is 14 calendar days from now by default
        from datetime import timedelta
        expiry_date = (datetime.now() + timedelta(days=14)).isoformat()
        
        if exists:
            conn.execute("""
                UPDATE pipeline_results
                SET run_timestamp = ?, final_verdict = ?, final_score = ?,
                    vote_breakdown = ?, ml_signals = ?, council_result = ?,
                    risk_matrix = ?, shariah_status = ?, entry_exit = ?,
                    price_at_run = ?, council_run = ?, run_duration_s = ?,
                    company_name = ?, sector = ?, signals = ?, trend = ?,
                    anomaly_flags = ?, anomaly_details = ?, reasons = ?,
                    confidence = ?, confidence_label = ?, confidence_components = ?,
                    regime = ?, shariah_report = ?, fundamentals = ?
                WHERE id = ?
            """, (
                now_str, res["verdict"], res["final_score"],
                vote_breakdown, ml_signals_json, council_result_json,
                risk_matrix, res["shariah_status"], entry_exit,
                res["price_at_run"], res["council_run"], duration_s,
                company_name, sector, signals_json, trend,
                anomaly_flags_json, anomaly_details_json, reasons_json,
                confidence, confidence_label, confidence_components_json,
                regime_json, shariah_report_json, fundamentals_json,
                exists["id"]
            ))
        else:
            conn.execute("""
                INSERT INTO pipeline_results (
                    run_date, run_timestamp, symbol, final_verdict, final_score,
                    vote_breakdown, ml_signals, council_result, risk_matrix,
                    shariah_status, entry_exit, price_at_run, council_run,
                    run_duration_s, recommendation_created_at, recommendation_expiry_at,
                    target_hit, stop_hit, outcome_status,
                    company_name, sector, signals, trend,
                    anomaly_flags, anomaly_details, reasons,
                    confidence, confidence_label, confidence_components,
                    regime, shariah_report, fundamentals
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_date_str, now_str, res["symbol"], res["verdict"], res["final_score"],
                vote_breakdown, ml_signals_json, council_result_json, risk_matrix,
                res["shariah_status"], entry_exit, res["price_at_run"], res["council_run"],
                duration_s, now_str, expiry_date,
                company_name, sector, signals_json, trend,
                anomaly_flags_json, anomaly_details_json, reasons_json,
                confidence, confidence_label, confidence_components_json,
                regime_json, shariah_report_json, fundamentals_json
            ))
        conn.commit()


def load_pipeline_results(run_date: Optional[str] = None) -> list[dict]:
    """Read and deserialise all pipeline results for a given date (or the latest date)."""
    with get_conn() as conn:
        if not run_date:
            row = conn.execute("SELECT MAX(run_date) FROM pipeline_results").fetchone()
            if not row or not row[0]:
                return []
            run_date = row[0]
            
        rows = conn.execute("""
            SELECT * FROM pipeline_results WHERE run_date = ?
        """, (run_date,)).fetchall()
        
    results = []
    for r in rows:
        row = dict(r)
        
        # Deserialise JSON columns
        def safe_json(val, default):
            if not val:
                return default
            try:
                return json.loads(val)
            except Exception:
                return default
                
        pipeline_res = {
            "symbol": row["symbol"],
            "date": row["run_date"],
            "company_name": row.get("company_name") or row["symbol"],
            "sector": row.get("sector") or "Unknown",
            "price_at_run": row["price_at_run"],
            "verdict": row["final_verdict"],
            "final_score": row["final_score"],
            "technical_score": row["final_score"], # fallback
            "signals": safe_json(row.get("signals"), {}),
            "trend": row.get("trend") or "",
            "regime": safe_json(row.get("regime"), {}),
            "anomaly_flags": safe_json(row.get("anomaly_flags"), []),
            "anomaly_details": safe_json(row.get("anomaly_details"), []),
            "score_breakdown": safe_json(row["vote_breakdown"], {}),
            "reasons": safe_json(row.get("reasons"), []),
            "shariah_status": row["shariah_status"],
            "shariah_report": safe_json(row.get("shariah_report"), {}),
            "confidence": row.get("confidence") or 50.0,
            "confidence_label": row.get("confidence_label") or "MODERATE",
            "confidence_components": safe_json(row.get("confidence_components"), {}),
            "horizon": safe_json(row["entry_exit"], {}),
            "ml_signals": safe_json(row["ml_signals"], {}),
            "fundamentals": safe_json(row.get("fundamentals"), {}),
            "council_run": row["council_run"],
            "council_result": safe_json(row["council_result"], {}),
            "challenge_result": safe_json(row.get("challenge_result"), {})
        }
        results.append(pipeline_res)
    return results


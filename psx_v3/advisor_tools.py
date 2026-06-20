"""
advisor_tools.py — Tool abstraction layer for the PSX V4 AI Advisor.

Every data access the advisor needs goes through this file.
V3 engines are never called directly from advisor_engine.py.

Design rules:
  - Every tool returns {"status": "ok"|"error"|"unavailable", "data": ..., "source": ...}
  - Every tool has full try/except — advisor never crashes due to a data failure
  - Tools are read-only — nothing here modifies V3 state
  - Tools are fast — heavy computation (full pipeline run) is NOT done here;
    the advisor reads from already-computed pipeline_results in the DB

Wiring:
  V3 pipeline writes pipeline_results → DB
  advisor_tools reads pipeline_results from DB (or falls back to live fetch)
  advisor_engine calls advisor_tools
"""

import json
import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger("advisor_tools")

# ---------------------------------------------------------------------------
# Shared DB helper (reuses V3's connection)
# ---------------------------------------------------------------------------

def _db():
    try:
        from memory.db import get_conn
        return get_conn()
    except Exception as e:
        logger.error(f"DB connection failed: {e}")
        return None


def _wrap(data, source: str = "db") -> dict:
    return {"status": "ok", "data": data, "source": source}


def _err(msg: str, source: str = "error") -> dict:
    return {"status": "error", "data": None, "source": source, "message": msg}


def _unavail(msg: str = "Data unavailable") -> dict:
    return {"status": "unavailable", "data": None, "source": "unavailable", "message": msg}


# ---------------------------------------------------------------------------
# Market tools
# ---------------------------------------------------------------------------

def get_live_quote(symbol: str) -> dict:
    """Current price, bid/ask from PSX live portal with yfinance fallback."""
    try:
        from core.psx_live import get_live_quote as _q
        result = _q(symbol.upper())
        if result.get("last_price") is not None:
            return _wrap(result, source="psx_live")
        return _unavail(f"No live price for {symbol}")
    except Exception as e:
        logger.warning(f"get_live_quote failed for {symbol}: {e}")
        # Fallback: last known price from DB
        return get_last_known_price(symbol)


def get_last_known_price(symbol: str) -> dict:
    """Last recorded close price from pipeline_results."""
    try:
        conn = _db()
        if not conn:
            return _unavail("DB unavailable")
        with conn:
            row = conn.execute("""
                SELECT price_at_run, run_timestamp FROM pipeline_results
                WHERE symbol = ?
                ORDER BY run_date DESC LIMIT 1
            """, (symbol.upper(),)).fetchone()
        if row:
            return _wrap({
                "symbol": symbol.upper(),
                "last_price": row["price_at_run"],
                "as_of": row["run_timestamp"],
                "source": "pipeline_cache",
            }, source="pipeline_cache")
        return _unavail(f"No price data found for {symbol}")
    except Exception as e:
        return _err(str(e))


def get_order_book_ratio(symbol: str) -> dict:
    """Bid/ask volume ratio from PSX live portal."""
    try:
        from core.psx_live import get_live_quote as _q
        q = _q(symbol.upper())
        bid_vol = q.get("bid_volume", 0) or 0
        ask_vol = q.get("ask_volume", 0) or 0
        ratio = round(bid_vol / ask_vol, 2) if ask_vol > 0 else None
        return _wrap({
            "symbol": symbol.upper(),
            "bid_volume": bid_vol,
            "ask_volume": ask_vol,
            "ratio": ratio,
            "interpretation": (
                "Buyer pressure" if (ratio or 0) > 1.2
                else "Seller pressure" if (ratio or 0) < 0.8
                else "Balanced"
            ),
        }, source="psx_live")
    except Exception as e:
        return _err(str(e))


def get_market_status() -> dict:
    """Whether PSX is currently open."""
    try:
        from core.data_engine import get_market_status as _ms
        return _wrap(_ms(), source="local")
    except Exception as e:
        return _err(str(e))


# ---------------------------------------------------------------------------
# Analytics tools (read from pipeline_results — already computed by V3)
# ---------------------------------------------------------------------------

def get_pipeline_result(symbol: str) -> dict:
    """
    Latest complete V3 pipeline result for a symbol.
    This is the primary source of truth for all analytics data.
    Returns the full stored result including verdict, score, signals,
    anomalies, shariah status, and horizon.
    """
    try:
        conn = _db()
        if not conn:
            return _unavail("DB unavailable")
        with conn:
            row = conn.execute("""
                SELECT * FROM pipeline_results
                WHERE symbol = ?
                ORDER BY run_date DESC LIMIT 1
            """, (symbol.upper(),)).fetchone()

        if not row:
            return _unavail(f"No pipeline result found for {symbol}. Run daily analysis first.")

        d = dict(row)
        # Parse JSON fields
        for field in ["vote_breakdown", "ml_signals", "council_result",
                      "risk_matrix", "entry_exit", "sentiment",
                      "candlestick_patterns", "challenge_result", "indicators"]:
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except Exception:
                    d[field] = {}

        return _wrap(d, source="pipeline_db")
    except Exception as e:
        return _err(str(e))


def get_ml_prediction(symbol: str) -> dict:
    """
    ML prediction from the latest pipeline result.
    Returns direction, confidence, reliability flag, and top features.
    """
    pr = get_pipeline_result(symbol)
    if pr["status"] != "ok":
        return pr
    ml = pr["data"].get("ml_signals") or {}
    if not ml:
        return _unavail(f"No ML signals stored for {symbol}")
    return _wrap({
        "symbol": symbol.upper(),
        "direction": ml.get("direction", "NOT_UP"),
        "confidence_pct": ml.get("confidence_pct", 0),
        "ml_signal_reliable": ml.get("ml_signal_reliable", False),
        "signal_strength": ml.get("signal_strength", "WEAK"),
        "model_accuracy_pct": ml.get("model_accuracy_pct", 0),
        "training_rows": ml.get("training_rows", 0),
        "direction_proba": ml.get("direction_proba", {}),
        "top_features": ml.get("top_features", {}),
        "summary": (
            f"RF predicts {ml.get('direction', '?')} with "
            f"{ml.get('confidence_pct', 0):.0f}% confidence "
            f"({'reliable' if ml.get('ml_signal_reliable') else 'UNRELIABLE — use with caution'})"
        ),
    }, source="pipeline_db")


def get_signal_scores(symbol: str) -> dict:
    """Technical signals (RSI, MACD, EMA trend, Bollinger, volume) from latest pipeline."""
    pr = get_pipeline_result(symbol)
    if pr["status"] != "ok":
        return pr
    d = pr["data"]
    return _wrap({
        "symbol": symbol.upper(),
        "verdict": d.get("final_verdict"),
        "final_score": d.get("final_score"),
        "technical_score": d.get("vote_breakdown", {}).get("technical_score"),
        "anomaly_boost": d.get("vote_breakdown", {}).get("anomaly_boost"),
        "regime": d.get("risk_matrix", {}).get("confidence_label"),
        "run_date": d.get("run_date"),
    }, source="pipeline_db")


# ---------------------------------------------------------------------------
# Risk tools
# ---------------------------------------------------------------------------

def get_atr_targets(symbol: str) -> dict:
    """ATR-based target price, stop loss, holding period from latest pipeline."""
    pr = get_pipeline_result(symbol)
    if pr["status"] != "ok":
        return pr
    horizon = pr["data"].get("entry_exit") or {}
    price = pr["data"].get("price_at_run")
    if not horizon:
        return _unavail(f"No horizon data for {symbol}")
    return _wrap({
        "symbol": symbol.upper(),
        "current_price": price,
        "target_price": horizon.get("target_price"),
        "stop_loss": horizon.get("stop_loss"),
        "risk_reward_ratio": horizon.get("risk_reward_ratio"),
        "target_pct": horizon.get("target_pct"),
        "stop_pct": horizon.get("stop_pct"),
        "holding_label": (horizon.get("holding_period") or {}).get("holding_label"),
        "holding_description": (horizon.get("holding_period") or {}).get("holding_description"),
        "atr": horizon.get("atr"),
    }, source="pipeline_db")


def get_risk_matrix(symbol: str) -> dict:
    """Confidence score, label, and component breakdown from latest pipeline."""
    pr = get_pipeline_result(symbol)
    if pr["status"] != "ok":
        return pr
    rm = pr["data"].get("risk_matrix") or {}
    return _wrap({
        "symbol": symbol.upper(),
        "confidence_label": rm.get("confidence_label"),
        "confidence_components": rm.get("confidence_components", {}),
        "shariah_status": pr["data"].get("shariah_status"),
    }, source="pipeline_db")


# ---------------------------------------------------------------------------
# Shariah tools
# ---------------------------------------------------------------------------

def get_shariah_status(symbol: str) -> dict:
    """Shariah compliance status from latest pipeline result."""
    pr = get_pipeline_result(symbol)
    if pr["status"] != "ok":
        # Try shariah engine directly as fallback
        try:
            from core.shariah_engine import screen_stock
            from core.data_engine import fetch_fundamentals
            fundamentals = fetch_fundamentals(symbol)
            report = screen_stock(symbol, fundamentals)
            return _wrap({
                "symbol": symbol.upper(),
                "overall_status": report.overall_status,
                "kmi_listed": report.kmi_listed,
                "recommendation": report.recommendation,
                "risk_flag": report.risk_flag,
                "purification_pct": report.purification_pct,
                "criteria_summary": [
                    {"name": c.name, "status": c.status, "note": c.note}
                    for c in report.criteria
                ],
            }, source="shariah_engine_live")
        except Exception as e2:
            return _err(str(e2))

    d = pr["data"]
    status = d.get("shariah_status", "UNKNOWN")
    # Try to get richer data from council_result if board room was run
    council = d.get("council_result") or {}
    shariah_notes = ""
    if council:
        shariah_llm = council.get("shariah_llm_output") or {}
        shariah_notes = shariah_llm.get("notes", "")

    return _wrap({
        "symbol": symbol.upper(),
        "overall_status": status,
        "scholar_notes": shariah_notes,
        "run_date": d.get("run_date"),
        "compliant": status == "COMPLIANT",
    }, source="pipeline_db")


# ---------------------------------------------------------------------------
# Prediction history tools
# ---------------------------------------------------------------------------

def get_prediction_history(symbol: str, lookback_days: int = 60) -> dict:
    """
    Historical prediction accuracy for a symbol from prediction_audit.
    Returns hit rate, recent failures, and per-anomaly accuracy.
    """
    try:
        from core.prediction_audit import get_failure_analysis, get_stock_hit_rate
        hit_rate = get_stock_hit_rate(symbol, lookback_days=lookback_days)
        analysis = get_failure_analysis(lookback_days=lookback_days)

        # Filter per-stock
        stock_rate = analysis.get("per_stock_rates", {}).get(symbol.upper())
        per_anomaly = analysis.get("per_anomaly_rates", {})

        # Pull recent verdicts for this symbol from pipeline_results
        conn = _db()
        recent_verdicts = []
        if conn:
            with conn:
                rows = conn.execute("""
                    SELECT run_date, final_verdict, final_score, price_at_run
                    FROM pipeline_results
                    WHERE symbol = ?
                    ORDER BY run_date DESC LIMIT 10
                """, (symbol.upper(),)).fetchall()
            recent_verdicts = [dict(r) for r in rows]

        return _wrap({
            "symbol": symbol.upper(),
            "hit_rate_pct": hit_rate,
            "stock_specific_rate": stock_rate,
            "per_anomaly_accuracy": per_anomaly,
            "recent_verdicts": recent_verdicts,
            "top_failure_reasons": analysis.get("top_failure_reasons", [])[:3],
            "lookback_days": lookback_days,
            "summary": (
                f"Historical hit rate: {hit_rate:.1f}%" if hit_rate is not None
                else "Insufficient history for accuracy calculation"
            ),
        }, source="prediction_audit")
    except Exception as e:
        return _err(str(e))


def get_advisor_past_lessons(symbol: str) -> dict:
    """Retrieve past advisor lessons for a symbol."""
    try:
        from advisor_memory import get_relevant_lessons, format_lessons_for_prompt
        lessons = get_relevant_lessons(symbol=symbol, limit=3)
        return _wrap({
            "lessons": lessons,
            "formatted": format_lessons_for_prompt(lessons),
        }, source="advisor_memory")
    except Exception as e:
        return _err(str(e))


# ---------------------------------------------------------------------------
# Macro / sentiment tools
# ---------------------------------------------------------------------------

def get_macro_context() -> dict:
    """KIBOR rate, market breadth, macro sentiment from V3 signal cache."""
    try:
        from core.psx_signals import get_kibor_context, get_psx_breadth
        kibor = get_kibor_context()
        breadth = get_psx_breadth()
        return _wrap({
            "kibor_rate": kibor.get("rate"),
            "kibor_sentiment": kibor.get("sentiment"),
            "market_breadth_status": breadth.get("status"),
            "breadth_sentiment": breadth.get("sentiment"),
            "index_price": breadth.get("index_price"),
            "up_down_ratio": breadth.get("up_down_ratio"),
            "summary": (
                f"KIBOR {kibor.get('rate', '?')}% ({kibor.get('sentiment', '?')}). "
                f"KSE-100 breadth {breadth.get('status', '?')} "
                f"({breadth.get('sentiment', '?')})."
            ),
        }, source="psx_signals")
    except Exception as e:
        return _err(str(e))


def get_sector_rotation(symbol: str) -> dict:
    """Sector momentum rank for a symbol."""
    try:
        from core.psx_signals import get_sector_rotation as _sr
        result = _sr(symbol.upper())
        return _wrap(result, source="psx_signals")
    except Exception as e:
        return _err(str(e))


def get_recent_announcements(symbol: str) -> dict:
    """Recent PSX announcements for a symbol."""
    try:
        from core.psx_live import get_psx_announcements
        anns = get_psx_announcements(symbol=symbol.upper())
        return _wrap({
            "symbol": symbol.upper(),
            "announcements": anns[:5],
            "count": len(anns),
        }, source="psx_live")
    except Exception as e:
        return _err(str(e))


def get_earnings_proximity(symbol: str) -> dict:
    """Days until next earnings, risk level."""
    try:
        from core.psx_signals import get_earnings_proximity as _ep
        result = _ep(symbol.upper())
        return _wrap(result, source="psx_signals")
    except Exception as e:
        return _err(str(e))


# ---------------------------------------------------------------------------
# Quick universe screen
# ---------------------------------------------------------------------------

def run_quick_screen(symbols: list[str], min_score: float = 55.0) -> dict:
    """
    Read latest pipeline results for a list of symbols and filter
    by minimum score. Returns ranked list. No new computation.
    """
    try:
        conn = _db()
        if not conn:
            return _unavail("DB unavailable")

        results = []
        with conn:
            for sym in symbols:
                row = conn.execute("""
                    SELECT symbol, final_verdict, final_score, shariah_status,
                           price_at_run, run_date
                    FROM pipeline_results
                    WHERE symbol = ?
                    ORDER BY run_date DESC LIMIT 1
                """, (sym.upper(),)).fetchone()
                if row:
                    results.append(dict(row))

        filtered = [
            r for r in results
            if (r.get("final_score") or 0) >= min_score
        ]
        filtered.sort(key=lambda x: x.get("final_score", 0), reverse=True)

        return _wrap({
            "screened": len(results),
            "passed": len(filtered),
            "min_score": min_score,
            "results": filtered,
        }, source="pipeline_db")
    except Exception as e:
        return _err(str(e))


# ---------------------------------------------------------------------------
# Convenience: gather all context for a symbol in one call
# ---------------------------------------------------------------------------

def gather_symbol_context(symbol: str, include_history: bool = True) -> dict:
    """
    Single call that gathers everything the advisor needs to discuss a symbol.
    Used by advisor_engine.py before building the Ollama prompt.

    Returns a flat dict with all available data, gracefully handling
    any individual tool failures.
    """
    sym = symbol.upper()
    ctx: dict = {"symbol": sym}

    # Pipeline result (core data)
    pr = get_pipeline_result(sym)
    if pr["status"] == "ok":
        d = pr["data"]
        ctx["verdict"] = d.get("final_verdict")
        ctx["final_score"] = d.get("final_score")
        ctx["price"] = d.get("price_at_run")
        ctx["shariah_status"] = d.get("shariah_status")
        ctx["run_date"] = d.get("run_date")
        # Signals
        vb = d.get("vote_breakdown") or {}
        ctx["technical_score"] = vb.get("technical_score")
        ctx["anomaly_boost"] = vb.get("anomaly_boost")
        ctx["ml_nudge"] = vb.get("ml_nudge")
    else:
        ctx["pipeline_error"] = pr.get("message", "No pipeline result")

    # ML
    ml = get_ml_prediction(sym)
    if ml["status"] == "ok":
        ctx["ml"] = ml["data"]

    # ATR targets
    atr = get_atr_targets(sym)
    if atr["status"] == "ok":
        ctx["targets"] = atr["data"]

    # Live quote
    lq = get_live_quote(sym)
    if lq["status"] == "ok":
        ctx["live_price"] = lq["data"].get("last_price")

    # Macro
    macro = get_macro_context()
    if macro["status"] == "ok":
        ctx["macro"] = macro["data"]

    # Sector rotation
    sr = get_sector_rotation(sym)
    if sr["status"] == "ok":
        ctx["sector_rotation"] = sr["data"]

    # Earnings proximity
    ep = get_earnings_proximity(sym)
    if ep["status"] == "ok":
        ctx["earnings_proximity"] = ep["data"]

    # Prediction history
    if include_history:
        ph = get_prediction_history(sym, lookback_days=60)
        if ph["status"] == "ok":
            ctx["prediction_history"] = ph["data"]

    return ctx

"""
historical_reasoning.py — Historical pattern retrieval for the PSX V4 Advisor.

Answers questions like:
  "What happened after SSGC hit an upper cap?"
  "Has the volume_spike anomaly been reliable for ISL?"
  "What is ENGRO's track record after a golden cross?"

Queries existing V3 tables:
  - pipeline_results       (verdicts, scores, anomaly flags, prices)
  - prediction_audit       (was_correct, failure_reason, anomaly_triggers_fired)
  - decision_reflections   (AI self-critique per verdict)
  - advisor_conversations  (past advisor recommendations)

Returns structured dicts ready for injection into Ollama prompts.
"""

import json
import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger("historical_reasoning")


def _db():
    try:
        from memory.db import get_conn
        return get_conn()
    except Exception as e:
        logger.error(f"DB connection failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Post-event performance
# ---------------------------------------------------------------------------

def get_post_event_performance(
    symbol: str,
    event_type: str,
    lookback_days: int = 180,
) -> dict:
    """
    Find past occurrences of event_type for symbol in pipeline_results
    and return what the price did in the 5 days after each occurrence.

    event_type maps to anomaly_flags entries, e.g.:
      'volume_spike', 'bollinger_squeeze', 'macd_crossover',
      'ema_golden_cross', 'ema_death_cross', 'breakout_high_volume',
      'earnings_beat', 'earnings_miss', 'dividend_announced'

    Returns:
        {
            "symbol": str,
            "event_type": str,
            "occurrences": int,
            "outcomes": [{"date": str, "price_then": float, "verdict": str}],
            "avg_score_at_event": float,
            "summary": str   — human-readable for prompt injection
        }
    """
    sym = symbol.upper()
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    conn = _db()
    if not conn:
        return {"symbol": sym, "event_type": event_type, "occurrences": 0,
                "summary": "DB unavailable"}

    try:
        with conn:
            # pipeline_results stores vote_breakdown JSON which may contain
            # anomaly_flags. We search for the event string anywhere in the row.
            rows = conn.execute("""
                SELECT run_date, final_verdict, final_score, price_at_run,
                       vote_breakdown
                FROM pipeline_results
                WHERE symbol = ?
                  AND run_date >= ?
                ORDER BY run_date ASC
            """, (sym, cutoff)).fetchall()
    except Exception as e:
        return {"symbol": sym, "event_type": event_type, "occurrences": 0,
                "summary": f"Query failed: {e}"}

    occurrences = []
    scores_at_event = []

    for row in rows:
        row = dict(row)
        # Check if event_type appears in vote_breakdown JSON
        vb_raw = row.get("vote_breakdown") or ""
        vb_str = vb_raw if isinstance(vb_raw, str) else json.dumps(vb_raw)
        if event_type.lower() in vb_str.lower():
            occurrences.append({
                "date": row["run_date"],
                "verdict": row["final_verdict"],
                "price_then": row["price_at_run"],
                "score": row["final_score"],
            })
            if row["final_score"] is not None:
                scores_at_event.append(row["final_score"])

    n = len(occurrences)
    avg_score = round(sum(scores_at_event) / len(scores_at_event), 1) if scores_at_event else None

    if n == 0:
        summary = (
            f"No recorded occurrences of '{event_type}' for {sym} "
            f"in the last {lookback_days} days."
        )
    else:
        buy_count = sum(1 for o in occurrences if o["verdict"] == "BUY")
        summary = (
            f"'{event_type}' triggered {n} time(s) for {sym} "
            f"in the last {lookback_days} days. "
            f"System verdict was BUY in {buy_count}/{n} cases. "
            f"Avg score at trigger: {avg_score or 'N/A'}."
        )

    return {
        "symbol": sym,
        "event_type": event_type,
        "occurrences": n,
        "outcomes": occurrences[-5:],   # last 5 for brevity
        "avg_score_at_event": avg_score,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Anomaly reliability for a symbol
# ---------------------------------------------------------------------------

def get_anomaly_reliability(symbol: str, lookback_days: int = 90) -> dict:
    """
    For each anomaly type that has fired for this symbol, return
    how often the subsequent prediction was correct.

    Pulls from prediction_audit.anomaly_triggers_fired + was_correct.
    """
    sym = symbol.upper()
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    conn = _db()
    if not conn:
        return {"symbol": sym, "anomaly_reliability": {}, "summary": "DB unavailable"}

    try:
        with conn:
            rows = conn.execute("""
                SELECT anomaly_triggers_fired, was_correct
                FROM prediction_audit
                WHERE symbol = ?
                  AND prediction_date >= ?
                  AND was_correct IS NOT NULL
            """, (sym, cutoff)).fetchall()
    except Exception as e:
        return {"symbol": sym, "anomaly_reliability": {}, "summary": f"Query failed: {e}"}

    stats: dict = {}
    for row in rows:
        try:
            flags = json.loads(row["anomaly_triggers_fired"] or "[]")
        except Exception:
            flags = []
        for flag in flags:
            stats.setdefault(flag, {"total": 0, "correct": 0})
            stats[flag]["total"] += 1
            if row["was_correct"] == 1:
                stats[flag]["correct"] += 1

    reliability = {
        flag: {
            "total": v["total"],
            "hit_rate": round(v["correct"] / v["total"] * 100, 1),
        }
        for flag, v in stats.items()
        if v["total"] >= 2
    }

    if reliability:
        lines = [f"  {flag}: {v['hit_rate']}% ({v['total']} signals)"
                 for flag, v in sorted(reliability.items(),
                                       key=lambda x: x[1]["hit_rate"], reverse=True)]
        summary = f"Anomaly reliability for {sym}:\n" + "\n".join(lines)
    else:
        summary = f"Insufficient anomaly history for {sym} in the last {lookback_days} days."

    return {
        "symbol": sym,
        "anomaly_reliability": reliability,
        "lookback_days": lookback_days,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Recent verdict track record
# ---------------------------------------------------------------------------

def get_verdict_track_record(symbol: str, lookback_days: int = 60) -> dict:
    """
    Return the last N verdicts for a symbol alongside their correctness
    from prediction_audit. Used for "how has the system done on X recently?"
    """
    sym = symbol.upper()
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    conn = _db()
    if not conn:
        return {"symbol": sym, "records": [], "summary": "DB unavailable"}

    try:
        with conn:
            rows = conn.execute("""
                SELECT prediction_date, prediction, actual_result,
                       was_correct, failure_reason, confidence_score,
                       final_pipeline_score
                FROM prediction_audit
                WHERE symbol = ?
                  AND prediction_date >= ?
                ORDER BY prediction_date DESC
                LIMIT 10
            """, (sym, cutoff)).fetchall()
    except Exception as e:
        return {"symbol": sym, "records": [], "summary": f"Query failed: {e}"}

    records = [dict(r) for r in rows]
    evaluated = [r for r in records if r["was_correct"] is not None]
    hit_rate = (
        round(sum(1 for r in evaluated if r["was_correct"] == 1) / len(evaluated) * 100, 1)
        if evaluated else None
    )

    if not records:
        summary = f"No prediction history for {sym} in the last {lookback_days} days."
    elif hit_rate is None:
        summary = f"Recent verdicts for {sym}: {len(records)} found, none yet evaluated."
    else:
        recent = records[0]
        summary = (
            f"{sym} recent track record: {hit_rate}% hit rate over {len(evaluated)} evaluated "
            f"predictions. Most recent: {recent['prediction']} on {recent['prediction_date']} "
            f"→ {'✓' if recent['was_correct'] else '✗' if recent['was_correct'] == 0 else 'pending'}."
        )

    return {
        "symbol": sym,
        "records": records,
        "hit_rate_pct": hit_rate,
        "total_evaluated": len(evaluated),
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# AI self-reflections for a symbol
# ---------------------------------------------------------------------------

def get_ai_reflections(symbol: str, limit: int = 3) -> dict:
    """
    Pull the AI's own self-critiques for a symbol from decision_reflections.
    These are the Ollama-generated lessons from correct/incorrect predictions.
    """
    sym = symbol.upper()
    conn = _db()
    if not conn:
        return {"symbol": sym, "reflections": [], "summary": "DB unavailable"}

    try:
        with conn:
            rows = conn.execute("""
                SELECT decision_date, verdict, price_at_decision,
                       price_now, price_change_pct, is_correct,
                       reflection_notes
                FROM decision_reflections
                WHERE symbol = ?
                ORDER BY decision_date DESC
                LIMIT ?
            """, (sym, limit)).fetchall()
    except Exception as e:
        return {"symbol": sym, "reflections": [], "summary": f"Query failed: {e}"}

    reflections = [dict(r) for r in rows]

    if not reflections:
        summary = f"No AI self-reflections stored for {sym} yet."
    else:
        lines = []
        for r in reflections:
            outcome = "HIT" if r["is_correct"] else "MISS"
            lines.append(
                f"  {r['decision_date']} — {r['verdict']} [{outcome} "
                f"{r['price_change_pct']:+.1f}%]: {r['reflection_notes']}"
            )
        summary = f"AI reflections for {sym}:\n" + "\n".join(lines)

    return {
        "symbol": sym,
        "reflections": reflections,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Full historical brief for a symbol (used by advisor_engine)
# ---------------------------------------------------------------------------

def build_historical_brief(symbol: str) -> str:
    """
    Assemble a concise multi-section historical context string
    for injection into an Ollama system prompt.

    Keeps it tight — total length under ~400 tokens.
    """
    sym = symbol.upper()
    sections = []

    # 1. Verdict track record
    track = get_verdict_track_record(sym, lookback_days=60)
    if track["summary"]:
        sections.append(track["summary"])

    # 2. Anomaly reliability (only if data exists)
    anomaly = get_anomaly_reliability(sym, lookback_days=90)
    if anomaly["anomaly_reliability"]:
        sections.append(anomaly["summary"])

    # 3. AI reflections (most recent 2)
    reflections = get_ai_reflections(sym, limit=2)
    if reflections["reflections"]:
        sections.append(reflections["summary"])

    if not sections:
        return f"No historical data available for {sym}."

    return "\n\n".join(sections)

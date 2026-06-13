"""
prediction_audit.py — Prediction Audit Engine.

Analyzes why predictions fail instead of blindly adding new indicators.

Responsibilities:
  - Track every prediction made
  - Compare predicted outcome vs actual outcome
  - Generate failure reasons, per-stock success rates, per-indicator success rates
  - Feed insights back into calibration proposals

This runs BEFORE ML calibration — understanding failures is prerequisite
to improving models.
"""

import json
import logging
from datetime import datetime, date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Record a prediction for later audit
# ---------------------------------------------------------------------------

def record_prediction(
    symbol: str,
    prediction: str,          # "BUY" | "SELL" | "HOLD"
    confidence_score: float,
    anomaly_triggers: list[str],
    boardroom_recommendation: Optional[str],
    pipeline_score: float,
) -> None:
    """Save a prediction to the prediction_audit table for future evaluation."""
    from memory.db import get_conn

    try:
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO prediction_audit (
                    symbol, prediction_date, prediction, confidence_score,
                    anomaly_triggers_fired, boardroom_recommendation,
                    final_pipeline_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol.upper(),
                date.today().isoformat(),
                prediction,
                confidence_score,
                json.dumps(anomaly_triggers),
                boardroom_recommendation,
                pipeline_score,
            ))
    except Exception as e:
        logger.error(f"Failed to record prediction for {symbol}: {e}")


# ---------------------------------------------------------------------------
# Evaluate past predictions against actual outcomes
# ---------------------------------------------------------------------------

def evaluate_predictions(
    lookback_days: int = 5,
    price_getter=None,
) -> dict:
    """
    Evaluate all un-evaluated predictions from `lookback_days` ago.

    For each prediction:
      - Fetch current price vs price_at_signal
      - Determine if prediction was correct
      - Record failure reason if wrong

    Args:
        lookback_days: How many days back to look for un-evaluated predictions
        price_getter: callable(symbol) -> float, returns current price

    Returns:
        Summary of evaluations performed.
    """
    from memory.db import get_conn

    cutoff_date = (date.today() - timedelta(days=lookback_days)).isoformat()
    eval_date = date.today().isoformat()

    with get_conn() as conn:
        # Find un-evaluated predictions older than lookback
        rows = conn.execute("""
            SELECT id, symbol, prediction_date, prediction, confidence_score,
                   anomaly_triggers_fired, final_pipeline_score
            FROM prediction_audit
            WHERE actual_result IS NULL
              AND prediction_date <= ?
        """, (cutoff_date,)).fetchall()

    evaluated = 0
    correct = 0
    failures = []

    for row in rows:
        row = dict(row)
        symbol = row["symbol"]
        prediction = row["prediction"]

        # Get price at prediction time from pipeline_results
        from memory.db import get_conn as gc
        with gc() as conn2:
            price_row = conn2.execute("""
                SELECT price_at_run FROM pipeline_results
                WHERE symbol = ? AND run_date = ?
            """, (symbol, row["prediction_date"])).fetchone()

        price_at_signal = float(price_row["price_at_run"]) if price_row and price_row["price_at_run"] else None

        # Get current price
        current_price = None
        if price_getter:
            try:
                current_price = price_getter(symbol)
            except Exception:
                pass

        if price_at_signal is None or current_price is None:
            continue

        # Calculate actual move
        actual_move_pct = ((current_price - price_at_signal) / price_at_signal) * 100

        # Determine correctness
        if prediction == "BUY":
            was_correct = actual_move_pct > 0
            actual_result = "UP" if actual_move_pct > 0 else "DOWN"
        elif prediction == "SELL":
            was_correct = actual_move_pct < 0
            actual_result = "DOWN" if actual_move_pct < 0 else "UP"
        else:  # HOLD
            was_correct = abs(actual_move_pct) < 3.0  # HOLD is correct if price stayed flat
            actual_result = "FLAT" if abs(actual_move_pct) < 3.0 else ("UP" if actual_move_pct > 0 else "DOWN")

        # Failure reason analysis
        failure_reason = None
        if not was_correct:
            anomalies = []
            try:
                anomalies = json.loads(row.get("anomaly_triggers_fired") or "[]")
            except Exception:
                pass

            if prediction == "BUY" and actual_move_pct < -5:
                failure_reason = "Strong reversal after BUY signal"
            elif prediction == "BUY" and "volume_spike" in str(anomalies):
                failure_reason = "Volume spike without follow-through"
            elif prediction == "BUY":
                failure_reason = "Weak momentum — BUY signal did not hold"
            elif prediction == "SELL" and actual_move_pct > 5:
                failure_reason = "Strong rally after SELL signal"
            elif prediction == "SELL":
                failure_reason = "Premature SELL — stock continued higher"
            else:
                failure_reason = "HOLD prediction but significant move occurred"

            failures.append({
                "symbol": symbol,
                "prediction": prediction,
                "actual_move_pct": round(actual_move_pct, 2),
                "failure_reason": failure_reason,
            })

        # Update the audit record
        from memory.db import get_conn as gc2
        with gc2() as conn3:
            conn3.execute("""
                UPDATE prediction_audit
                SET actual_result = ?, was_correct = ?, failure_reason = ?, audit_date = ?
                WHERE id = ?
            """, (actual_result, 1 if was_correct else 0, failure_reason, eval_date, row["id"]))

        evaluated += 1
        if was_correct:
            correct += 1

    return {
        "evaluated": evaluated,
        "correct": correct,
        "incorrect": evaluated - correct,
        "hit_rate": round((correct / evaluated) * 100, 1) if evaluated > 0 else 0.0,
        "recent_failures": failures[:20],
    }


# ---------------------------------------------------------------------------
# Aggregated audit reports
# ---------------------------------------------------------------------------

def get_failure_analysis(lookback_days: int = 30) -> dict:
    """
    Aggregate top failure reasons, per-stock success rates,
    per-indicator success rates, and per-anomaly success rates.
    """
    from memory.db import get_conn

    cutoff_date = (date.today() - timedelta(days=lookback_days)).isoformat()

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT symbol, prediction, actual_result, was_correct,
                   confidence_score, anomaly_triggers_fired, failure_reason,
                   final_pipeline_score
            FROM prediction_audit
            WHERE prediction_date >= ? AND actual_result IS NOT NULL
        """, (cutoff_date,)).fetchall()

    if not rows:
        return {
            "total_evaluated": 0,
            "overall_hit_rate": 0.0,
            "top_failure_reasons": [],
            "per_stock_rates": {},
            "per_anomaly_rates": {},
        }

    rows = [dict(r) for r in rows]
    total = len(rows)
    correct = sum(1 for r in rows if r["was_correct"] == 1)
    overall_hit_rate = round((correct / total) * 100, 1) if total > 0 else 0.0

    # Top failure reasons
    failure_counts = {}
    for r in rows:
        reason = r.get("failure_reason")
        if reason:
            if reason not in failure_counts:
                failure_counts[reason] = {"count": 0, "total_for_type": 0}
            failure_counts[reason]["count"] += 1

    # Count total predictions for each failure type to get success rate
    for r in rows:
        reason = r.get("failure_reason")
        if reason and reason in failure_counts:
            failure_counts[reason]["total_for_type"] += 1

    top_failures = []
    for reason, data in sorted(failure_counts.items(), key=lambda x: x[1]["count"], reverse=True):
        top_failures.append({
            "failure_reason": reason,
            "occurrences": data["count"],
            "success_rate": round(100 - (data["count"] / max(data["total_for_type"], 1)) * 100, 1),
        })

    # Per-stock success rates
    stock_stats = {}
    for r in rows:
        sym = r["symbol"]
        if sym not in stock_stats:
            stock_stats[sym] = {"total": 0, "correct": 0}
        stock_stats[sym]["total"] += 1
        if r["was_correct"] == 1:
            stock_stats[sym]["correct"] += 1

    per_stock = {
        sym: round((s["correct"] / s["total"]) * 100, 1)
        for sym, s in stock_stats.items()
        if s["total"] >= 2  # only show stocks with enough data
    }

    # Per-anomaly success rates
    anomaly_stats = {}
    for r in rows:
        try:
            anomalies = json.loads(r.get("anomaly_triggers_fired") or "[]")
        except Exception:
            anomalies = []

        for anomaly in anomalies:
            if anomaly not in anomaly_stats:
                anomaly_stats[anomaly] = {"total": 0, "correct": 0}
            anomaly_stats[anomaly]["total"] += 1
            if r["was_correct"] == 1:
                anomaly_stats[anomaly]["correct"] += 1

    per_anomaly = {
        a: round((s["correct"] / s["total"]) * 100, 1)
        for a, s in anomaly_stats.items()
        if s["total"] >= 3  # need enough data
    }

    return {
        "total_evaluated": total,
        "overall_hit_rate": overall_hit_rate,
        "top_failure_reasons": top_failures[:10],
        "per_stock_rates": per_stock,
        "per_anomaly_rates": per_anomaly,
    }


def get_stock_hit_rate(symbol: str, lookback_days: int = 60) -> Optional[float]:
    """
    Get the historical hit rate for a specific stock.
    Returns None if insufficient data.
    """
    from memory.db import get_conn

    cutoff_date = (date.today() - timedelta(days=lookback_days)).isoformat()

    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END) as correct
            FROM prediction_audit
            WHERE symbol = ? AND prediction_date >= ? AND actual_result IS NOT NULL
        """, (symbol.upper(), cutoff_date)).fetchone()

    if not row or row["total"] < 3:
        return None

    return round((row["correct"] / row["total"]) * 100, 1)


def get_overall_hit_rate(lookback_days: int = 30) -> Optional[float]:
    """Get the system-wide hit rate across all stocks."""
    from memory.db import get_conn

    cutoff_date = (date.today() - timedelta(days=lookback_days)).isoformat()

    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END) as correct
            FROM prediction_audit
            WHERE prediction_date >= ? AND actual_result IS NOT NULL
        """, (cutoff_date,)).fetchone()

    if not row or row["total"] < 5:
        return None

    return round((row["correct"] / row["total"]) * 100, 1)

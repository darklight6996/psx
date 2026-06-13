"""
trading_journal.py — BUY challenge and post-mortem evaluation system.

Every BUY signal must pass a "challenge" test before being emitted:
  1. What is the STRONGEST counter-argument against this BUY?
  2. What specific signal drove this BUY?
  3. Is the deciding signal historically reliable for this stock?

Post-mortem:
  After the holding period expires, evaluate:
  - Was the prediction correct?
  - Which signal drove the decision and was it right?
  - What pattern can be detected in the outcome?
"""

import json
import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BUY Challenge
# ---------------------------------------------------------------------------

def challenge_buy(
    symbol: str,
    verdict: str,
    score: float,
    signals: dict,
    anomaly_flags: list[str],
    regime: dict,
) -> dict:
    """
    Challenge a BUY signal with counter-arguments.

    Returns:
        {
            "passed": bool,
            "deciding_signal": str,
            "counter_arguments": list[str],
            "challenge_score": float (0-100, higher = more confident BUY),
            "recommendation": str,
        }
    """
    if verdict != "BUY":
        return {
            "passed": True,  # non-BUY signals don't need challenge
            "deciding_signal": "N/A",
            "counter_arguments": [],
            "challenge_score": 0,
            "recommendation": f"{verdict} signal — challenge not required",
        }

    counter_args = []
    challenge_penalty = 0

    # Counter-argument 1: Regime
    regime_type = regime.get("regime", "CHOPPY")
    if regime_type == "TRENDING DOWN":
        counter_args.append(
            f"Market regime is TRENDING DOWN (ADX={regime.get('adx_value', 0):.0f})"
            " — buying against the trend is risky"
        )
        challenge_penalty += 15
    elif regime_type == "CHOPPY":
        counter_args.append(
            "Market regime is CHOPPY — no clear trend to support momentum BUY"
        )
        challenge_penalty += 8

    # Counter-argument 2: RSI
    rsi_data = signals.get("rsi", {})
    rsi_val = rsi_data.get("value", 50)
    if rsi_val > 65:
        counter_args.append(
            f"RSI is {rsi_val:.0f} — already in bullish territory, "
            "limited upside before overbought"
        )
        challenge_penalty += 10
    elif rsi_val > 75:
        counter_args.append(
            f"RSI is {rsi_val:.0f} — OVERBOUGHT. "
            "BUY at these levels historically has poor follow-through"
        )
        challenge_penalty += 20

    # Counter-argument 3: Volume confirmation
    vol_data = signals.get("volume", {})
    if not vol_data.get("notable", False):
        counter_args.append(
            "Volume is NOT notably elevated — BUY signal lacks volume confirmation"
        )
        challenge_penalty += 5

    # Counter-argument 4: No anomalies
    if not anomaly_flags:
        counter_args.append(
            "No anomaly triggers fired — this is a routine signal, not exceptional"
        )
        challenge_penalty += 5

    # Counter-argument 5: EMA trend
    ema_data = signals.get("ema_trend", {})
    ema_label = ema_data.get("label", "Unknown").lower()
    if "downtrend" in ema_label:
        counter_args.append(
            f"EMA trend is '{ema_label}' — price below key moving averages"
        )
        challenge_penalty += 12

    # Determine deciding signal
    deciding_signal = _identify_deciding_signal(signals, anomaly_flags)

    # Challenge score
    challenge_score = max(0, min(100, score - challenge_penalty))

    # Decision: BUY passes challenge if adjusted score still above threshold
    # Using a lower threshold than buy_score_min since this is a secondary check
    passed = challenge_score >= 45

    if passed:
        recommendation = (
            f"BUY challenge PASSED (challenge score: {challenge_score:.0f}). "
            f"Deciding signal: {deciding_signal}. "
            f"{len(counter_args)} counter-argument(s) considered."
        )
    else:
        recommendation = (
            f"BUY challenge FAILED (challenge score: {challenge_score:.0f} < 45). "
            f"Downgrading to HOLD. Counter-arguments too strong."
        )

    return {
        "passed": passed,
        "deciding_signal": deciding_signal,
        "counter_arguments": counter_args,
        "challenge_score": round(challenge_score, 1),
        "recommendation": recommendation,
    }


def _identify_deciding_signal(signals: dict, anomaly_flags: list[str]) -> str:
    """Identify which signal was the primary driver of the BUY verdict."""
    # Priority order for deciding signal
    if "breakout_high_volume" in anomaly_flags:
        return "Breakout with high volume confirmation"
    if "ema_golden_cross" in anomaly_flags:
        return "EMA Golden Cross (50/200)"
    if "macd_crossover" in anomaly_flags:
        return "MACD bullish crossover"

    macd = signals.get("macd", {})
    if macd.get("bullish") is True and "Crossover" in macd.get("label", ""):
        return "MACD bullish crossover"

    ema = signals.get("ema_trend", {})
    if "uptrend" in ema.get("label", "").lower():
        return "EMA trend alignment (bullish)"

    rsi = signals.get("rsi", {})
    if rsi.get("value", 50) < 35:
        return "RSI oversold bounce"

    if "volume_spike" in anomaly_flags:
        return "Volume spike anomaly"

    return "Composite score threshold"


# ---------------------------------------------------------------------------
# Post-mortem evaluation
# ---------------------------------------------------------------------------

def evaluate_past_signals(lookback_days: int = 7, price_getter=None) -> list[dict]:
    """
    Evaluate past BUY/SELL signals after their holding period has elapsed.

    Returns list of evaluation results for each expired signal.
    """
    from memory.db import get_conn

    cutoff_date = (date.today() - timedelta(days=lookback_days)).isoformat()

    with get_conn() as conn:
        # Find pipeline results that haven't been evaluated yet
        rows = conn.execute("""
            SELECT pr.symbol, pr.run_date, pr.final_verdict, pr.final_score,
                   pr.price_at_run, pr.anomaly_flags
            FROM pipeline_results pr
            LEFT JOIN trading_journal tj
                ON pr.symbol = tj.symbol AND pr.run_date = tj.signal_date
            WHERE pr.run_date <= ?
              AND pr.final_verdict IN ('BUY', 'SELL')
              AND tj.symbol IS NULL
        """, (cutoff_date,)).fetchall()

    results = []
    for row in rows:
        row = dict(row)
        symbol = row["symbol"]
        price_at_signal = row.get("price_at_run")

        if not price_at_signal or not price_getter:
            continue

        try:
            current_price = price_getter(symbol)
        except Exception:
            continue

        if current_price is None:
            continue

        actual_move_pct = ((current_price - price_at_signal) / price_at_signal) * 100

        verdict = row["final_verdict"]
        if verdict == "BUY":
            was_correct = actual_move_pct > 0
        else:  # SELL
            was_correct = actual_move_pct < 0

        # Determine pattern
        if abs(actual_move_pct) < 1:
            pattern = "FLAT — no significant move"
        elif was_correct and abs(actual_move_pct) > 5:
            pattern = "STRONG_FOLLOW_THROUGH"
        elif was_correct:
            pattern = "WEAK_FOLLOW_THROUGH"
        elif not was_correct and abs(actual_move_pct) > 5:
            pattern = "REVERSAL — signal was wrong"
        else:
            pattern = "MINOR_COUNTER_MOVE"

        # Post-mortem note
        if was_correct:
            post_mortem = f"{verdict} signal was correct. Stock moved {actual_move_pct:+.1f}%."
        else:
            post_mortem = (
                f"{verdict} signal was WRONG. Stock moved {actual_move_pct:+.1f}% "
                f"(expected {'up' if verdict == 'BUY' else 'down'})."
            )

        journal_entry = {
            "symbol": symbol,
            "signal_date": row["run_date"],
            "signal_verdict": verdict,
            "signal_score": row.get("final_score"),
            "price_at_signal": price_at_signal,
            "price_at_evaluation": current_price,
            "actual_move_pct": round(actual_move_pct, 2),
            "was_correct": was_correct,
            "pattern_detected": pattern,
            "post_mortem": post_mortem,
        }

        # Save to trading_journal
        _save_journal_entry(journal_entry)
        results.append(journal_entry)

    return results


def _save_journal_entry(entry: dict) -> None:
    """Save a journal entry to the trading_journal table."""
    try:
        from memory.db import get_conn
        with get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trading_journal (
                    journal_date, symbol, signal_date, signal_verdict,
                    signal_score, price_at_signal, price_at_evaluation,
                    actual_move_pct, was_correct, post_mortem, pattern_detected
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                date.today().isoformat(),
                entry["symbol"],
                entry["signal_date"],
                entry["signal_verdict"],
                entry.get("signal_score"),
                entry.get("price_at_signal"),
                entry.get("price_at_evaluation"),
                entry.get("actual_move_pct"),
                1 if entry["was_correct"] else 0,
                entry.get("post_mortem"),
                entry.get("pattern_detected"),
            ))
    except Exception as e:
        logger.error(f"Failed to save journal entry for {entry.get('symbol')}: {e}")

"""
confidence_engine.py — Mathematical confidence calculator.

Derives confidence from:
  1. Signal agreement (how many technical signals agree with the verdict)
  2. Anomaly strength (number and severity of anomaly triggers)
  3. Historical accuracy (past prediction hit rate for this stock)
  4. ML probability (if available, the classifier's predicted probability)
  5. Trend strength (ADX-based regime strength)

Rules:
- NEVER uses LLM generation for confidence. Pure math only.
- Output: 0–100 score + human-readable label.
- Board Room cannot modify confidence scores.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Weights (must sum to 1.0)
# ---------------------------------------------------------------------------

WEIGHTS = {
    "signal_agreement":   0.30,
    "anomaly_strength":   0.15,
    "historical_accuracy": 0.20,
    "ml_probability":     0.20,
    "trend_strength":     0.15,
}


# ---------------------------------------------------------------------------
# Component scorers (each returns 0–100)
# ---------------------------------------------------------------------------

def _score_signal_agreement(
    verdict: str,
    rsi_bullish: Optional[bool],
    macd_bullish: Optional[bool],
    ema_trend: str,
    bb_position: Optional[float],
    volume_notable: bool,
) -> float:
    """
    How many technical signals agree with the final verdict?
    Returns 0–100.
    """
    is_buy = verdict == "BUY"
    is_sell = verdict == "SELL"

    agreements = 0
    total_signals = 0

    # RSI
    if rsi_bullish is not None:
        total_signals += 1
        if (is_buy and rsi_bullish) or (is_sell and not rsi_bullish):
            agreements += 1

    # MACD
    if macd_bullish is not None:
        total_signals += 1
        if (is_buy and macd_bullish) or (is_sell and not macd_bullish):
            agreements += 1

    # EMA trend
    if ema_trend and ema_trend != "unknown":
        total_signals += 1
        bullish_trends = {"strong_uptrend", "uptrend"}
        bearish_trends = {"strong_downtrend", "downtrend"}
        if (is_buy and ema_trend in bullish_trends) or (is_sell and ema_trend in bearish_trends):
            agreements += 1

    # Bollinger %B
    if bb_position is not None:
        total_signals += 1
        # Buy signal confirmed if price near lower band (oversold), sell if near upper
        if (is_buy and bb_position < 0.3) or (is_sell and bb_position > 0.7):
            agreements += 1

    # Volume confirmation
    if volume_notable:
        total_signals += 1
        agreements += 1  # notable volume confirms any signal

    if total_signals == 0:
        return 50.0  # neutral

    return (agreements / total_signals) * 100


def _score_anomaly_strength(anomaly_flags: list[str]) -> float:
    """
    Anomaly triggers boost confidence (more anomalies = more unusual = higher conviction).
    Returns 0–100.
    """
    if not anomaly_flags:
        return 30.0  # base — no anomalies is low but not zero

    # Each anomaly adds confidence (diminishing returns)
    count = len(anomaly_flags)
    # 1 anomaly = 50, 2 = 70, 3 = 82, 4+ = 90+
    score = 30.0 + (70.0 * (1.0 - (1.0 / (1.0 + count * 0.8))))
    return min(score, 95.0)


def _score_historical_accuracy(
    stock_hit_rate: Optional[float],
    overall_hit_rate: Optional[float],
) -> float:
    """
    Past prediction accuracy for this stock and overall.
    Returns 0–100.
    """
    if stock_hit_rate is not None and stock_hit_rate >= 0:
        # Weight stock-specific more if available
        if overall_hit_rate is not None:
            return stock_hit_rate * 0.7 + overall_hit_rate * 0.3
        return stock_hit_rate
    elif overall_hit_rate is not None:
        return overall_hit_rate
    else:
        return 50.0  # no history — neutral


def _score_ml_probability(ml_prob: Optional[float]) -> float:
    """
    ML classifier's predicted probability (0–1) → confidence (0–100).
    Only counts if ML is available and the data guard passed.
    """
    if ml_prob is None:
        return 50.0  # neutral when ML unavailable
    # Scale: 0.5 = neutral, 0.0 or 1.0 = max confidence in direction
    return abs(ml_prob - 0.5) * 200  # 0.5→0, 1.0→100, 0.0→100


def _score_trend_strength(adx_value: Optional[float]) -> float:
    """
    ADX-based trend strength.
    Returns 0–100.
    """
    if adx_value is None:
        return 40.0  # weak default
    # ADX < 15 = no trend (low confidence), > 40 = strong trend
    if adx_value < 15:
        return 20.0
    elif adx_value < 20:
        return 35.0
    elif adx_value < 25:
        return 50.0
    elif adx_value < 35:
        return 70.0
    elif adx_value < 50:
        return 85.0
    else:
        return 95.0


# ---------------------------------------------------------------------------
# Main confidence calculator
# ---------------------------------------------------------------------------

def compute_confidence(
    verdict: str,
    rsi_bullish: Optional[bool] = None,
    macd_bullish: Optional[bool] = None,
    ema_trend: str = "unknown",
    bb_position: Optional[float] = None,
    volume_notable: bool = False,
    anomaly_flags: list[str] = None,
    stock_hit_rate: Optional[float] = None,
    overall_hit_rate: Optional[float] = None,
    ml_probability: Optional[float] = None,
    adx_value: Optional[float] = None,
) -> dict:
    """
    Compute a mathematical confidence score for a pipeline recommendation.

    Returns:
        {
            "confidence_score": float (0–100),
            "confidence_label": str ("LOW" | "MODERATE" | "HIGH" | "VERY_HIGH"),
            "components": {
                "signal_agreement": float,
                "anomaly_strength": float,
                "historical_accuracy": float,
                "ml_probability": float,
                "trend_strength": float,
            }
        }
    """
    if anomaly_flags is None:
        anomaly_flags = []

    # HOLD verdicts always get moderate confidence (no strong action)
    if verdict == "HOLD":
        return {
            "confidence_score": 45.0,
            "confidence_label": "MODERATE",
            "components": {
                "signal_agreement": 50.0,
                "anomaly_strength": 30.0,
                "historical_accuracy": 50.0,
                "ml_probability": 50.0,
                "trend_strength": 40.0,
            },
        }

    # Compute components
    components = {
        "signal_agreement": round(_score_signal_agreement(
            verdict, rsi_bullish, macd_bullish, ema_trend, bb_position, volume_notable
        ), 1),
        "anomaly_strength": round(_score_anomaly_strength(anomaly_flags), 1),
        "historical_accuracy": round(_score_historical_accuracy(
            stock_hit_rate, overall_hit_rate
        ), 1),
        "ml_probability": round(_score_ml_probability(ml_probability), 1),
        "trend_strength": round(_score_trend_strength(adx_value), 1),
    }

    # Weighted average
    score = sum(
        components[k] * WEIGHTS[k]
        for k in WEIGHTS
    )
    score = round(max(0.0, min(100.0, score)), 1)

    # Label
    if score >= 75:
        label = "VERY_HIGH"
    elif score >= 55:
        label = "HIGH"
    elif score >= 35:
        label = "MODERATE"
    else:
        label = "LOW"

    return {
        "confidence_score": score,
        "confidence_label": label,
        "components": components,
    }

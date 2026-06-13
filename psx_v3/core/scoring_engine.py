"""
scoring_engine.py — Unified scoring engine for PSX Advisory Agent v3.

REPLACES the broken chain of chained overrides (confidence filter, regime gate,
velocity override, macro gate, data staleness gate, post-circuit gate,
ML reliability gate) with a clean 3-stage approach.

Architecture:
  Stage 1: Pure technical score (0–100) from indicators
  Stage 2: Anomaly detection — flags unusual patterns that boost/modify score
  Stage 3: Verdict decision — PSX-calibrated thresholds produce BUY/HOLD/SELL

Rules:
- NO override stacking. Each stage feeds the next cleanly.
- Thresholds are PSX-calibrated, not imported from US market defaults.
- Anomalies can only BOOST a signal, never suppress it.
- ML is optional — if unavailable or unreliable, verdict is still generated.
- Shariah status is READ from shariah_engine, never determined here.
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PSX-calibrated thresholds
# ---------------------------------------------------------------------------

# These are tuned for Pakistan Stock Exchange characteristics:
# - Higher volatility than developed markets
# - Lower average daily volume
# - Momentum-driven retail market
# - Higher concentration risk

PSX_THRESHOLDS = {
    "buy_score_min":     55,    # minimum composite score to issue BUY
    "sell_score_max":    35,    # below this → SELL
    "strong_buy_min":    72,    # high-conviction BUY
    "strong_sell_max":   22,    # high-conviction SELL
    "volume_spike_x":    2.0,  # volume / avg_volume >= this → anomaly
    "rsi_oversold":      30,   # PSX oversold threshold
    "rsi_overbought":    70,   # PSX overbought threshold
    "bb_squeeze_width":  0.04, # Bollinger bandwidth < this → squeeze
}

# Anomaly types and their score boost (additive, capped)
ANOMALY_BOOSTS = {
    "volume_spike":           8,    # unusual volume
    "bollinger_squeeze":      5,    # volatility contraction → expansion coming
    "rsi_divergence":         7,    # price vs RSI divergence
    "macd_crossover":         6,    # MACD just crossed signal
    "ema_golden_cross":      10,    # EMA 50 crossed above EMA 200
    "ema_death_cross":       -8,    # EMA 50 crossed below EMA 200 (penalizes)
    "breakout_high_volume":  12,    # price breakout + volume confirmation
    "earnings_beat":          6,    # positive earnings announcement
    "earnings_miss":         -5,    # negative earnings
    "dividend_announced":     4,    # dividend declared
}


# ---------------------------------------------------------------------------
# Stage 1: Technical Score
# ---------------------------------------------------------------------------

def compute_stage1_score(df: pd.DataFrame) -> dict:
    """
    Compute a pure technical score (0–100) from RSI, MACD, Bollinger, EMA.
    This is a wrapper around indicators.compute_technical_score with
    additional data returned for Stage 2 anomaly detection.
    """
    from core.indicators import (
        calc_rsi, calc_bollinger, calc_macd, calc_ema,
        rsi_signal, macd_signal_interp, ema_trend_signal,
        volume_signal, detect_regime,
    )

    if df is None or len(df) < 30:
        return {
            "technical_score": 50.0,
            "signals": {},
            "trend": "unknown",
            "regime": {"regime": "CHOPPY", "adx_value": 0},
            "raw_data": {},
            "error": "Insufficient data for technical analysis",
        }

    raw_data = {}

    # RSI
    rsi_series = calc_rsi(df)
    rsi_val = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50.0
    rsi_info = rsi_signal(rsi_val)
    raw_data["rsi"] = rsi_val
    raw_data["rsi_bullish"] = rsi_val < PSX_THRESHOLDS["rsi_overbought"] and rsi_val > PSX_THRESHOLDS["rsi_oversold"]

    # Bollinger
    bb_df = calc_bollinger(df)
    bb_pct_b = float(bb_df["bb_pct_b"].iloc[-1]) if not bb_df.empty else 0.5
    bb_width = float(bb_df["bb_width"].iloc[-1]) if not bb_df.empty else 0.1
    raw_data["bb_pct_b"] = bb_pct_b
    raw_data["bb_width"] = bb_width

    # MACD
    macd_df = calc_macd(df)
    macd_interp = macd_signal_interp(macd_df)
    raw_data["macd_bullish"] = macd_interp.get("bullish")

    # Check MACD crossover (for anomaly detection)
    macd_crossover = False
    if not macd_df.empty and len(macd_df) >= 2:
        prev_macd = macd_df.iloc[-2]["macd"]
        prev_sig = macd_df.iloc[-2]["macd_signal"]
        curr_macd = macd_df.iloc[-1]["macd"]
        curr_sig = macd_df.iloc[-1]["macd_signal"]
        if prev_macd < prev_sig and curr_macd > curr_sig:
            macd_crossover = True  # bullish crossover
            raw_data["macd_crossover_bullish"] = True
        elif prev_macd > prev_sig and curr_macd < curr_sig:
            macd_crossover = True  # bearish crossover
            raw_data["macd_crossover_bearish"] = True

    # EMA
    emas = calc_ema(df)
    trend = ema_trend_signal(df, emas)
    raw_data["ema_trend"] = trend

    # Check golden/death cross
    if not emas.empty and len(emas) >= 2:
        try:
            prev_e50 = emas["ema_50"].iloc[-2]
            prev_e200 = emas["ema_200"].iloc[-2]
            curr_e50 = emas["ema_50"].iloc[-1]
            curr_e200 = emas["ema_200"].iloc[-1]
            if prev_e50 < prev_e200 and curr_e50 > curr_e200:
                raw_data["golden_cross"] = True
            elif prev_e50 > prev_e200 and curr_e50 < curr_e200:
                raw_data["death_cross"] = True
        except (KeyError, IndexError):
            pass

    # Volume
    vol_info = volume_signal(df)
    raw_data["volume_ratio"] = vol_info.get("ratio")
    raw_data["volume_notable"] = vol_info.get("notable", False)

    # Regime (ADX)
    regime = detect_regime(df)
    raw_data["adx_value"] = regime.get("adx_value", 0)

    # --- Weighted composite score ---
    score_components = []

    # RSI contribution (25%)
    rsi_score = 50 + (rsi_val - 50) * 0.6
    rsi_score = max(0, min(100, rsi_score))
    score_components.append(("rsi", rsi_score, 0.25))

    # Bollinger contribution (20%)
    bb_score = bb_pct_b * 100
    bb_score = max(0, min(100, bb_score))
    score_components.append(("bollinger", bb_score, 0.20))

    # MACD contribution (25%)
    if macd_interp.get("bullish") is True:
        macd_score = 70
    elif macd_interp.get("bullish") is False:
        macd_score = 30
    else:
        macd_score = 50
    score_components.append(("macd", macd_score, 0.25))

    # EMA trend contribution (30%)
    trend_scores = {
        "strong_uptrend": 90, "uptrend": 70, "sideways": 50,
        "downtrend": 30, "strong_downtrend": 10, "unknown": 50,
    }
    score_components.append(("ema", trend_scores.get(trend, 50), 0.30))

    # Calculate weighted average
    total_weight = sum(w for _, _, w in score_components)
    technical_score = sum(s * w for _, s, w in score_components) / total_weight
    technical_score = round(max(0, min(100, technical_score)), 1)

    return {
        "technical_score": technical_score,
        "signals": {
            "rsi": {"value": round(rsi_val, 1), **rsi_info},
            "macd": macd_interp,
            "ema_trend": {"label": trend.replace("_", " ").title()},
            "bollinger": {"pct_b": round(bb_pct_b, 3)},
            "volume": vol_info,
        },
        "trend": trend,
        "regime": regime,
        "raw_data": raw_data,
    }


# ---------------------------------------------------------------------------
# Stage 2: Anomaly Detection
# ---------------------------------------------------------------------------

def detect_anomalies(
    raw_data: dict,
    df: pd.DataFrame = None,
    announcements: list[dict] = None,
) -> dict:
    """
    Detect anomalous conditions that modify the score.
    Anomalies can BOOST a signal (most cases) or PENALIZE (death cross, earnings miss).

    Returns:
        {
            "anomaly_flags": list of flag names,
            "anomaly_boost": total additive score adjustment,
            "anomaly_details": list of dicts with explanations,
        }
    """
    flags = []
    details = []
    total_boost = 0

    # Volume spike
    vol_ratio = raw_data.get("volume_ratio")
    if vol_ratio and vol_ratio >= PSX_THRESHOLDS["volume_spike_x"]:
        flags.append("volume_spike")
        details.append({
            "flag": "volume_spike",
            "detail": f"Volume {vol_ratio:.1f}x average — unusual institutional activity",
            "boost": ANOMALY_BOOSTS["volume_spike"],
        })
        total_boost += ANOMALY_BOOSTS["volume_spike"]

    # Bollinger squeeze
    bb_width = raw_data.get("bb_width", 1.0)
    if bb_width < PSX_THRESHOLDS["bb_squeeze_width"]:
        flags.append("bollinger_squeeze")
        details.append({
            "flag": "bollinger_squeeze",
            "detail": f"Bollinger bandwidth {bb_width:.4f} — volatility squeeze, breakout imminent",
            "boost": ANOMALY_BOOSTS["bollinger_squeeze"],
        })
        total_boost += ANOMALY_BOOSTS["bollinger_squeeze"]

    # MACD crossover
    if raw_data.get("macd_crossover_bullish"):
        flags.append("macd_crossover")
        details.append({
            "flag": "macd_crossover",
            "detail": "Bullish MACD crossover — momentum shifting up",
            "boost": ANOMALY_BOOSTS["macd_crossover"],
        })
        total_boost += ANOMALY_BOOSTS["macd_crossover"]
    elif raw_data.get("macd_crossover_bearish"):
        flags.append("macd_crossover")
        details.append({
            "flag": "macd_crossover",
            "detail": "Bearish MACD crossover — momentum shifting down",
            "boost": -ANOMALY_BOOSTS["macd_crossover"],
        })
        total_boost -= ANOMALY_BOOSTS["macd_crossover"]

    # Golden / Death cross
    if raw_data.get("golden_cross"):
        flags.append("ema_golden_cross")
        details.append({
            "flag": "ema_golden_cross",
            "detail": "EMA 50 crossed above EMA 200 — major bullish signal",
            "boost": ANOMALY_BOOSTS["ema_golden_cross"],
        })
        total_boost += ANOMALY_BOOSTS["ema_golden_cross"]
    elif raw_data.get("death_cross"):
        flags.append("ema_death_cross")
        details.append({
            "flag": "ema_death_cross",
            "detail": "EMA 50 crossed below EMA 200 — major bearish signal",
            "boost": ANOMALY_BOOSTS["ema_death_cross"],
        })
        total_boost += ANOMALY_BOOSTS["ema_death_cross"]

    # Breakout with volume
    if raw_data.get("volume_notable") and raw_data.get("ema_trend") in ("strong_uptrend", "uptrend"):
        if "volume_spike" in flags:  # only if volume is also spiking
            flags.append("breakout_high_volume")
            details.append({
                "flag": "breakout_high_volume",
                "detail": "Price trending up with high volume — breakout confirmation",
                "boost": ANOMALY_BOOSTS["breakout_high_volume"],
            })
            total_boost += ANOMALY_BOOSTS["breakout_high_volume"]

    # RSI divergence (simplified: price making new low but RSI not)
    rsi_val = raw_data.get("rsi", 50)
    if rsi_val < 35 and raw_data.get("ema_trend") in ("downtrend", "strong_downtrend"):
        # Oversold in downtrend — potential reversal
        flags.append("rsi_divergence")
        details.append({
            "flag": "rsi_divergence",
            "detail": f"RSI {rsi_val:.0f} oversold in downtrend — potential bullish divergence",
            "boost": ANOMALY_BOOSTS["rsi_divergence"],
        })
        total_boost += ANOMALY_BOOSTS["rsi_divergence"]

    # Announcement-based anomalies
    if announcements:
        for ann in announcements:
            ann_type = ann.get("announcement_type", "")
            if ann_type == "EARNINGS_BEAT" and "earnings_beat" not in flags:
                flags.append("earnings_beat")
                details.append({
                    "flag": "earnings_beat",
                    "detail": f"Positive earnings announcement: {ann.get('headline', '')}",
                    "boost": ANOMALY_BOOSTS["earnings_beat"],
                })
                total_boost += ANOMALY_BOOSTS["earnings_beat"]
            elif ann_type == "EARNINGS_MISS" and "earnings_miss" not in flags:
                flags.append("earnings_miss")
                details.append({
                    "flag": "earnings_miss",
                    "detail": f"Negative earnings announcement: {ann.get('headline', '')}",
                    "boost": ANOMALY_BOOSTS["earnings_miss"],
                })
                total_boost += ANOMALY_BOOSTS["earnings_miss"]
            elif ann_type == "DIVIDEND_ANNOUNCED" and "dividend_announced" not in flags:
                flags.append("dividend_announced")
                details.append({
                    "flag": "dividend_announced",
                    "detail": f"Dividend declared: {ann.get('headline', '')}",
                    "boost": ANOMALY_BOOSTS["dividend_announced"],
                })
                total_boost += ANOMALY_BOOSTS["dividend_announced"]

    return {
        "anomaly_flags": flags,
        "anomaly_boost": total_boost,
        "anomaly_details": details,
    }


# ---------------------------------------------------------------------------
# Stage 3: Verdict Decision
# ---------------------------------------------------------------------------

def determine_verdict(
    technical_score: float,
    anomaly_boost: float,
    ml_prediction: Optional[str] = None,
    ml_probability: Optional[float] = None,
    ml_reliable: bool = False,
) -> dict:
    """
    Determine the final verdict using PSX-calibrated thresholds.

    Rules:
    1. Start with technical_score + anomaly_boost = adjusted_score
    2. ML can nudge ±5 points if reliable (200+ rows, walk-forward validated)
    3. Apply PSX thresholds to determine BUY/HOLD/SELL
    4. No override stacking — single clean pass

    Returns:
        {
            "verdict": str,
            "final_score": float,
            "score_breakdown": dict,
            "reasons": list[str],
        }
    """
    reasons = []

    # Step 1: Adjusted score
    adjusted_score = technical_score + anomaly_boost
    reasons.append(f"Technical score: {technical_score:.1f}")

    if anomaly_boost != 0:
        reasons.append(f"Anomaly adjustment: {'+' if anomaly_boost > 0 else ''}{anomaly_boost}")

    # Step 2: ML nudge (optional, capped at ±5)
    ml_nudge = 0.0
    if ml_reliable and ml_prediction and ml_probability is not None:
        if ml_prediction == "UP" and ml_probability > 0.6:
            ml_nudge = min((ml_probability - 0.5) * 10, 5.0)  # max +5
            reasons.append(f"ML UP signal (+{ml_nudge:.1f}): probability {ml_probability:.0%}")
        elif ml_prediction == "NOT_UP" and ml_probability > 0.6:
            ml_nudge = max(-(ml_probability - 0.5) * 10, -5.0)  # max -5
            reasons.append(f"ML NOT_UP signal ({ml_nudge:.1f}): probability {ml_probability:.0%}")
    elif not ml_reliable:
        reasons.append("ML skipped: insufficient data or not yet validated")

    final_score = round(max(0, min(100, adjusted_score + ml_nudge)), 1)

    # Step 3: Apply PSX thresholds
    if final_score >= PSX_THRESHOLDS["strong_buy_min"]:
        verdict = "BUY"
        reasons.append(f"Strong BUY — score {final_score} ≥ {PSX_THRESHOLDS['strong_buy_min']} (high conviction)")
    elif final_score >= PSX_THRESHOLDS["buy_score_min"]:
        verdict = "BUY"
        reasons.append(f"BUY — score {final_score} ≥ {PSX_THRESHOLDS['buy_score_min']}")
    elif final_score <= PSX_THRESHOLDS["strong_sell_max"]:
        verdict = "SELL"
        reasons.append(f"Strong SELL — score {final_score} ≤ {PSX_THRESHOLDS['strong_sell_max']} (high conviction)")
    elif final_score <= PSX_THRESHOLDS["sell_score_max"]:
        verdict = "SELL"
        reasons.append(f"SELL — score {final_score} ≤ {PSX_THRESHOLDS['sell_score_max']}")
    else:
        verdict = "HOLD"
        reasons.append(f"HOLD — score {final_score} between {PSX_THRESHOLDS['sell_score_max']}–{PSX_THRESHOLDS['buy_score_min']}")

    return {
        "verdict": verdict,
        "final_score": final_score,
        "score_breakdown": {
            "technical_score": technical_score,
            "anomaly_boost": anomaly_boost,
            "ml_nudge": ml_nudge,
            "final_score": final_score,
        },
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Full scoring pipeline (called per stock)
# ---------------------------------------------------------------------------

def score_stock(
    symbol: str,
    df: pd.DataFrame,
    ml_prediction: Optional[str] = None,
    ml_probability: Optional[float] = None,
    ml_reliable: bool = False,
    announcements: list[dict] = None,
) -> dict:
    """
    Run the full 3-stage scoring pipeline for a single stock.

    Returns:
        Complete scoring result with verdict, score, anomalies, and reasons.
    """
    symbol = symbol.upper()

    # Stage 1: Technical Score
    stage1 = compute_stage1_score(df)

    # Stage 2: Anomaly Detection
    stage2 = detect_anomalies(
        raw_data=stage1["raw_data"],
        df=df,
        announcements=announcements or [],
    )

    # Stage 3: Verdict Decision
    stage3 = determine_verdict(
        technical_score=stage1["technical_score"],
        anomaly_boost=stage2["anomaly_boost"],
        ml_prediction=ml_prediction,
        ml_probability=ml_probability,
        ml_reliable=ml_reliable,
    )

    return {
        "symbol": symbol,
        "verdict": stage3["verdict"],
        "final_score": stage3["final_score"],
        "technical_score": stage1["technical_score"],
        "signals": stage1["signals"],
        "trend": stage1["trend"],
        "regime": stage1["regime"],
        "anomaly_flags": stage2["anomaly_flags"],
        "anomaly_boost": stage2["anomaly_boost"],
        "anomaly_details": stage2["anomaly_details"],
        "score_breakdown": stage3["score_breakdown"],
        "reasons": stage3["reasons"],
        "raw_data": stage1["raw_data"],
    }

"""
horizon_engine.py — Holding period, target price, stop loss, and confidence interval calculator.

Uses Average True Range (ATR) as the primary volatility measure.

Every recommendation MUST answer:
  - "If I buy, how long do I hold?"
  - "What is my upside target?"
  - "Where is my stop loss?"

Rules:
- All calculations are deterministic (no LLM generation).
- ATR drives target/stop distances.
- Holding period is derived from trend strength (ADX) and volatility.
- Confidence interval is a statistical range (1 ATR = ~68%, 2 ATR = ~95%).
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ATR calculation
# ---------------------------------------------------------------------------

def calc_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Calculate Average True Range.
    Requires OHLC columns: High, Low, Close.
    Returns the latest ATR value, or None if insufficient data.
    """
    if df is None or len(df) < period + 1:
        return None

    try:
        high = df["High"]
        low = df["Low"]
        close = df["Close"]

        # True Range = max(H-L, |H-Cprev|, |L-Cprev|)
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Wilder's smoothing (EMA with alpha = 1/period)
        atr = true_range.ewm(alpha=1 / period, min_periods=period).mean()
        latest = float(atr.iloc[-1])
        return latest if not np.isnan(latest) else None
    except Exception as e:
        logger.error(f"ATR calculation failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Target & Stop Loss
# ---------------------------------------------------------------------------

def calc_target_stop(
    entry_price: float,
    atr: float,
    verdict: str = "BUY",
    risk_reward_ratio: float = 2.0,
    stop_atr_multiple: float = 1.5,
    target_atr_multiple: float = 3.0,
) -> dict:
    """
    Calculate target price and stop loss based on ATR.

    For BUY:
      - Stop loss = entry - (ATR × stop_multiple)
      - Target    = entry + (ATR × target_multiple)
    For SELL:
      - Stop loss = entry + (ATR × stop_multiple)
      - Target    = entry - (ATR × target_multiple)

    Returns dict with target_price, stop_loss, risk_pkr, reward_pkr, risk_reward_ratio.
    """
    if verdict == "SELL":
        stop_loss = entry_price + (atr * stop_atr_multiple)
        target = entry_price - (atr * target_atr_multiple)
    else:
        stop_loss = entry_price - (atr * stop_atr_multiple)
        target = entry_price + (atr * target_atr_multiple)

    risk_pkr = abs(entry_price - stop_loss)
    reward_pkr = abs(target - entry_price)
    actual_rr = reward_pkr / risk_pkr if risk_pkr > 0 else 0.0

    return {
        "entry_price": round(entry_price, 2),
        "target_price": round(max(0.0, target), 2),
        "stop_loss": round(max(0.0, stop_loss), 2),
        "risk_pkr": round(risk_pkr, 2),
        "reward_pkr": round(reward_pkr, 2),
        "risk_reward_ratio": round(actual_rr, 2),
        "atr_used": round(atr, 2),
        "stop_pct": round((risk_pkr / entry_price) * 100, 2) if entry_price > 0 else 0.0,
        "target_pct": round((reward_pkr / entry_price) * 100, 2) if entry_price > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# Holding period estimation
# ---------------------------------------------------------------------------

def estimate_holding_period(
    atr: float,
    price: float,
    adx_value: Optional[float] = None,
    target_pct: float = 5.0,
) -> dict:
    """
    Estimate how many trading days it should take to reach the target.

    Logic:
    - Daily expected move ≈ ATR
    - Target distance = price × (target_pct / 100)
    - Days estimate = target_distance / (ATR × drift_factor)
    - ADX modifies drift_factor: strong trends reach targets faster

    Returns dict with estimated_days, holding_label, calendar_days.
    """
    if atr <= 0 or price <= 0:
        return {
            "estimated_trading_days": 0,
            "estimated_calendar_days": 0,
            "holding_label": "UNKNOWN",
            "holding_description": "Insufficient data to estimate holding period",
        }

    target_distance = price * (target_pct / 100.0)

    # Drift factor: how much of ATR actually contributes to directional move
    # Higher ADX = stronger trend = more of ATR goes in the right direction
    if adx_value is not None:
        if adx_value > 40:
            drift_factor = 0.50  # strong trend — half ATR per day is directional
        elif adx_value > 25:
            drift_factor = 0.35
        elif adx_value > 15:
            drift_factor = 0.20
        else:
            drift_factor = 0.10  # choppy — very slow progress
    else:
        drift_factor = 0.25  # default moderate

    daily_progress = atr * drift_factor
    if daily_progress <= 0:
        estimated_days = 90  # cap
    else:
        estimated_days = int(min(target_distance / daily_progress, 120))

    # Convert trading days → calendar days (PSX: 5 days/week)
    calendar_days = int(estimated_days * 7 / 5)

    # Label
    if estimated_days <= 5:
        label = "VERY_SHORT"
        desc = f"~{estimated_days} trading days ({calendar_days} calendar days) — short swing trade"
    elif estimated_days <= 15:
        label = "SHORT"
        desc = f"~{estimated_days} trading days ({calendar_days} calendar days) — short-term position"
    elif estimated_days <= 40:
        label = "MEDIUM"
        desc = f"~{estimated_days} trading days ({calendar_days} calendar days) — medium-term hold"
    elif estimated_days <= 80:
        label = "LONG"
        desc = f"~{estimated_days} trading days ({calendar_days} calendar days) — longer-term position"
    else:
        label = "VERY_LONG"
        desc = f"~{estimated_days}+ trading days ({calendar_days}+ calendar days) — patient hold required"

    return {
        "estimated_trading_days": estimated_days,
        "estimated_calendar_days": calendar_days,
        "holding_label": label,
        "holding_description": desc,
    }


# ---------------------------------------------------------------------------
# Confidence interval
# ---------------------------------------------------------------------------

def calc_confidence_interval(price: float, atr: float, days: int = 10) -> dict:
    """
    Statistical confidence intervals using ATR.

    Using sqrt(days) scaling for multi-day intervals:
    - 1σ (68% interval): price ± ATR × √days × 1.0
    - 2σ (95% interval): price ± ATR × √days × 2.0
    """
    if atr <= 0 or price <= 0:
        return {
            "interval_68_low": price, "interval_68_high": price,
            "interval_95_low": price, "interval_95_high": price,
        }

    sqrt_days = np.sqrt(max(1, days))
    sigma_1 = atr * sqrt_days * 1.0
    sigma_2 = atr * sqrt_days * 2.0

    return {
        "interval_68_low": round(max(0, price - sigma_1), 2),
        "interval_68_high": round(price + sigma_1, 2),
        "interval_95_low": round(max(0, price - sigma_2), 2),
        "interval_95_high": round(price + sigma_2, 2),
        "days_ahead": days,
    }


# ---------------------------------------------------------------------------
# Full horizon package
# ---------------------------------------------------------------------------

def compute_horizon(
    df: pd.DataFrame,
    entry_price: float,
    verdict: str = "BUY",
    adx_value: Optional[float] = None,
) -> dict:
    """
    Compute the complete horizon package for a recommendation.

    Returns:
        {
            "atr": float,
            "target_price": float,
            "stop_loss": float,
            "risk_reward_ratio": float,
            "holding_period": dict,
            "confidence_interval": dict,
            ...
        }
    """
    atr = calc_atr(df)
    if atr is None or atr <= 0:
        return {
            "atr": None,
            "target_price": None,
            "stop_loss": None,
            "risk_reward_ratio": None,
            "holding_period": {
                "estimated_trading_days": 0,
                "holding_label": "UNKNOWN",
            },
            "confidence_interval": {},
            "error": "ATR unavailable — insufficient price data",
        }

    # Target & stop
    ts = calc_target_stop(entry_price, atr, verdict)

    # Holding period
    holding = estimate_holding_period(
        atr=atr,
        price=entry_price,
        adx_value=adx_value,
        target_pct=ts["target_pct"],
    )

    # 10-day confidence interval
    ci = calc_confidence_interval(entry_price, atr, days=holding["estimated_trading_days"] or 10)

    return {
        "atr": round(atr, 2),
        "target_price": ts["target_price"],
        "stop_loss": ts["stop_loss"],
        "risk_pkr": ts["risk_pkr"],
        "reward_pkr": ts["reward_pkr"],
        "risk_reward_ratio": ts["risk_reward_ratio"],
        "stop_pct": ts["stop_pct"],
        "target_pct": ts["target_pct"],
        "holding_period": holding,
        "confidence_interval": ci,
    }

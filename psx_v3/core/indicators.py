"""
indicators.py — Technical indicator calculations for PSX advisory.

Uses the `ta` library for RSI, Bollinger Bands, MACD.
All functions accept a pd.DataFrame with OHLCV columns.
"""

import logging
from typing import Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Relative Strength Index.
    Returns a Series of RSI values (0–100).
    """
    try:
        from ta.momentum import RSIIndicator
        rsi = RSIIndicator(close=df["Close"], window=period)
        return rsi.rsi()
    except Exception as e:
        logger.warning(f"RSI calculation failed: {e}")
        return pd.Series(dtype=float)


def rsi_signal(rsi_value: float) -> dict:
    """Interpret an RSI value."""
    if rsi_value >= 70:
        return {"label": "Overbought", "action": "caution", "color": "red"}
    elif rsi_value <= 30:
        return {"label": "Oversold",   "action": "opportunity", "color": "green"}
    elif rsi_value >= 60:
        return {"label": "Bullish",    "action": "hold/buy",    "color": "lightgreen"}
    elif rsi_value <= 40:
        return {"label": "Bearish",    "action": "hold/sell",   "color": "orange"}
    else:
        return {"label": "Neutral",    "action": "hold",        "color": "gray"}


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def calc_bollinger(
    df: pd.DataFrame, period: int = 20, std_dev: float = 2.0
) -> pd.DataFrame:
    """
    Bollinger Bands.
    Returns DataFrame with columns: bb_upper, bb_mid, bb_lower, bb_pct_b, bb_width.
    %B = (price - lower) / (upper - lower)
    """
    try:
        from ta.volatility import BollingerBands
        bb = BollingerBands(close=df["Close"], window=period, window_dev=std_dev)
        result = pd.DataFrame({
            "bb_upper":  bb.bollinger_hband(),
            "bb_mid":    bb.bollinger_mavg(),
            "bb_lower":  bb.bollinger_lband(),
            "bb_pct_b":  bb.bollinger_pband(),   # 0 = at lower, 1 = at upper
            "bb_width":  bb.bollinger_wband(),   # width indicator
        })
        return result
    except Exception as e:
        logger.warning(f"Bollinger calculation failed: {e}")
        return pd.DataFrame()


def bollinger_signal(pct_b: float) -> dict:
    """Interpret Bollinger %B value."""
    if pct_b > 1.0:
        return {"label": "Above Upper Band — Overbought",  "color": "red"}
    elif pct_b >= 0.8:
        return {"label": "Near Upper Band — Bullish",      "color": "orange"}
    elif pct_b >= 0.5:
        return {"label": "Upper Half — Mild Bullish",      "color": "lightgreen"}
    elif pct_b >= 0.2:
        return {"label": "Lower Half — Mild Bearish",      "color": "lightyellow"}
    elif pct_b >= 0.0:
        return {"label": "Near Lower Band — Bearish",      "color": "orange"}
    else:
        return {"label": "Below Lower Band — Oversold",    "color": "green"}


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def calc_macd(
    df: pd.DataFrame,
    fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """
    MACD, Signal Line, and Histogram.
    Returns DataFrame with columns: macd, macd_signal, macd_hist.
    """
    try:
        from ta.trend import MACD
        macd_obj = MACD(close=df["Close"], window_fast=fast, window_slow=slow, window_sign=signal)
        return pd.DataFrame({
            "macd":        macd_obj.macd(),
            "macd_signal": macd_obj.macd_signal(),
            "macd_hist":   macd_obj.macd_diff(),
        })
    except Exception as e:
        logger.warning(f"MACD calculation failed: {e}")
        return pd.DataFrame()


def macd_signal_interp(macd_df: pd.DataFrame) -> dict:
    """Interpret the most recent MACD bar."""
    if macd_df.empty:
        return {"label": "N/A", "action": "neutral", "bullish": None}
    last = macd_df.iloc[-1]
    prev = macd_df.iloc[-2] if len(macd_df) > 1 else last

    macd_val    = last["macd"]
    signal_val  = last["macd_signal"]
    hist_now    = last["macd_hist"]
    hist_prev   = prev["macd_hist"]

    # Crossover detection
    if prev["macd"] < prev["macd_signal"] and macd_val > signal_val:
        return {"label": "Bullish Crossover ↑", "action": "buy signal", "bullish": True}
    elif prev["macd"] > prev["macd_signal"] and macd_val < signal_val:
        return {"label": "Bearish Crossover ↓", "action": "sell signal", "bullish": False}
    elif macd_val > signal_val and hist_now > hist_prev:
        return {"label": "Bullish Momentum ↑",  "action": "hold/buy",   "bullish": True}
    elif macd_val > signal_val:
        return {"label": "Above Signal Line",    "action": "hold",       "bullish": True}
    elif hist_now < hist_prev:
        return {"label": "Bearish Momentum ↓",  "action": "caution",    "bullish": False}
    else:
        return {"label": "Below Signal Line",   "action": "hold/sell",  "bullish": False}


# ---------------------------------------------------------------------------
# Moving Averages
# ---------------------------------------------------------------------------

def calc_ema(df: pd.DataFrame, periods: list[int] = [20, 50, 200]) -> pd.DataFrame:
    """Calculate multiple EMAs."""
    result = pd.DataFrame(index=df.index)
    for p in periods:
        result[f"ema_{p}"] = df["Close"].ewm(span=p, adjust=False).mean()
    return result


def ema_trend_signal(df: pd.DataFrame, emas: pd.DataFrame) -> str:
    """
    Determine trend from EMA alignment.
    Returns: 'strong_uptrend', 'uptrend', 'downtrend', 'strong_downtrend', 'sideways'
    """
    last_close = df["Close"].iloc[-1]
    try:
        e20  = emas["ema_20"].iloc[-1]
        e50  = emas["ema_50"].iloc[-1]
        e200 = emas["ema_200"].iloc[-1]

        if last_close > e20 > e50 > e200:
            return "strong_uptrend"
        elif last_close > e50 > e200:
            return "uptrend"
        elif last_close < e20 < e50 < e200:
            return "strong_downtrend"
        elif last_close < e50 < e200:
            return "downtrend"
        else:
            return "sideways"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Volume Analysis
# ---------------------------------------------------------------------------

def volume_signal(df: pd.DataFrame, lookback: int = 20) -> dict:
    """Check if current volume is unusual."""
    if len(df) < lookback + 1:
        return {"label": "Insufficient data", "ratio": None}
    avg_vol   = df["Volume"].iloc[-(lookback+1):-1].mean()
    curr_vol  = df["Volume"].iloc[-1]
    ratio     = curr_vol / avg_vol if avg_vol > 0 else 1.0

    if ratio >= 2.0:
        return {"label": f"Very High Volume ({ratio:.1f}x avg)", "ratio": ratio, "notable": True}
    elif ratio >= 1.5:
        return {"label": f"High Volume ({ratio:.1f}x avg)",      "ratio": ratio, "notable": True}
    elif ratio <= 0.5:
        return {"label": f"Low Volume ({ratio:.1f}x avg)",       "ratio": ratio, "notable": False}
    else:
        return {"label": f"Normal Volume ({ratio:.1f}x avg)",    "ratio": ratio, "notable": False}


# ---------------------------------------------------------------------------
# Trailing Stop
# ---------------------------------------------------------------------------

def calc_trailing_stop(entry_price: float, current_price: float, stop_pct: float = 0.10) -> dict:
    """
    Calculate trailing stop status.

    Args:
        entry_price:   price you bought at
        current_price: today's price
        stop_pct:      e.g. 0.10 = 10% trailing stop

    Returns:
        dict with stop_price, triggered (bool), drawdown_pct
    """
    stop_price   = entry_price * (1 - stop_pct)
    drawdown_pct = (current_price - entry_price) / entry_price * 100
    triggered    = current_price <= stop_price

    return {
        "stop_price":    round(stop_price, 2),
        "current_price": round(current_price, 2),
        "drawdown_pct":  round(drawdown_pct, 2),
        "triggered":     triggered,
        "action":        "⚠️ STOP HIT — Consider exiting" if triggered else "✓ Within range",
    }


# ---------------------------------------------------------------------------
# Composite technical score (0–100)
# ---------------------------------------------------------------------------

def compute_technical_score(df: pd.DataFrame) -> dict:
    """
    Combine RSI, Bollinger, MACD, and EMA into a single 0–100 score.
    Higher = more bullish.
    """
    if df is None or len(df) < 30:
        return {"score": 50, "signals": {}, "error": "Insufficient data"}

    signals = {}
    score_components = []

    # RSI (weight: 25)
    rsi_series = calc_rsi(df)
    if not rsi_series.empty:
        rsi_val = float(rsi_series.iloc[-1])
        signals["rsi"] = {"value": round(rsi_val, 1), **rsi_signal(rsi_val)}
        # Score: 50 = neutral, scale based on distance from 50
        rsi_score = 50 + (rsi_val - 50) * 0.6  # compress range
        rsi_score = max(0, min(100, rsi_score))
        score_components.append(("rsi", rsi_score, 0.25))

    # Bollinger (weight: 20)
    bb_df = calc_bollinger(df)
    if not bb_df.empty:
        pct_b = float(bb_df["bb_pct_b"].iloc[-1])
        signals["bollinger"] = {"pct_b": round(pct_b, 3), **bollinger_signal(pct_b)}
        bb_score = pct_b * 100
        bb_score = max(0, min(100, bb_score))
        score_components.append(("bollinger", bb_score, 0.20))

    # MACD (weight: 25)
    macd_df = calc_macd(df)
    if not macd_df.empty:
        macd_interp = macd_signal_interp(macd_df)
        signals["macd"] = macd_interp
        macd_score = 70 if macd_interp.get("bullish") else (50 if macd_interp.get("bullish") is None else 30)
        score_components.append(("macd", macd_score, 0.25))

    # EMA trend (weight: 30)
    emas = calc_ema(df)
    trend = ema_trend_signal(df, emas)
    trend_scores = {
        "strong_uptrend":   90,
        "uptrend":          70,
        "sideways":         50,
        "downtrend":        30,
        "strong_downtrend": 10,
        "unknown":          50,
    }
    signals["ema_trend"] = {"label": trend.replace("_", " ").title()}
    score_components.append(("ema", trend_scores.get(trend, 50), 0.30))

    # Weighted composite
    if score_components:
        total_weight = sum(w for _, _, w in score_components)
        composite = sum(s * w for _, s, w in score_components) / total_weight
    else:
        composite = 50.0

    return {
        "score":   round(composite, 1),
        "signals": signals,
        "trend":   trend,
    }


def detect_regime(df: pd.DataFrame) -> dict:
    """
    Detect the market regime using ADX, +DI, and -DI.
    Returns:
        dict: {
            "regime": "TRENDING UP" | "TRENDING DOWN" | "CHOPPY" | "TRANSITIONING",
            "adx_value": float,
            "plus_di": float,
            "minus_di": float,
            "signal_modifier": float
        }
    """
    if df is None or len(df) < 14:
        return {
            "regime": "CHOPPY",
            "adx_value": 0.0,
            "plus_di": 0.0,
            "minus_di": 0.0,
            "signal_modifier": 0.0
        }
        
    try:
        from ta.trend import ADXIndicator
        adx_ind = ADXIndicator(high=df["High"], low=df["Low"], close=df["Close"], window=14)
        adx_series = adx_ind.adx()
        plus_di_series = adx_ind.adx_pos()
        minus_di_series = adx_ind.adx_neg()
        
        # Handle nan values gracefully
        adx_val = float(adx_series.iloc[-1]) if not pd.isna(adx_series.iloc[-1]) else 0.0
        plus_di = float(plus_di_series.iloc[-1]) if not pd.isna(plus_di_series.iloc[-1]) else 0.0
        minus_di = float(minus_di_series.iloc[-1]) if not pd.isna(minus_di_series.iloc[-1]) else 0.0
        
        if adx_val > 25:
            if plus_di > minus_di:
                regime = "TRENDING UP"
                modifier = 1.0
            else:
                regime = "TRENDING DOWN"
                modifier = 0.8
        elif adx_val < 20:
            regime = "CHOPPY"
            modifier = 0.0
        else:
            regime = "TRANSITIONING"
            modifier = 0.9
            
        return {
            "regime": regime,
            "adx_value": round(adx_val, 2),
            "plus_di": round(plus_di, 2),
            "minus_di": round(minus_di, 2),
            "signal_modifier": modifier
        }
    except Exception as e:
        logger.error(f"Error in detect_regime calculation: {e}")
        return {
            "regime": "CHOPPY",
            "adx_value": 0.0,
            "plus_di": 0.0,
            "minus_di": 0.0,
            "signal_modifier": 0.0
        }


# ---------------------------------------------------------------------------
# Candlestick Pattern Detection
# ---------------------------------------------------------------------------

def detect_candlestick_patterns(df: pd.DataFrame) -> list[dict]:
    """
    Detect key candlestick patterns on the last few bars.
    Returns a list of detected patterns with their signal direction.

    Patterns detected:
    - Hammer / Inverted Hammer (bullish reversal)
    - Bullish/Bearish Engulfing
    - Doji (indecision)
    - Morning Star / Evening Star (reversal)
    """
    if df is None or len(df) < 3:
        return []

    patterns = []
    o = df["Open"].values
    h = df["High"].values
    l = df["Low"].values  # noqa: E741
    c = df["Close"].values

    # Helper: body size
    def body(i):
        return abs(c[i] - o[i])

    def upper_shadow(i):
        return h[i] - max(o[i], c[i])

    def lower_shadow(i):
        return min(o[i], c[i]) - l[i]

    def total_range(i):
        return h[i] - l[i] if h[i] > l[i] else 0.001

    last = len(df) - 1
    prev = last - 1
    prev2 = last - 2

    # --- Hammer (bullish reversal) ---
    # Small body, long lower shadow (2x+ body), little upper shadow
    if body(last) > 0:
        ls = lower_shadow(last)
        us = upper_shadow(last)
        bd = body(last)
        if ls >= 2 * bd and us < bd * 0.5:
            patterns.append({
                "pattern": "Hammer",
                "signal": "bullish",
                "strength": "moderate",
                "description": "Small body with long lower shadow — buyers rejected lower prices",
            })

    # --- Inverted Hammer (bullish reversal at bottom) ---
    if body(last) > 0:
        ls = lower_shadow(last)
        us = upper_shadow(last)
        bd = body(last)
        if us >= 2 * bd and ls < bd * 0.5:
            patterns.append({
                "pattern": "Inverted Hammer",
                "signal": "bullish",
                "strength": "weak",
                "description": "Small body with long upper shadow — potential reversal from downtrend",
            })

    # --- Bullish Engulfing ---
    if prev >= 0:
        if (c[prev] < o[prev] and  # previous was bearish
                c[last] > o[last] and  # current is bullish
                o[last] <= c[prev] and  # current open <= previous close
                c[last] >= o[prev]):    # current close >= previous open
            patterns.append({
                "pattern": "Bullish Engulfing",
                "signal": "bullish",
                "strength": "strong",
                "description": "Bullish candle completely engulfs previous bearish candle",
            })

    # --- Bearish Engulfing ---
    if prev >= 0:
        if (c[prev] > o[prev] and  # previous was bullish
                c[last] < o[last] and  # current is bearish
                o[last] >= c[prev] and  # current open >= previous close
                c[last] <= o[prev]):    # current close <= previous open
            patterns.append({
                "pattern": "Bearish Engulfing",
                "signal": "bearish",
                "strength": "strong",
                "description": "Bearish candle completely engulfs previous bullish candle",
            })

    # --- Doji (indecision) ---
    tr = total_range(last)
    if body(last) / tr < 0.1 and tr > 0:
        patterns.append({
            "pattern": "Doji",
            "signal": "neutral",
            "strength": "moderate",
            "description": "Open ≈ Close — market indecision, potential reversal",
        })

    # --- Morning Star (3-bar bullish reversal) ---
    if prev2 >= 0:
        if (c[prev2] < o[prev2] and          # first bar bearish
                body(prev) < body(prev2) * 0.3 and  # middle bar small body
                c[last] > o[last] and                # third bar bullish
                c[last] > (o[prev2] + c[prev2]) / 2):  # closes above midpoint of first bar
            patterns.append({
                "pattern": "Morning Star",
                "signal": "bullish",
                "strength": "strong",
                "description": "3-bar bullish reversal pattern — potential trend change up",
            })

    # --- Evening Star (3-bar bearish reversal) ---
    if prev2 >= 0:
        if (c[prev2] > o[prev2] and          # first bar bullish
                body(prev) < body(prev2) * 0.3 and  # middle bar small body
                c[last] < o[last] and                # third bar bearish
                c[last] < (o[prev2] + c[prev2]) / 2):  # closes below midpoint of first bar
            patterns.append({
                "pattern": "Evening Star",
                "signal": "bearish",
                "strength": "strong",
                "description": "3-bar bearish reversal pattern — potential trend change down",
            })

    return patterns


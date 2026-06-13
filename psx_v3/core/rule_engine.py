"""
core/rule_engine.py — Deterministic Rule-Based Scoring Engine
"""

def compute_quant_score(data: dict) -> float:
    """
    Primary driver (0-100).
    Uses: RSI, MACD crossover, short-term returns.
    """
    score = 50.0  # neutral start
    
    # RSI component (0-30 points)
    rsi = data["rsi"]
    if rsi < 30:
        score += (30 - rsi) * 1.0    # deeply oversold = bullish
    elif rsi > 70:
        score -= (rsi - 70) * 1.0    # deeply overbought = bearish
    
    # MACD crossover component (0-35 points)
    macd = data["macd"]
    macd_signal = data.get("macd_signal", macd * 0.9)
    macd_histogram = macd - macd_signal
    
    if macd_histogram > 0:
        score += min(abs(macd_histogram) * 15, 35)   # bullish crossover
    else:
        score -= min(abs(macd_histogram) * 15, 35)   # bearish crossover
    
    # Short-term return component (0-35 points)
    ret_1d = data["return_1d"]  # decimal form, e.g., 0.02 = 2%
    ret_component = ret_1d * 100 * 1.5   # scale 2% return = +3 points
    ret_component = max(-35, min(35, ret_component))
    score += ret_component
    
    return max(0, min(100, score))


def compute_bull_score(data: dict) -> float:
    """
    Longer-term optimism (0-100).
    Uses: 7-day trend, volume expansion on up days, price vs 20-day MA.
    """
    score = 50.0
    
    # 7-day return component (0-30 points)
    ret_7d = data["return_7d"]  # decimal
    trend_points = ret_7d * 100 * 2.0   # 5% weekly gain = +10 points
    score += max(-30, min(30, trend_points))
    
    # Volume expansion on up days (0-35 points)
    avg_volume = data.get("avg_volume_20d", data["volume"])
    volume_ratio = data["volume"] / avg_volume if avg_volume > 0 else 1.0
    
    if data["return_1d"] > 0 and volume_ratio > 1.2:
        # Strong volume on green day = bullish confirmation
        score += min((volume_ratio - 1.0) * 25, 35)
    elif data["return_1d"] > 0 and volume_ratio < 0.8:
        # Weak volume on green day = less conviction
        score -= 10
    
    # Price vs 20-day moving average (0-35 points)
    price = data["price"]
    ma_20 = data.get("ma_20", price)
    if price > ma_20:
        pct_above = (price - ma_20) / ma_20 * 100
        score += min(pct_above * 3.5, 35)
    else:
        pct_below = (ma_20 - price) / ma_20 * 100
        score -= min(pct_below * 2.0, 35)
    
    return max(0, min(100, score))


def compute_bear_score(data: dict) -> float:
    """
    Downward pressure (0-100).
    Uses: downward momentum, volume expansion on down days, RSI overbought.
    """
    score = 50.0
    
    # Downward momentum (0-35 points)
    ret_7d = data["return_7d"]
    if ret_7d < 0:
        # Negative 7-day return scaled: -5% = +17.5 bearish points
        score += min(abs(ret_7d) * 100 * 3.5, 35)
    
    # Volume expansion on down days (0-35 points)
    avg_volume = data.get("avg_volume_20d", data["volume"])
    volume_ratio = data["volume"] / avg_volume if avg_volume > 0 else 1.0
    
    if data["return_1d"] < 0 and volume_ratio > 1.2:
        # Heavy volume on red day = distribution
        score += min((volume_ratio - 1.0) * 25, 35)
    
    # RSI overbought reversal risk (0-30 points)
    rsi = data["rsi"]
    if rsi > 75:
        score += min((rsi - 75) * 1.2, 30)  # extreme overbought = bearish
    elif rsi > 65:
        score += (rsi - 65) * 0.4             # moderately overbought
    
    return max(0, min(100, score))


def compute_risk_score(data: dict) -> float:
    """
    Risk/danger metric (0-100). Higher = more risk = more bearish pressure.
    Uses: volatility, gap downs, proximity to 52-week low.
    """
    score = 50.0
    
    # Volatility component (0-35 points)
    volatility = data["volatility"]  # decimal, e.g., 0.03 = 3% daily vol
    vol_percentile = data.get("vol_percentile_20d", volatility * 30)
    # High vol = higher risk
    score += min(vol_percentile * 0.35, 35)
    
    # Gap down detection (0-30 points)
    open_price = data.get("open", data["price"])
    prev_close = data.get("prev_close", data["price"])
    gap_pct = (open_price - prev_close) / prev_close * 100
    
    if gap_pct < -2.0:
        # Significant gap down = risk spike
        score += min(abs(gap_pct) * 5, 30)
    elif gap_pct < -0.5:
        score += abs(gap_pct) * 3
    
    # Proximity to 52-week low (0-35 points)
    price = data["price"]
    low_52w = data.get("low_52w", price * 0.7)
    high_52w = data.get("high_52w", price * 1.3)
    range_52w = high_52w - low_52w
    
    if range_52w > 0:
        pct_above_low = (price - low_52w) / range_52w * 100
        # Close to 52-week low = higher risk
        if pct_above_low < 10:
            score += (10 - pct_above_low) * 3.5
        elif pct_above_low < 25:
            score += (25 - pct_above_low) * 1.0
    
    return max(0, min(100, score))


def compute_final_score(quant, bull, bear, risk):
    """Weighted aggregation."""
    return (quant * 0.4) + (bull * 0.3) + ((100 - bear) * 0.2) + ((100 - risk) * 0.1)


def get_decision(final_score: float) -> str:
    """Deterministic verdict (PSX-calibrated thresholds)."""
    if final_score >= 55:
        return "BUY"
    elif final_score >= 35:
        return "HOLD"
    else:
        return "SELL"

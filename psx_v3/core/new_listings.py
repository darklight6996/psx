"""
core/new_listings.py — New Listings Handler.

Identifies if a stock is newly listed (has less than 200 days of data) and adjusts
its analysis profile to rely more on fundamentals and short-term momentum,
bypassing the ML and deep historical technicals.
"""

import pandas as pd
import logging

logger = logging.getLogger("new_listings")

def analyze_new_listing(symbol: str, df: pd.DataFrame, fundamentals: dict) -> dict:
    """
    Provides a simplified analysis for newly listed stocks.
    """
    price_now = float(df["Close"].iloc[-1]) if not df.empty else 0.0
    days_listed = len(df)
    
    # Calculate simple short-term momentum if we have at least a few days
    momentum = "UNKNOWN"
    if days_listed >= 5:
        ret_5d = (price_now - float(df["Close"].iloc[-5])) / float(df["Close"].iloc[-5])
        if ret_5d > 0.05:
            momentum = "BULLISH_MOMENTUM"
        elif ret_5d < -0.05:
            momentum = "BEARISH_MOMENTUM"
        else:
            momentum = "CONSOLIDATING"
            
    reasons = [
        f"Newly listed stock: only {days_listed} days of trading data available.",
        "Deep technicals and Machine Learning models require 200+ days and have been bypassed.",
        f"Short-term momentum is currently {momentum}."
    ]
    
    return {
        "verdict": "HOLD", # Conservative default for new listings
        "final_score": 50,
        "technical_score": 50,
        "signals": {
            "momentum": {"label": momentum, "value": f"{days_listed} days"}
        },
        "trend": momentum,
        "regime": {"regime": "PRICE_DISCOVERY", "adx_value": 0.0},
        "anomaly_flags": ["NEW_LISTING"],
        "anomaly_details": [{"flag": "NEW_LISTING", "detail": "Stock lacks sufficient history for robust analysis."}],
        "score_breakdown": {"base": 50},
        "reasons": reasons,
        "confidence": 30.0,
        "confidence_label": "LOW",
        "confidence_components": {"data_history": 0, "volatility": 30},
        "horizon": {"target": price_now * 1.05, "stop": price_now * 0.95, "atr": 0.0},
        "ml_signals": {"status": "skipped", "reason": "New listing"}
    }

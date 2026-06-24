"""
hqm_engine.py — High-Quality Momentum (HQM) scoring.

Algorithm:
1. Compute 1M, 3M, 6M, 12M returns for each stock in a universe.
2. Rank each stock against the universe (percentile).
3. Average the four percentile ranks → HQM Score (0–100).
4. Combine with technical score → final Advisory Rating.

Reference: "Quantitative Momentum" by Wesley Gray & Jack Vogel.
"""
# NOTE: HQM scores are inputs into scoring_engine.py. They are NOT the final verdict.

import logging
from typing import Optional
import numpy as np
import pandas as pd
from scipy.stats import percentileofscore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Percentile helper
# ---------------------------------------------------------------------------

def _percentile_score(series: pd.Series, value: float) -> float:
    """Return percentile rank of `value` within `series` (0–100)."""
    valid = series.dropna().values
    if len(valid) == 0:
        return 50.0
    return float(percentileofscore(valid, value, kind="rank"))


# ---------------------------------------------------------------------------
# Single-stock return calculation
# ---------------------------------------------------------------------------

def compute_returns(closes: pd.Series) -> dict:
    """
    Given a Series of daily closes (most recent last), compute
    1M / 3M / 6M / 12M percentage returns.
    """
    now = closes.iloc[-1]

    def _ret(approx_days: int) -> Optional[float]:
        # approximate trading days: 1M≈21, 3M≈63, 6M≈126, 12M≈252
        n = min(approx_days, len(closes) - 1)
        if n <= 0:
            return None
        past = closes.iloc[-(n + 1)]
        if past == 0:
            return None
        return (now - past) / past * 100

    return {
        "return_1m":  _ret(21),
        "return_3m":  _ret(63),
        "return_6m":  _ret(126),
        "return_12m": _ret(252),
        "current_price": float(now),
    }


# ---------------------------------------------------------------------------
# Universe-level HQM scoring
# ---------------------------------------------------------------------------

def compute_hqm_universe(returns_df: pd.DataFrame) -> pd.DataFrame:
    """
    Given a DataFrame with columns [return_1m, return_3m, return_6m, return_12m]
    indexed by symbol, compute HQM percentile scores.

    Returns the same DataFrame with added columns:
        pct_1m, pct_3m, pct_6m, pct_12m, hqm_score
    """
    df = returns_df.copy()
    periods = ["return_1m", "return_3m", "return_6m", "return_12m"]
    pct_cols = ["pct_1m",   "pct_3m",   "pct_6m",   "pct_12m"]

    for ret_col, pct_col in zip(periods, pct_cols):
        if ret_col in df.columns:
            df[pct_col] = df[ret_col].apply(
                lambda v: _percentile_score(df[ret_col], v) if pd.notna(v) else np.nan
            )
        else:
            df[pct_col] = np.nan

    # HQM = mean of available percentiles
    df["hqm_score"] = df[pct_cols].mean(axis=1)

    return df


# ---------------------------------------------------------------------------
# Single-stock HQM score (relative to a given universe)
# ---------------------------------------------------------------------------

def score_single_stock(
    symbol: str,
    closes: pd.Series,
    universe_df: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Score a single stock.

    If universe_df is provided (output of compute_hqm_universe), the stock's
    percentiles are computed relative to that universe.
    Otherwise, self-relative scores are returned (less meaningful but still usable).

    Returns dict with all return and percentile fields.
    """
    rets = compute_returns(closes)

    if universe_df is not None and symbol in universe_df.index:
        row = universe_df.loc[symbol]
        return {
            "symbol":        symbol,
            "current_price": rets["current_price"],
            "return_1m":     round(rets["return_1m"]  or 0, 2),
            "return_3m":     round(rets["return_3m"]  or 0, 2),
            "return_6m":     round(rets["return_6m"]  or 0, 2),
            "return_12m":    round(rets["return_12m"] or 0, 2),
            "pct_1m":        round(float(row.get("pct_1m",  50)), 1),
            "pct_3m":        round(float(row.get("pct_3m",  50)), 1),
            "pct_6m":        round(float(row.get("pct_6m",  50)), 1),
            "pct_12m":       round(float(row.get("pct_12m", 50)), 1),
            "hqm_score":     round(float(row.get("hqm_score", 50)), 1),
        }

    # Self-relative: just return raw data, normalise to 0-100 linearly
    def _norm(v):
        if v is None:
            return 50.0
        # clip to ±100% return, scale to 0–100
        clamped = max(-100, min(100, v))
        return round((clamped + 100) / 2, 1)

    pct_1m  = _norm(rets["return_1m"])
    pct_3m  = _norm(rets["return_3m"])
    pct_6m  = _norm(rets["return_6m"])
    pct_12m = _norm(rets["return_12m"])
    hqm     = round(np.nanmean([pct_1m, pct_3m, pct_6m, pct_12m]), 1)

    return {
        "symbol":        symbol,
        "current_price": rets["current_price"],
        "return_1m":     round(rets["return_1m"]  or 0, 2),
        "return_3m":     round(rets["return_3m"]  or 0, 2),
        "return_6m":     round(rets["return_6m"]  or 0, 2),
        "return_12m":    round(rets["return_12m"] or 0, 2),
        "pct_1m":        pct_1m,
        "pct_3m":        pct_3m,
        "pct_6m":        pct_6m,
        "pct_12m":       pct_12m,
        "hqm_score":     hqm,
    }


# ---------------------------------------------------------------------------
# Final advisory rating
# ---------------------------------------------------------------------------

def compute_legacy_momentum_signal(
    hqm_score: float,
    technical_score: float,
    shariah_compliant: bool,
    macro_sentiment: str = "neutral",   # "bullish", "neutral", "bearish"
) -> dict:
    """LEGACY — do not use for final verdicts. Used only as one input signal into the voting engine."""
    import warnings
    warnings.warn("compute_legacy_momentum_signal is deprecated. Use core.scoring_engine instead.", DeprecationWarning, stacklevel=2)
    raise RuntimeError("compute_legacy_momentum_signal is deprecated. Use core.scoring_engine instead.")





# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

import math

def calc_position_size(
    total_capital: float,
    num_positions: int,
    current_price: float,
    allocation_pct: Optional[float] = None,
) -> dict:
    """
    Calculate whole-share position size.
    Dynamically adjusts to avoid fragmentation on small budgets (e.g. 5,000 PKR).

    Args:
        total_capital:  total portfolio value in PKR
        num_positions:  number of stocks to diversify across (if allocation_pct not given)
        current_price:  current share price
        allocation_pct: override — specific % of capital for this position (0.0–1.0)

    Returns:
        dict with capital_allocated, shares, cost, remaining_capital, warning
    """
    warning = ""
    if total_capital <= 25000 and allocation_pct is None:
        if total_capital < 10000:
            effective_num_positions = 1
            warning = "⚠️ Small capital: Concentrating budget into 1 stock to afford whole shares."
        else:
            effective_num_positions = 2
            warning = "⚠️ Small capital: Concentrating budget into 2 stocks to reduce trading fee friction."
        capital_for_stock = total_capital / effective_num_positions
    else:
        if allocation_pct is not None:
            capital_for_stock = total_capital * allocation_pct
        else:
            capital_for_stock = total_capital / max(num_positions, 1)

    shares = math.floor(capital_for_stock / current_price) if current_price > 0 else 0
    cost   = shares * current_price

    if shares == 0 and current_price > 0:
        warning = f"❌ Stock price (PKR {current_price:,.2f}) exceeds allocated budget (PKR {capital_for_stock:,.2f}). Cannot purchase."

    return {
        "capital_allocated": round(capital_for_stock, 2),
        "shares":            shares,
        "cost":              round(cost, 2),
        "remaining_capital": round(total_capital - cost, 2),
        "price_per_share":   round(current_price, 2),
        "warning":           warning,
    }


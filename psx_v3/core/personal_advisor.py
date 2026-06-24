"""
core/personal_advisor.py — Personalised investment recommendations.

Generates personalised BUY/HOLD/SELL/ADD/TAKE_PROFIT/CUT_LOSS signals
based on the combination of:
  1. The market signal (from scoring_engine + council)
  2. The user's actual position (entry price, shares, PKR invested)
  3. ATR-based profit/loss thresholds
  4. Portfolio weight and concentration
  5. How long the position has been held

The market signal is neutral — it applies to everyone.
The personal signal is specific — it applies only to this user's situation.

These are two different questions:
  Market signal: "Is ISL a good stock to own right now?"
  Personal signal: "Given YOU bought ISL at PKR 85 and it is now PKR 94,
                   what should YOU do with YOUR position right now?"
"""

import math
import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ATR helper
# ---------------------------------------------------------------------------

def _get_atr(df: Optional[pd.DataFrame]) -> float:
    """Get latest ATR value from a DataFrame. Returns 0.0 if unavailable."""
    if df is None or df.empty:
        return 0.0
    try:
        from core.horizon_engine import calc_atr
        atr_val = calc_atr(df)
        return atr_val if atr_val and atr_val > 0 else 0.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Portfolio context loader
# ---------------------------------------------------------------------------

def get_personal_portfolio_context(symbol: str, current_price: float) -> dict:
    """
    Load the user's position in this symbol from the investments table.
    Returns full context needed by get_personal_signal().
    """
    from memory.db import get_open_investments
    from core.portfolio import get_total_capital

    positions = [p for p in get_open_investments() if p["symbol"] == symbol.upper()]

    if not positions:
        return {
            "holding": False,
            "total_capital": get_total_capital(),
            "current_portfolio_weight_pct": 0.0,
        }

    # Aggregate all positions in this symbol (user may have bought in multiple tranches)
    total_shares = sum(p["shares"] for p in positions)
    total_invested = sum(p["pkr_invested"] for p in positions)
    avg_entry_price = total_invested / total_shares if total_shares > 0 else 0
    current_value = current_price * total_shares
    pnl_pkr = current_value - total_invested
    pnl_pct = pnl_pkr / total_invested * 100 if total_invested > 0 else 0
    total_capital = get_total_capital()
    portfolio_weight = current_value / total_capital * 100 if total_capital > 0 else 0

    # Earliest entry date (for weeks held calculation)
    dates = []
    for p in positions:
        try:
            dates.append(date.fromisoformat(p["entry_date"]))
        except Exception:
            pass
    first_entry = min(dates) if dates else date.today()
    weeks_held = (date.today() - first_entry).days // 7

    # Highest price since entry (for trailing stop)
    highest_since = 0.0
    for p in positions:
        h = p.get("highest_price_since_entry")
        if h and isinstance(h, (int, float)) and h > 0:
            highest_since = max(highest_since, float(h))
        else:
            highest_since = max(highest_since, float(p["entry_price"]))
    highest_since = max(highest_since, current_price)

    return {
        "holding": True,
        "symbol": symbol.upper(),
        "total_shares": total_shares,
        "total_invested_pkr": round(total_invested, 2),
        "avg_entry_price": round(avg_entry_price, 2),
        "current_price": current_price,
        "current_value_pkr": round(current_value, 2),
        "pnl_pkr": round(pnl_pkr, 2),
        "pnl_pct": round(pnl_pct, 2),
        "portfolio_weight_pct": round(portfolio_weight, 2),
        "weeks_held": weeks_held,
        "first_entry_date": first_entry.isoformat(),
        "highest_price_since_entry": round(highest_since, 2),
        "total_capital": total_capital,
        "num_tranches": len(positions),
    }


# ---------------------------------------------------------------------------
# Personal signal generator
# ---------------------------------------------------------------------------

_DEFAULT_ALLOCATION_PCT = 5.0


def get_personal_signal(
    symbol: str,
    market_signal: str,
    market_score: float,
    current_price: float,
    df: Optional[pd.DataFrame],
    portfolio_context: dict,
) -> dict:
    """
    Generate a personal recommendation combining market signal with
    the user's actual position and portfolio situation.
    """
    holding = portfolio_context.get("holding", False)
    total_capital = portfolio_context.get("total_capital", 500_000)

    # ── Scenario A: No position held, market says BUY ────────────────────────
    if not holding and market_signal == "BUY":
        atr = _get_atr(df) if df is not None else 0.0

        entry_timing = "GOOD"
        if df is not None and not df.empty and atr > 0:
            today_move = abs(current_price - float(df["Open"].iloc[-1]))
            entry_timing = "GOOD" if today_move < 0.5 * atr else "WAIT_FOR_PULLBACK"

        suggested_allocation_pct = _DEFAULT_ALLOCATION_PCT
        suggested_pkr = total_capital * (suggested_allocation_pct / 100)
        suggested_shares = math.floor(suggested_pkr / current_price) if current_price > 0 else 0

        stop_loss = round(current_price - 2 * atr, 2) if atr > 0 else 0.0
        target_1 = round(current_price + 2 * atr, 2) if atr > 0 else 0.0
        target_2 = round(current_price + 4 * atr, 2) if atr > 0 else 0.0

        return {
            "personal_verdict": "CONSIDER_BUYING",
            "personal_action": (
                f"No position held. Market signal is BUY (score {market_score:.0f}). "
                f"Consider entering {suggested_shares} shares at PKR {current_price:,.2f} "
                f"({suggested_allocation_pct:.0f}% of your PKR {total_capital:,.0f} capital)."
                + (f" Stop at PKR {stop_loss:,.2f}, Target 1: PKR {target_1:,.2f}, Target 2: PKR {target_2:,.2f}."
                   if atr > 0 else "")
            ),
            "entry_timing": entry_timing,
            "suggested_entry_pkr": round(current_price, 2),
            "suggested_shares": suggested_shares,
            "suggested_investment_pkr": round(suggested_shares * current_price, 2),
            "stop_loss_pkr": stop_loss,
            "target_1_pkr": target_1,
            "target_2_pkr": target_2,
            "portfolio_weight_pct": suggested_allocation_pct,
            "scenario": "NO_POSITION_MARKET_BUY",
        }

    # ── Scenario B: Position held, in profit ─────────────────────────────────
    if holding and portfolio_context.get("pnl_pct", 0) > 0:
        entry_price = portfolio_context["avg_entry_price"]
        shares = portfolio_context["total_shares"]
        pkr_invested = portfolio_context["total_invested_pkr"]
        pnl_pkr = portfolio_context["pnl_pkr"]
        pnl_pct = portfolio_context["pnl_pct"]
        weeks_held = portfolio_context.get("weeks_held", 0)
        highest_since = portfolio_context.get("highest_price_since_entry", current_price)

        atr = _get_atr(df) if df is not None else 0.0
        if atr <= 0 and entry_price > 0:
            atr = entry_price * 0.02

        trailing_stop = round(highest_since - 1.5 * atr, 2) if atr > 0 else 0.0
        at_target_1 = current_price >= entry_price + 2 * atr if atr > 0 else False
        at_target_2 = current_price >= entry_price + 4 * atr if atr > 0 else False
        stop_hit = current_price <= trailing_stop if trailing_stop > 0 else False

        target_1_pkr = round(entry_price + 2 * atr, 2) if atr > 0 else 0.0
        target_2_pkr = round(entry_price + 4 * atr, 2) if atr > 0 else 0.0
        locked_profit = round((trailing_stop - entry_price) * shares, 2) if trailing_stop > 0 else 0.0

        if stop_hit:
            verdict = "EXIT_TRAILING_STOP_HIT"
            action = (
                f"Trailing stop hit at PKR {trailing_stop:,.2f}. "
                f"Exit your {shares} shares NOW. "
                f"Lock in PKR {pnl_pkr:+,.0f} ({pnl_pct:+.1f}%) profit."
            )
        elif at_target_2:
            verdict = "TAKE_FULL_PROFIT"
            action = (
                f"Target 2 reached! You are up PKR {pnl_pkr:+,.0f} ({pnl_pct:+.1f}%). "
                f"Consider closing the full position or holding with a tight stop "
                f"at PKR {trailing_stop:,.2f}."
            )
        elif at_target_1:
            half_shares = shares // 2
            verdict = "TAKE_PARTIAL_PROFIT"
            action = (
                f"Target 1 reached. You are up PKR {pnl_pkr:+,.0f} ({pnl_pct:+.1f}%). "
                f"Consider selling half ({half_shares} shares) at PKR {current_price:,.2f}. "
                f"Move stop to entry price PKR {entry_price:,.2f} to protect remaining profit. "
                f"Let the other half run to Target 2: PKR {target_2_pkr:,.2f}."
            )
        elif market_signal == "SELL":
            verdict = "EXIT_MARKET_TURNED"
            action = (
                f"Market signal has turned SELL. You are currently up "
                f"PKR {pnl_pkr:+,.0f} ({pnl_pct:+.1f}%). "
                f"Consider exiting before the market signal deteriorates further."
            )
        else:
            verdict = "HOLD_AND_TRAIL"
            action = (
                f"Holding {shares} shares bought at PKR {entry_price:,.2f}. "
                f"Current profit: PKR {pnl_pkr:+,.0f} ({pnl_pct:+.1f}%). "
                f"Trail stop to PKR {trailing_stop:,.2f}. "
                f"Market signal is {market_signal} — no action needed."
            )

        return {
            "personal_verdict": verdict,
            "personal_action": action,
            "entry_price": entry_price,
            "current_price": current_price,
            "shares_held": shares,
            "pkr_invested": pkr_invested,
            "current_value_pkr": round(current_price * shares, 2),
            "pnl_pkr": round(pnl_pkr, 2),
            "pnl_pct": round(pnl_pct, 2),
            "trailing_stop_pkr": trailing_stop,
            "target_1_pkr": target_1_pkr,
            "target_2_pkr": target_2_pkr,
            "weeks_held": weeks_held,
            "highest_price_since": round(highest_since, 2),
            "locked_profit_pkr": locked_profit,
            "scenario": "HOLDING_IN_PROFIT",
        }

    # ── Scenario C: Position held, in a loss ─────────────────────────────────
    if holding and portfolio_context.get("pnl_pct", 0) < 0:
        entry_price = portfolio_context["avg_entry_price"]
        shares = portfolio_context["total_shares"]
        pkr_invested = portfolio_context["total_invested_pkr"]
        pnl_pkr = portfolio_context["pnl_pkr"]
        pnl_pct = portfolio_context["pnl_pct"]
        weeks_held = portfolio_context.get("weeks_held", 0)

        atr = _get_atr(df) if df is not None else 0.0
        if atr <= 0 and entry_price > 0:
            atr = entry_price * 0.02

        stop_loss = round(entry_price - 2 * atr, 2) if atr > 0 else 0.0
        stop_hit = current_price <= stop_loss if stop_loss > 0 else False
        deep_loss = pnl_pct < -15

        if stop_hit or deep_loss:
            verdict = "CUT_LOSS"
            stop_msg = f"ATR stop hit at PKR {stop_loss:,.2f}. " if stop_hit and atr > 0 else ""
            action = (
                f"Stop loss triggered. You are down PKR {abs(pnl_pkr):,.0f} "
                f"({pnl_pct:.1f}%). "
                f"{stop_msg}"
                f"Exit your {shares} shares to prevent further loss. "
                f"Do not average down — the original thesis is broken."
            )
        elif market_signal == "SELL":
            verdict = "EXIT_DOUBLE_SIGNAL"
            action = (
                f"You are down PKR {abs(pnl_pkr):,.0f} ({pnl_pct:.1f}%) "
                f"AND the market signal has turned SELL. "
                f"Double confirmation to exit. Sell your {shares} shares."
            )
        elif market_signal in ("BUY", "HOLD") and pnl_pct > -8:
            stop_pct_below = round((entry_price - stop_loss) / entry_price * 100, 1) if stop_loss > 0 and entry_price > 0 else 0
            verdict = "HOLD_WITHIN_TOLERANCE"
            action = (
                f"You are down PKR {abs(pnl_pkr):,.0f} ({pnl_pct:.1f}%) "
                f"but within normal ATR range. Stop loss at PKR {stop_loss:,.2f} "
                f"({stop_pct_below}% below entry). "
                f"Market signal is still {market_signal}. Hold — do NOT average down yet. "
                f"Re-evaluate if price falls below PKR {stop_loss:,.2f}."
            )
        else:
            verdict = "WATCH_CAREFULLY"
            action = (
                f"Down PKR {abs(pnl_pkr):,.0f} ({pnl_pct:.1f}%). "
                f"Hard stop at PKR {stop_loss:,.2f}. "
                f"Market signal is {market_signal}. Watch closely."
            )

        return {
            "personal_verdict": verdict,
            "personal_action": action,
            "entry_price": entry_price,
            "current_price": current_price,
            "shares_held": shares,
            "pkr_invested": pkr_invested,
            "current_value_pkr": round(current_price * shares, 2),
            "pnl_pkr": round(pnl_pkr, 2),
            "pnl_pct": round(pnl_pct, 2),
            "stop_loss_pkr": stop_loss,
            "weeks_held": weeks_held,
            "scenario": "HOLDING_IN_LOSS",
        }

    # ── Scenario D: No position, market says HOLD/WAIT/SELL ──────────────────
    return {
        "personal_verdict": "MONITOR",
        "personal_action": (
            f"No position held. Market signal is {market_signal} (score {market_score:.0f}). "
            f"No action needed. Add to watchlist and wait for a BUY signal."
        ),
        "scenario": "NO_POSITION_NO_BUY_SIGNAL",
        "watch_price": round(current_price * 0.97, 2),
        "watch_note": f"Consider reviewing again if price dips to PKR {round(current_price * 0.97, 2):,.2f}",
    }


# ---------------------------------------------------------------------------
# Convenience: compute both context + signal in one call
# ---------------------------------------------------------------------------

def compute_personal_advisory(
    symbol: str,
    market_signal: str,
    market_score: float,
    current_price: float,
    df: Optional[pd.DataFrame] = None,
) -> dict:
    """
    One-call convenience function.
    Returns dict with 'portfolio_context' and 'personal_signal' keys.
    """
    ctx = get_personal_portfolio_context(symbol, current_price)
    sig = get_personal_signal(
        symbol=symbol,
        market_signal=market_signal,
        market_score=market_score,
        current_price=current_price,
        df=df,
        portfolio_context=ctx,
    )
    return {
        "portfolio_context": ctx,
        "personal_signal": sig,
    }


# ---------------------------------------------------------------------------
# Display helpers for UI
# ---------------------------------------------------------------------------

PERSONAL_VERDICT_DISPLAY = {
    "CONSIDER_BUYING":        "🔵 Consider Buy",
    "TAKE_PARTIAL_PROFIT":    "💛 Take Half Profit",
    "TAKE_FULL_PROFIT":       "💰 Take Full Profit",
    "HOLD_AND_TRAIL":         "🟢 Hold & Trail Stop",
    "HOLD_WITHIN_TOLERANCE":  "🟡 Hold (In Loss)",
    "EXIT_TRAILING_STOP_HIT": "🔴 Exit — Stop Hit",
    "EXIT_MARKET_TURNED":     "🔴 Exit — Signal Changed",
    "EXIT_DOUBLE_SIGNAL":     "🚨 Exit Now",
    "CUT_LOSS":               "🚨 Cut Loss",
    "WATCH_CAREFULLY":        "⚠️ Watch",
    "MONITOR":                "👁️ Monitor",
}

URGENT_VERDICTS = {"CUT_LOSS", "EXIT_TRAILING_STOP_HIT", "EXIT_DOUBLE_SIGNAL"}
PROFIT_VERDICTS = {"TAKE_PARTIAL_PROFIT", "TAKE_FULL_PROFIT"}
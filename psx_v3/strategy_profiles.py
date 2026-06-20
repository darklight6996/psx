"""
strategy_profiles.py — Strategy mode configuration for the PSX V4 Advisor.

Three modes: day, swing, longterm.

Each profile defines:
  - Which tools the advisor prioritises
  - What the system prompt addendum says
  - How to interpret signals and thresholds
  - What holding period is expected
  - What success looks like (for outcome evaluation)

No external dependencies — pure config.
"""

from typing import Optional

# ---------------------------------------------------------------------------
# Profile definitions
# ---------------------------------------------------------------------------

STRATEGY_PROFILES: dict[str, dict] = {

    "day": {
        "label":            "Day trading",
        "short_label":      "DAY",
        "emoji":            "⚡",
        "horizon_days":     1,
        "hit_threshold_pct": 1.0,   # BUY correct if up >1% intraday/next open

        "priority_tools": [
            "get_live_quote",
            "get_order_book_ratio",
            "get_market_status",
            "get_atr_targets",
            "get_macro_context",
        ],

        "system_prompt_addendum": """
You are advising a DAY TRADER on the Pakistan Stock Exchange (PSX).

Key priorities for this strategy:
- Focus on intraday momentum, order book imbalance (bid/ask volume ratio), and same-day entry/exit.
- Highlight PSX-specific risks: upper/lower circuit breakers (7.5% daily limit), illiquid stocks that lock.
- Only recommend stocks with high average daily volume (top-tier KSE-100 constituents).
- ATR-based same-day targets are the primary exit criteria.
- Avoid recommending stocks near earnings (HIGH_RISK proximity).
- If order book ratio > 1.3 with rising price: strong intraday buy signal.
- If order book ratio < 0.7 with falling price: distribution — avoid or short.
- Keep recommendations tight: entry zone, target, and hard stop. No vague advice.
- Express confidence as a percentage. If confidence < 55%, recommend WAIT.
""",
        "success_criterion": "Price moved >1% in the right direction within 1 trading day.",
    },

    "swing": {
        "label":            "Swing trading",
        "short_label":      "SWING",
        "emoji":            "📈",
        "horizon_days_min": 3,
        "horizon_days_max": 20,
        "hit_threshold_pct": 1.5,   # BUY correct if up >1.5% within holding period

        "priority_tools": [
            "get_pipeline_result",
            "get_ml_prediction",
            "get_atr_targets",
            "get_sector_rotation",
            "get_signal_scores",
            "get_recent_announcements",
            "get_prediction_history",
        ],

        "system_prompt_addendum": """
You are advising a SWING TRADER on the Pakistan Stock Exchange (PSX).

Key priorities for this strategy:
- Target 3–20 day breakouts using technical momentum (EMA trends, MACD crossovers, volume spikes).
- ATR-based target prices and stop losses are mandatory in every concrete recommendation.
- PSX-specific context: RSI frequently runs to 80+ before reversing — standard 70 is too early to sell.
- Sector rotation matters: prefer stocks in LEADER sectors, avoid LAGGARD sectors.
- ML prediction is a supporting signal only — if ml_signal_reliable is False, ignore it.
- Anomaly triggers (volume_spike, golden_cross, breakout_high_volume) increase conviction.
- Shariah compliance must be checked — non-compliant stocks cannot be BUY.
- If earnings are within 5 days (HIGH_RISK), recommend WAIT not BUY.
- Holding period: state explicitly. "3–7 days", "1–2 weeks", not vague ranges.
""",
        "success_criterion": "Price moved >1.5% in the right direction within the stated holding period.",
    },

    "longterm": {
        "label":            "Long-term investing",
        "short_label":      "LONGTERM",
        "emoji":            "🏛️",
        "horizon_days":     90,
        "hit_threshold_pct": 5.0,   # BUY correct if up >5% within 90 days

        "priority_tools": [
            "get_shariah_status",
            "get_prediction_history",
            "get_macro_context",
            "get_sector_rotation",
            "get_pipeline_result",
            "get_atr_targets",
            "get_ai_reflections",
        ],

        "system_prompt_addendum": """
You are advising a LONG-TERM INVESTOR on the Pakistan Stock Exchange (PSX).

Key priorities for this strategy:
- Focus on fundamentals, Shariah compliance, valuation, and sector macro trends.
- Shariah compliance is non-negotiable — GRAY_AREA stocks require explicit discussion before recommendation.
- Short-term technical noise (daily RSI, MACD) should be downweighted significantly.
- Macro context is critical: KIBOR rates, IMF program status, PKR trajectory affect multi-month returns.
- Highlight dividend yield, debt-to-equity, and sector regulatory risk.
- Sector rotation: prefer sectors with structural tailwinds (e.g. tech/IT for PKR hedge, 
  fertiliser for food security, energy transition).
- PSX-specific long-term risks: liquidity (free float < 20% = trap), circular debt exposure,
  government policy dependency.
- Be explicit about what would invalidate the thesis (stop-loss for investors: 
  typically 12–15%, wider than swing traders).
- Holding period: months to years. Don't recommend selling on short-term dips.
""",
        "success_criterion": "Price moved >5% in the right direction within 90 days.",
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_profile(mode: str) -> dict:
    """
    Return profile dict for a given mode string.
    Accepts: 'day', 'swing', 'longterm', 'long', 'long_term', 'long-term'.
    Defaults to 'swing' if unrecognised.
    """
    mode = mode.lower().strip().replace("-", "").replace("_", "")
    mapping = {
        "day":       "day",
        "daytrading": "day",
        "intraday":  "day",
        "swing":     "swing",
        "swingtrading": "swing",
        "medium":    "swing",
        "longterm":  "longterm",
        "long":      "longterm",
        "invest":    "longterm",
        "investor":  "longterm",
        "investing": "longterm",
    }
    key = mapping.get(mode, "swing")
    return STRATEGY_PROFILES[key]


def get_mode_from_text(text: str) -> Optional[str]:
    """
    Detect strategy mode from free-form user text.

    Returns 'day', 'swing', 'longterm', or None if ambiguous.
    """
    text_lower = text.lower()
    day_keywords    = ["day trade", "day trading", "intraday", "same day", "today only"]
    swing_keywords  = ["swing", "few days", "week or two", "short term", "breakout"]
    long_keywords   = ["long term", "long-term", "hold months", "hold years",
                       "invest for", "portfolio", "retirement", "halal invest"]

    if any(kw in text_lower for kw in day_keywords):
        return "day"
    if any(kw in text_lower for kw in swing_keywords):
        return "swing"
    if any(kw in text_lower for kw in long_keywords):
        return "longterm"
    return None


def describe_strategy(mode: str) -> str:
    """Short human-readable description for display in the chat UI."""
    profile = get_profile(mode)
    return f"{profile['emoji']} {profile['label']}"


STRATEGY_QUESTION = (
    "Before I start, what is your goal for this session?\n\n"
    "⚡ **Day trading** — same-day entry and exit, tight stops\n"
    "📈 **Swing trading** — 3 to 20 day positions, breakout focus\n"
    "🏛️ **Long-term investing** — months to years, fundamentals and Shariah focus\n\n"
    "Just reply with: *day*, *swing*, or *long term*."
)

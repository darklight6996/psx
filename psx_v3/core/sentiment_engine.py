"""
sentiment_engine.py — Announcement-only sentiment analyzer.

Phase 1 scope: Only analyzes company disclosures, earnings reports,
and dividend announcements from PSX.

DISABLED in Phase 1:
- Social media scraping
- Forum buzz
- News aggregators
- FinBERT inference (saved for Phase 2 when local model is installed)

The output is a simple composite score and label for each stock
based on its recent announcements.
"""

import logging
from datetime import datetime, date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Announcement sentiment weights
# ---------------------------------------------------------------------------

ANNOUNCEMENT_SCORES = {
    "DIVIDEND_ANNOUNCED":    +0.6,
    "QUARTERLY_RESULTS":     +0.2,  # neutral-positive (depends on content)
    "EARNINGS_BEAT":         +0.8,
    "EARNINGS_MISS":         -0.7,
    "AUDITOR_RESIGNED":      -0.9,
    "DEFAULT_RISK":          -1.0,
    "GENERAL":                0.0,
}

# Decay: announcements lose impact over time
DECAY_HALF_LIFE_DAYS = 7  # impact halves every 7 days


# ---------------------------------------------------------------------------
# Core sentiment computation
# ---------------------------------------------------------------------------

def compute_announcement_sentiment(
    symbol: str,
    announcements: list[dict],
    lookback_days: int = 30,
) -> dict:
    """
    Compute sentiment from PSX announcements for a stock.

    Args:
        symbol: PSX ticker
        announcements: list of announcement dicts from psx_live.get_psx_announcements()
        lookback_days: how far back to consider announcements

    Returns:
        {
            "composite_score": float (-1.0 to +1.0),
            "sentiment_label": "POSITIVE" | "NEGATIVE" | "NEUTRAL",
            "announcement_count": int,
            "key_events": list of relevant announcements,
            "details": dict with breakdown,
        }
    """
    symbol = symbol.upper()
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()

    # Filter announcements for this stock within lookback
    relevant = []
    for ann in announcements:
        ann_sym = str(ann.get("symbol", "")).upper()
        ann_date = ann.get("announcement_date", "")
        if ann_sym == symbol and ann_date >= cutoff:
            relevant.append(ann)

    if not relevant:
        return {
            "composite_score": 0.0,
            "sentiment_label": "NEUTRAL",
            "announcement_count": 0,
            "key_events": [],
            "details": {"message": "No recent announcements"},
        }

    # Calculate time-decayed weighted score
    total_weight = 0.0
    weighted_score = 0.0
    key_events = []

    for ann in relevant:
        ann_type = ann.get("announcement_type", "GENERAL")
        base_score = ANNOUNCEMENT_SCORES.get(ann_type, 0.0)

        # Calculate decay
        try:
            ann_date = datetime.strptime(ann.get("announcement_date", ""), "%Y-%m-%d").date()
            days_ago = (date.today() - ann_date).days
        except (ValueError, TypeError):
            days_ago = lookback_days  # assume old if unparseable

        # Exponential decay
        import math
        decay = math.exp(-0.693 * days_ago / DECAY_HALF_LIFE_DAYS)  # ln(2) ≈ 0.693

        weight = decay
        weighted_score += base_score * weight
        total_weight += weight

        if abs(base_score) > 0.3:  # only track significant events
            key_events.append({
                "type": ann_type,
                "headline": ann.get("headline", ""),
                "date": ann.get("announcement_date", ""),
                "impact": round(base_score * decay, 3),
            })

    # Normalize to -1.0 to +1.0
    if total_weight > 0:
        composite = weighted_score / total_weight
    else:
        composite = 0.0

    composite = max(-1.0, min(1.0, composite))

    # Label
    if composite >= 0.3:
        label = "POSITIVE"
    elif composite <= -0.3:
        label = "NEGATIVE"
    else:
        label = "NEUTRAL"

    return {
        "composite_score": round(composite, 3),
        "sentiment_label": label,
        "announcement_count": len(relevant),
        "key_events": key_events[:5],  # top 5
        "details": {
            "weighted_score": round(weighted_score, 3),
            "total_weight": round(total_weight, 3),
            "lookback_days": lookback_days,
        },
    }


# ---------------------------------------------------------------------------
# Save to database
# ---------------------------------------------------------------------------

def save_sentiment(symbol: str, sentiment: dict) -> None:
    """Persist sentiment result to sentiment_history table."""
    import json
    try:
        from memory.db import get_conn
        with get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO sentiment_history
                    (symbol, sentiment_date, composite_score, sentiment_label, details_json)
                VALUES (?, ?, ?, ?, ?)
            """, (
                symbol.upper(),
                date.today().isoformat(),
                sentiment["composite_score"],
                sentiment["sentiment_label"],
                json.dumps(sentiment),
            ))
    except Exception as e:
        logger.error(f"Failed to save sentiment for {symbol}: {e}")


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def compute_batch_sentiment(
    symbols: list[str],
    all_announcements: list[dict],
) -> dict[str, dict]:
    """
    Compute sentiment for multiple stocks.
    Returns {symbol: sentiment_dict}.
    """
    results = {}
    for symbol in symbols:
        sentiment = compute_announcement_sentiment(symbol, all_announcements)
        results[symbol] = sentiment
        if sentiment["announcement_count"] > 0:
            save_sentiment(symbol, sentiment)
    return results

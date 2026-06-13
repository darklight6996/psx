"""
macro_sentiment.py — Pakistan macro-economic sentiment filter.

Uses NewsAPI to scan for keywords related to:
- SBP (State Bank of Pakistan) interest rate decisions
- IMF deals / loan tranches
- PKR/USD exchange rate shocks
- FATF grey-listing status
- Inflation data

Falls back to "neutral" if no API key or network available.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")


# ---------------------------------------------------------------------------
# Keyword lists
# ---------------------------------------------------------------------------

BEARISH_KEYWORDS = [
    "pakistan default", "imf stalled", "imf suspended", "imf collapsed",
    "sbp rate hike", "interest rate increase", "inflation surged",
    "pkr crash", "rupee crashed", "rupee falls", "currency devaluation",
    "fatf blacklist", "political crisis pakistan", "psx circuit breaker",
    "budget deficit widened", "current account deficit pakistan",
    "pakistan recession", "power outage", "energy crisis pakistan",
]

BULLISH_KEYWORDS = [
    "imf tranche approved", "imf deal pakistan", "sbp rate cut",
    "interest rate cut pakistan", "pkr recovers", "rupee stabilizes",
    "pakistan gdp growth", "psx record high", "cpec investment",
    "remittances surge pakistan", "current account surplus pakistan",
    "fatf grey list removed", "fiscal surplus pakistan",
    "pakistan credit rating upgrade",
]


# ---------------------------------------------------------------------------
# Sentiment scoring
# ---------------------------------------------------------------------------

def _score_text(text: str) -> int:
    """Return +1 for each bullish keyword, -1 for each bearish keyword."""
    t = text.lower()
    score = 0
    for kw in BULLISH_KEYWORDS:
        if kw in t:
            score += 1
    for kw in BEARISH_KEYWORDS:
        if kw in t:
            score -= 1
    return score


def get_macro_sentiment(lookback_days: int = 3) -> dict:
    """
    Fetch recent Pakistan financial news and return sentiment.

    Returns:
        {
          "sentiment":    "bullish" | "neutral" | "bearish",
          "score":        int,
          "headlines":    [ { "title": ..., "score": ... }, ... ],
          "source":       "newsapi" | "fallback",
          "summary":      "..."
        }
    """
    if not NEWSAPI_KEY or NEWSAPI_KEY == "your_newsapi_key_here":
        return _fallback_sentiment()

    try:
        from newsapi import NewsApiClient
        api  = NewsApiClient(api_key=NEWSAPI_KEY)
        from_dt = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        articles = api.get_everything(
            q="Pakistan stock exchange OR Pakistan economy OR SBP OR IMF Pakistan OR rupee",
            language="en",
            sort_by="publishedAt",
            from_param=from_dt,
            page_size=30,
        )

        total_score = 0
        headlines   = []

        for art in articles.get("articles", []):
            text  = (art.get("title", "") + " " + (art.get("description") or ""))
            score = _score_text(text)
            if score != 0:
                headlines.append({
                    "title":     art.get("title", ""),
                    "source":    art.get("source", {}).get("name", ""),
                    "url":       art.get("url", ""),
                    "score":     score,
                    "published": art.get("publishedAt", ""),
                })
            total_score += score

        # Determine sentiment
        if total_score >= 3:
            sentiment = "bullish"
            summary   = f"Macro sentiment is BULLISH (+{total_score}). Positive news flow around Pakistan economy."
        elif total_score <= -3:
            sentiment = "bearish"
            summary   = f"Macro sentiment is BEARISH ({total_score}). Negative news flow — consider holding or reducing positions."
        else:
            sentiment = "neutral"
            summary   = f"Macro sentiment is NEUTRAL (score: {total_score}). No strong directional bias."

        # Sort headlines by absolute score
        headlines.sort(key=lambda h: abs(h["score"]), reverse=True)

        return {
            "sentiment": sentiment,
            "score":     total_score,
            "headlines": headlines[:10],
            "source":    "newsapi",
            "summary":   summary,
        }

    except ImportError:
        logger.warning("newsapi-python not installed. Run: pip install newsapi-python")
        return _fallback_sentiment()
    except Exception as e:
        logger.warning(f"NewsAPI call failed: {e}")
        return _fallback_sentiment()


def _fallback_sentiment() -> dict:
    """Return neutral sentiment with a note about missing API key."""
    return {
        "sentiment": "neutral",
        "score":     0,
        "headlines": [],
        "source":    "fallback",
        "summary":   (
            "NewsAPI key not configured. Macro sentiment defaulting to NEUTRAL. "
            "Add NEWSAPI_KEY to your .env file for live Pakistan news sentiment. "
            "Get a free key at https://newsapi.org"
        ),
    }


# ---------------------------------------------------------------------------
# Pakistan-specific macro context (static reference data)
# ---------------------------------------------------------------------------

MACRO_CONTEXT = {
    "sbp_policy_rate_note": (
        "The SBP policy rate significantly impacts PSX valuations. "
        "A rate cut is bullish for equities (lower discount rates). "
        "A rate hike is bearish. Monitor SBP Monetary Policy Committee meetings."
    ),
    "imf_note": (
        "Pakistan's IMF Extended Fund Facility (EFF) is a key market driver. "
        "Tranche disbursements signal fiscal stability. Delays cause PKR weakness and PSX sell-offs."
    ),
    "pkr_note": (
        "PKR/USD rate affects import-heavy sectors (oil, chemicals, auto). "
        "Exporters (textiles, IT) benefit from a weaker PKR."
    ),
    "sector_rate_sensitivity": {
        "Technology":        "Low sensitivity — earns in PKR, exports in USD (positive for weak PKR)",
        "Oil & Gas":         "High sensitivity — imports denominated in USD",
        "Cement":            "Moderate — energy cost driven",
        "Fertilizer":        "Moderate — gas prices key input",
        "Banking":           "High — directly affected by SBP rate",
        "Textile":           "Benefits from weak PKR (export-oriented)",
        "Power":             "High — circular debt and government policy driven",
    },
}


# ---------------------------------------------------------------------------
# Ingestion Modules (yfinance + feedparser RSS bulletins)
# ---------------------------------------------------------------------------

import feedparser
import yfinance as yf

# Public macro news RSS feeds (no API key required)
_MACRO_RSS_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EKSE100&region=PK&lang=en-US",
]


def fetch_rss_macro_news(
    feed_urls: list[str] | None = None,
    max_items: int = 8,
    max_chars: int = 120,
) -> list[str]:
    """Fetch live macro bulletins from public RSS feeds via feedparser.

    Returns a de-duplicated list of headline strings, each strictly
    truncated to *max_chars* to keep the LLM token window small.
    """
    urls = feed_urls or _MACRO_RSS_FEEDS
    seen: set[str] = set()
    headlines: list[str] = []

    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = (entry.get("title") or "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                headlines.append(title[:max_chars])
                if len(headlines) >= max_items:
                    break
        except Exception as e:
            logger.warning(f"RSS macro feed fetch failed ({url}): {e}")

        if len(headlines) >= max_items:
            break

    return headlines


def fetch_company_news(
    symbol: str,
    max_items: int = 5,
    max_chars: int = 150,
) -> list[str]:
    """Fetch and cleanly parse company-specific news via yfinance, strictly truncated."""
    ticker_str = symbol.upper()
    if not ticker_str.endswith(".KA"):
        ticker_str = f"{ticker_str}.KA"
    try:
        t = yf.Ticker(ticker_str)
        news = t.news or []
        bulletins: list[str] = []
        for item in news[:max_items]:
            title = item.get("title", "")
            summary = item.get("summary", "") or item.get("description", "") or ""
            text = f"{title}: {summary}"[:max_chars]
            bulletins.append(text.strip())
        return bulletins
    except Exception as e:
        logger.warning(f"yfinance news fetch failed for {symbol}: {e}")
        return []


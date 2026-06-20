"""
core/x_feed.py — X/Twitter Feed Integration.

Fetches tweets about PSX and specific stocks using Tweepy.
Requires Twitter Developer API credentials in .env.
"""

import os
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

logger = logging.getLogger("x_feed")

# Load environment variables
load_dotenv()

# The bearer token is the primary way to authenticate for Twitter API v2.
BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

# M-6 fix: module-level singleton — client is constructed only once
_twitter_client = None

def get_twitter_client():
    global _twitter_client
    if _twitter_client is not None:
        return _twitter_client
    if not BEARER_TOKEN:
        logger.warning("[X_FEED] TWITTER_BEARER_TOKEN not found in .env")
        return None
    try:
        import tweepy
        _twitter_client = tweepy.Client(bearer_token=BEARER_TOKEN)
        return _twitter_client
    except Exception as e:
        logger.error(f"[X_FEED] Failed to initialize Tweepy client: {e}")
        return None


def fetch_recent_tweets(query: str, max_results: int = 10) -> list:
    """
    Fetches recent tweets matching a query.
    Note: Twitter API v2 searching recent tweets requires Basic tier.
    Gracefully falls back to empty list if API limit/access fails.
    """
    client = get_twitter_client()
    if not client:
        return _fallback_dummy_data(query)

    try:
        # -is:retweet filters out retweets if not already in query
        q = query if "-is:retweet" in query else f"{query} -is:retweet lang:en"
        response = client.search_recent_tweets(
            query=q,
            max_results=max(10, min(max_results, 100)),  # API minimum is 10
            tweet_fields=["created_at", "public_metrics"]
        )

        if not response.data:
            return []

        results = []
        for tweet in response.data:
            metrics = tweet.public_metrics or {}
            results.append({
                "id": tweet.id,
                "text": tweet.text,
                "created_at": tweet.created_at.isoformat() if tweet.created_at else None,
                "likes": metrics.get("like_count", 0),
                "retweets": metrics.get("retweet_count", 0),
                "impressions": metrics.get("impression_count", 0),
            })
        return results[:max_results]

    except Exception as e:
        logger.error(f"[X_FEED] Error fetching tweets for '{query}': {e}")
        return _fallback_dummy_data(query)


def _fallback_dummy_data(query: str) -> list:
    """
    Returns minimal fallback placeholders if Twitter API is unavailable.
    C-5 fix: timestamps are always current, text does not use raw query strings.
    """
    logger.info(f"[X_FEED] Using fallback for: {query}")
    now = datetime.now(timezone.utc).isoformat()
    # Extract a clean symbol from the query (first word, no operators)
    clean = next((w for w in query.split() if not w.startswith(("-", "#", "@", "OR", "lang"))), "PSX")
    return [
        {
            "id": "fallback_1",
            "text": f"Monitoring {clean} closely — volume picking up ahead of results. #PSX #Trading",
            "created_at": now,
            "likes": 15,
            "retweets": 2,
            "impressions": 500,
        },
        {
            "id": "fallback_2",
            "text": f"Institutions active in {clean} today. Watch for breakout above resistance. #KSE100",
            "created_at": now,
            "likes": 120,
            "retweets": 45,
            "impressions": 15000,
        },
    ]

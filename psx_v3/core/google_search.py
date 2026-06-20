"""
core/google_search.py — Real-time Google Search integration for PSX Advisory Agent.

Uses the Google Custom Search JSON API (free tier: 100 queries/day).
Falls back gracefully to an empty result set if the API key is missing or quota exceeded.

Setup:
    1. Go to https://console.cloud.google.com → Enable "Custom Search API"
    2. Create an API key and add to .env: GOOGLE_SEARCH_API_KEY=...
    3. Create a Programmable Search Engine at https://cse.google.com
       - Set to "Search the entire web"
    4. Get the Search Engine ID (cx) and add: GOOGLE_CSE_ID=...

The system uses Gemini's public search grounding concept but falls back to
Custom Search API when Gemini is not available.
"""

import os
import logging
import time
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("google_search")

GOOGLE_API_KEY = os.getenv("GOOGLE_SEARCH_API_KEY", "")
GOOGLE_CSE_ID  = os.getenv("GOOGLE_CSE_ID", "")

# Rate limiting: 100 queries/day free, be conservative
_DAILY_QUOTA   = 90   # leave 10 buffer
_QUERY_LOG_FILE = Path("data/google_search_quota.json")
_CACHE_DIR      = Path("data/search_cache")
_CACHE_TTL_HOURS = 4  # results stay fresh for 4 hours

_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_QUERY_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Quota management
# ---------------------------------------------------------------------------

def _load_quota() -> dict:
    if _QUERY_LOG_FILE.exists():
        try:
            with open(_QUERY_LOG_FILE) as f:
                data = json.load(f)
            if data.get("date") == datetime.now().strftime("%Y-%m-%d"):
                return data
        except Exception:
            pass
    return {"date": datetime.now().strftime("%Y-%m-%d"), "count": 0}


def _save_quota(data: dict):
    try:
        with open(_QUERY_LOG_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def _quota_remaining() -> int:
    q = _load_quota()
    return max(0, _DAILY_QUOTA - q.get("count", 0))


def _increment_quota():
    q = _load_quota()
    q["count"] = q.get("count", 0) + 1
    _save_quota(q)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_path(query: str) -> Path:
    h = hashlib.md5(query.lower().encode()).hexdigest()[:12]
    return _CACHE_DIR / f"{h}.json"


def _load_cache(query: str) -> Optional[list]:
    p = _cache_path(query)
    if not p.exists():
        return None
    try:
        with open(p) as f:
            data = json.load(f)
        age_hours = (time.time() - data.get("ts", 0)) / 3600
        if age_hours < _CACHE_TTL_HOURS:
            return data.get("results", [])
    except Exception:
        pass
    return None


def _save_cache(query: str, results: list):
    p = _cache_path(query)
    try:
        with open(p, "w") as f:
            json.dump({"ts": time.time(), "results": results}, f)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Core search function
# ---------------------------------------------------------------------------

def google_search(
    query: str,
    num_results: int = 5,
    date_restrict: str = "d7",   # restrict to last 7 days — 'd1','d3','d7','m1','m3'
    allow_cache: bool = True,
) -> list[dict]:
    """
    Perform a Google Custom Search and return structured results.

    Args:
        query:        The search query string.
        num_results:  Number of results to return (max 10 per call with free API).
        date_restrict: Restrict to recent results — 'd7' = last 7 days.
        allow_cache:  Return cached results if fresh (avoids burning quota).

    Returns:
        List of dicts: [{title, snippet, url, displayed_url, published_date}]
        Empty list if API unavailable or quota exhausted.
    """
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        logger.debug("[GSE] API key / CSE ID not configured — search disabled")
        return []

    # Cache check (free quota protection)
    cache_key = f"{query}|{date_restrict}"
    if allow_cache:
        cached = _load_cache(cache_key)
        if cached is not None:
            logger.debug(f"[GSE] Cache hit for: {query}")
            return cached[:num_results]

    # Quota check
    remaining = _quota_remaining()
    if remaining <= 0:
        logger.warning("[GSE] Daily quota exhausted — returning empty results")
        return []

    try:
        import requests
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key":         GOOGLE_API_KEY,
            "cx":          GOOGLE_CSE_ID,
            "q":           query,
            "num":         min(num_results, 10),
            "dateRestrict": date_restrict,
            "safe":        "off",
        }
        resp = requests.get(url, params=params, timeout=10)
        _increment_quota()

        if resp.status_code == 429:
            logger.warning("[GSE] Rate limited (429) — returning empty")
            return []

        if resp.status_code != 200:
            logger.warning(f"[GSE] API error {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        items = data.get("items", [])

        results = []
        for item in items[:num_results]:
            # Extract publication date from metatags or pagemap if available
            pub_date = ""
            pagemap = item.get("pagemap", {})
            metatags = pagemap.get("metatags", [{}])
            if metatags:
                pub_date = (
                    metatags[0].get("article:published_time", "")
                    or metatags[0].get("og:article:published_time", "")
                    or metatags[0].get("date", "")
                )

            results.append({
                "title":          item.get("title", ""),
                "snippet":        item.get("snippet", ""),
                "url":            item.get("link", ""),
                "displayed_url":  item.get("displayLink", ""),
                "published_date": pub_date[:10] if pub_date else "",
            })

        _save_cache(cache_key, results)
        logger.info(f"[GSE] Fetched {len(results)} results for: '{query}' ({remaining - 1} quota remaining)")
        return results

    except ImportError:
        logger.error("[GSE] requests library not available")
        return []
    except Exception as e:
        logger.error(f"[GSE] Search failed for '{query}': {e}")
        return []


# ---------------------------------------------------------------------------
# PSX-specific convenience wrappers
# ---------------------------------------------------------------------------

def search_stock_news(symbol: str, company_name: str = "", lookback_days: int = 7) -> list[dict]:
    """
    Fetch recent news, press releases, and analysis for a PSX stock.

    Args:
        symbol:       PSX ticker e.g. "SYS"
        company_name: Optional full name e.g. "Systems Limited"
        lookback_days: Restrict to last N days.

    Returns:
        List of search result dicts.
    """
    date_code = f"d{lookback_days}" if lookback_days <= 30 else f"m{lookback_days // 30}"
    name_part = f'"{company_name}" OR ' if company_name else ""
    query = (
        f'{name_part}"{symbol}" PSX stock news OR earnings OR dividend OR results '
        f'site:brecorder.com OR site:thenews.com.pk OR site:profit.pakistantoday.com.pk '
        f'OR site:dawn.com OR site:propakistani.pk OR site:businessrecorder.com'
    )
    results = google_search(query, num_results=6, date_restrict=date_code)
    if not results:
        # Broader fallback without site restriction
        query2 = f'{name_part}"{symbol}" Pakistan stock exchange news'
        results = google_search(query2, num_results=5, date_restrict=date_code)
    return results


def search_macro_pakistan_news(lookback_days: int = 3) -> list[dict]:
    """
    Fetch Pakistan macro-economic news (SBP, IMF, PKR, KSE-100).

    Returns:
        List of search result dicts.
    """
    date_code = f"d{lookback_days}"
    query = (
        "Pakistan economy 2025 OR 2026 SBP OR IMF OR rupee OR KSE-100 OR inflation "
        "site:brecorder.com OR site:dawn.com OR site:geo.tv OR site:thenews.com.pk"
    )
    results = google_search(query, num_results=8, date_restrict=date_code)
    if not results:
        results = google_search("Pakistan stock market news today", num_results=6, date_restrict=date_code)
    return results


def search_sector_news(sector: str, lookback_days: int = 7) -> list[dict]:
    """Fetch sector-level news relevant to PSX."""
    query = f'"{sector}" Pakistan stock 2025 OR 2026 news earnings outlook'
    return google_search(query, num_results=5, date_restrict=f"d{lookback_days}")


def format_search_results_for_llm(results: list[dict], max_chars: int = 3000) -> str:
    """
    Format Google search results into a compact text block for LLM prompts.
    Includes source, title, snippet and date. Total is capped at max_chars.
    """
    if not results:
        return ""

    lines = ["GOOGLE SEARCH RESULTS (real-time web):"]
    total = 0
    for i, r in enumerate(results, 1):
        date_tag = f" [{r['published_date']}]" if r.get("published_date") else ""
        block = (
            f"\n[{i}] {r['title']}{date_tag}\n"
            f"    Source: {r['displayed_url']}\n"
            f"    {r['snippet']}\n"
        )
        if total + len(block) > max_chars:
            break
        lines.append(block)
        total += len(block)

    return "\n".join(lines)


def get_quota_status() -> dict:
    """Return current daily quota usage for display in the UI."""
    q = _load_quota()
    used = q.get("count", 0)
    return {
        "date":      q.get("date"),
        "used":      used,
        "remaining": max(0, _DAILY_QUOTA - used),
        "limit":     _DAILY_QUOTA,
        "enabled":   bool(GOOGLE_API_KEY and GOOGLE_CSE_ID),
    }

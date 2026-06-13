"""
core/news_filter.py — Strict credibility, hype, opinion, and bot filtering for market news and social feeds.
"""

import re
import logging
from collections import Counter

logger = logging.getLogger("news_filter")

HYPE_WORDS = [
    r"to\s+the\s+moon", r"short\s+squeeze", r"generational\s+buy",
    r"100x\s+gem", r"100x", r"rocket", r"lambos?", r"easy\s+money",
    r"guaranteed\s+profit", r"pump", r"next\s+tesla", r"buy\s+now\s+or\s+cry"
]

FACT_INDICATORS = [
    r"\d+%", r"revenue", r"profit", r"dividend", r"earning", r"margin", r"growth",
    r"bought", r"sold", r"shares", r"sec\s+filing", r"announcement", r"director",
    r"ceo", r"board", r"meeting", r"production", r"capacity", r"increase", r"decrease"
]

def clean_hype_language(text: str) -> str:
    """Removes standard hype keywords from text."""
    cleaned = text
    for word in HYPE_WORDS:
        cleaned = re.sub(word, "[HYPE]", cleaned, flags=re.IGNORECASE)
    return cleaned

def filter_and_format_news(news_items: list[dict]) -> dict:
    """
    Applies strict heuristics to filter news items and social forum posts:
    1. Source Credibility Scoring
    2. Logical Fallacy & Manipulation (Hype / Rant / Bot) Filter
    3. The "Talk is Cheap" Heuristic (Opinion vs. Facts)
    4. Contrarian Cross-Check

    Returns a dict with three lists:
    - 'verified_facts': High-signal hard facts.
    - 'retail_sentiment': Unverified retail sentiment stripped of hype.
    - 'discarded_noise': Explanations/content of items filtered out.
    """
    verified_facts = []
    retail_sentiment = []
    discarded_noise = []

    # 1. Detect Coordinated Bot Behavior
    # Group items by content similarity (simple exact/near-exact matches)
    content_counts = Counter([item["content"].strip().lower() for item in news_items])
    bot_contents = {content for content, count in content_counts.items() if count >= 3}

    # Identify if we have any counter-arguments in the dataset (bearish facts/sentiment)
    has_bearish_signals = any(
        item["sentiment"] == "bearish" or any(re.search(w, item["content"], re.I) for w in ["drop", "loss", "fell", "decrease", "devaluation", "debt"])
        for item in news_items
    )

    for item in news_items:
        source = item.get("source", "Unknown")
        content = item.get("content", "")
        user = item.get("user", "")
        
        # Check source type
        is_institutional = source in ["Reuters", "Bloomberg", "SEC filings", "PSX Official Filing"]

        # Check Bot behavior
        if content.strip().lower() in bot_contents:
            discarded_noise.append({
                "source": source,
                "content": content,
                "reason": "Flagged as coordinated bot behavior (repetitive phrasing across posts)."
            })
            continue

        # Check Hype words
        has_hype = any(re.search(word, content, re.IGNORECASE) for word in HYPE_WORDS)
        if has_hype:
            discarded_noise.append({
                "source": source,
                "content": content,
                "reason": "Contains flagged hype language (e.g. 'to the moon', 'squeeze')."
            })
            continue

        # 2. Check for "Talk is Cheap" and pure sentimental rants
        has_numbers_or_facts = any(re.search(ind, content, re.IGNORECASE) for ind in FACT_INDICATORS)
        is_opinion = any(re.search(w, content, re.IGNORECASE) for w in [r"i\s+think", r"in\s+my\s+opinion", r"i\s+believe", r"will\s+double"])

        if is_institutional:
            # Institutional is verified high-signal
            verified_facts.append({
                "source": source,
                "content": content,
                "url": item.get("url", "")
            })
        else:
            # Retail source (X, Reddit, Discord)
            if is_opinion and not has_numbers_or_facts:
                discarded_noise.append({
                    "source": source,
                    "content": content,
                    "reason": "Filtered by 'Talk is Cheap' heuristic (pure opinion/speculation without facts)."
                })
            elif not has_numbers_or_facts and any(w in content.lower() for w in ["manipulate", "unfair", "makers", "hate"]):
                discarded_noise.append({
                    "source": source,
                    "content": content,
                    "reason": "Discarded as emotional rant containing no underlying fundamental or technical catalysts."
                })
            else:
                # Retain retail claim but classify as retail sentiment, clean hype if any
                cleaned_content = clean_hype_language(content)
                
                # Contrarian Cross-Check
                signal_to_noise = "Normal"
                is_strong_bullish = item.get("sentiment") == "bullish" and any(w in content.lower() for w in ["buy", "undervalued", "growth"])
                if is_strong_bullish and not has_bearish_signals:
                    signal_to_noise = "Reduced (Strong bullish claim with zero contrarian balance in feed)"

                retail_sentiment.append({
                    "source": source,
                    "user": user,
                    "content": cleaned_content,
                    "signal_rating": signal_to_noise
                })

    return {
        "verified_facts": verified_facts,
        "retail_sentiment": retail_sentiment,
        "discarded_noise": discarded_noise
    }

def format_filtered_news_to_markdown(filtered: dict) -> str:
    """Formats the filtered news dictionary into the required Markdown headers."""
    md = []
    
    md.append("### [Verified High-Signal Facts]")
    if filtered["verified_facts"]:
        for item in filtered["verified_facts"]:
            md.append(f"- **{item['source']}**: {item['content']}")
    else:
        md.append("- *No verified primary source news available.*")

    md.append("\n### [Unverified Retail Sentiment]")
    if filtered["retail_sentiment"]:
        for item in filtered["retail_sentiment"]:
            rating_str = f" *(Signal-to-Noise: {item['signal_rating']})*" if item['signal_rating'] != "Normal" else ""
            md.append(f"- **{item['source']} ({item['user']})**: {item['content']}{rating_str}")
    else:
        md.append("- *No verified retail sentiment.*")

    md.append("\n### [Discarded Noise/Hype]")
    if filtered["discarded_noise"]:
        for item in filtered["discarded_noise"]:
            md.append(f"- **{item['source']}**: \"{item['content']}\" — *Reason: {item['reason']}*")
    else:
        md.append("- *No noise was filtered out.*")
        
    return "\n".join(md)

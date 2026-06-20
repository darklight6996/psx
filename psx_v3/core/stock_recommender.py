"""
core/stock_recommender.py — AI Stock Recommender.

Uses the existing LLM integration to recommend a list of stocks to analyze further,
based on current daily results and macro sentiment.
"""

import logging
import json
from core.llm import ollama_chat, pick_model, get_available_models, parse_json_response

logger = logging.getLogger("stock_recommender")

RECOMMENDER_PROMPT = """You are an expert AI trading assistant. 
Based on the provided daily market results and macro sentiment, pick exactly 3 to 5 stock symbols that look the most promising for a deeper Machine Learning analysis.
Prioritize stocks with strong "BUY" ratings, high technical scores, or bullish anomaly flags.

Respond ONLY with a valid JSON object in this format:
{
    "recommended_symbols": ["SYM1", "SYM2", "SYM3"],
    "reasoning": "Brief explanation of why these were chosen."
}
"""

def recommend_stocks_for_ml(daily_results: dict, macro: dict) -> dict:
    """
    Returns a dictionary with recommended symbols and reasoning.
    """
    if not daily_results:
        return {"recommended_symbols": [], "reasoning": "No daily results available to make recommendations."}
        
    models = get_available_models()
    model = pick_model("qwen2.5:7b", models)
    if not model:
        logger.warning("No LLM available for stock recommendation.")
        return {"recommended_symbols": [], "reasoning": "LLM not available."}
        
    # Build a compact summary of the top 20 stocks to avoid blowing up the context window
    # Sort by score
    sorted_stocks = sorted(
        [r for sym, r in daily_results.items() if "error" not in r],
        key=lambda x: x.get("advisory", {}).get("score", 0),
        reverse=True
    )[:20]
    
    summary_lines = []
    for s in sorted_stocks:
        sym = s.get("symbol")
        score = s.get("advisory", {}).get("score", 0)
        rating = s.get("advisory", {}).get("rating", "UNKNOWN")
        trend = s.get("trend", "UNKNOWN")
        flags = s.get("anomaly_flags", [])
        summary_lines.append(f"{sym}: Score {score}, Rating {rating}, Trend {trend}, Anomalies: {flags}")
        
    user_msg = f"Macro Sentiment: {macro.get('sentiment', 'Unknown')}\n"
    user_msg += "Top Scored Stocks:\n" + "\n".join(summary_lines)
    
    try:
        raw_resp = ollama_chat(model, RECOMMENDER_PROMPT, user_msg)
        parsed = parse_json_response(raw_resp)
        return {
            "recommended_symbols": parsed.get("recommended_symbols", []),
            "reasoning": parsed.get("reasoning", "No reasoning provided.")
        }
    except Exception as e:
        logger.error(f"[Recommender] Failed to generate recommendations: {e}")
        return {"recommended_symbols": [], "reasoning": f"Error: {e}"}

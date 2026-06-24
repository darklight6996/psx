"""
council/ollama_council.py — Local AI Board Room (Layer 3)
"""

import os
import json
import logging
import requests
from datetime import datetime
from typing import Optional, Any

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Recommended models
EXPLAINER_MODEL = "qwen2.5:14b"
SHARIAH_MODEL = "qwen2.5:14b"
ANALYST_MODELS = "qwen2.5:7b"
CHAIRMAN_MODEL = "qwen2.5:7b"

# Styling badge maps
VERDICT_COLOR = {
    "BUY": "#10b981",
    "HOLD": "#f59e0b",
    "SELL": "#ef4444",
    "COMPLIANT": "#10b981",
    "NON-COMPLIANT": "#ef4444",
    "REVIEW": "#f59e0b",
    "UNKNOWN": "#94a3b8"
}
VERDICT_BG = {
    "BUY": "#064e3b",
    "HOLD": "#78350f",
    "SELL": "#4c0519",
    "COMPLIANT": "#064e3b",
    "NON-COMPLIANT": "#4c0519",
    "REVIEW": "#78350f",
    "UNKNOWN": "#1e293b"
}

def get_available_models() -> list[str]:
    """Return list of models currently pulled in Ollama."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if resp.status_code == 200:
            return [m["name"] for m in resp.json().get("models", [])]
    except Exception as e:
        logger.warning(f"Cannot connect to Ollama at {OLLAMA_BASE_URL}: {e}")
    return []

def pick_model(preferred: str, available: list[str]) -> Optional[str]:
    if preferred in available:
        return preferred
    base = preferred.split(":")[0]
    for a in available:
        if a.startswith(base):
            return a
    if available:
        return available[0]
    return None

def ollama_chat(model: str, system: str, user_msg: str, timeout: int = 90) -> Optional[str]:
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system",  "content": system},
                {"role": "user",    "content": user_msg},
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 1500},
        }
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=timeout,
        )
        if resp.status_code == 200:
            return resp.json()["message"]["content"]
    except Exception as e:
        logger.error(f"Ollama call failed ({model}): {e}")
    return None

def parse_json_response(text: str) -> dict:
    if not text:
        return {}
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip().lstrip("json").strip()
            if part.startswith("{"):
                text = part
                break
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass
    return {"raw_text": text[:500]}

import concurrent.futures

def parallel_ollama_chat(tasks: list[dict], timeout_per_call: int = 45) -> list[Optional[str]]:
    """Run multiple Ollama chat calls in parallel."""
    results = [None] * len(tasks)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_to_task = {executor.submit(ollama_chat, task["model"], task["system"], task["user_msg"], timeout_per_call): i for i, task in enumerate(tasks)}
        for future in concurrent.futures.as_completed(future_to_task):
            index = future_to_task[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                logger.error(f"Parallel Ollama chat generated an exception: {exc}")
    return results


# --- ANALYST SYSTEMS ---

SHARIAH_SYSTEM = """You are a Shariah Finance Scholar expert in Pakistani Islamic finance.
Your role is strictly notes-only: you cannot decide or override compliance status.
Provide a clear analysis and explanation of the compliance status based on the provided Meezan Shariah engine report, and investigate any gray areas.

Respond in strict JSON only:
{
  "role": "Shariah Scholar",
  "notes": "A concise summary explaining the compliance status.",
  "independent_investigation": "A detailed paragraph on any grey areas or aspects requiring deeper investigation."
}"""

BULL_ANALYST_SYSTEM = """You are a Bull Analyst for a stock advisory agent. Your role is to identify bullish signals and present a compelling argument for a BUY or HOLD verdict.
Analyze the stock using specific bullish trading techniques (e.g. Trend Line breakout, Golden Cross, Volume Accumulation, RSI oversold recovery).
You must explain the specific technique used, cite supporting technical metrics/announcements, and avoid hallucinating.

Respond in strict JSON only:
{
  "role": "Bull Analyst",
  "verdict": "BUY / HOLD / SELL",
  "trading_technique": "Specific technical/fundamental analysis technique used",
  "rationale": "A concise bullish argument (2-3 sentences) citing specific indicators and news.",
  "score_impact": "+ / - (points)"
}"""

BEAR_ANALYST_SYSTEM = """You are a Bear Analyst for a stock advisory agent. Your role is to identify bearish signals and present a compelling argument for a SELL or HOLD verdict.
Analyze the stock using specific bearish trading techniques (e.g. Overhead Resistance, RSI overbought, MACD bearish crossovers, Volume fatigue, Support breaches).

Respond in strict JSON only:
{
  "role": "Bear Analyst",
  "verdict": "BUY / HOLD / SELL",
  "trading_technique": "Specific bearish analysis technique used",
  "rationale": "A concise bearish argument (2-3 sentences) based on the provided data.",
  "score_impact": "+ / - (points)"
}"""

QUANT_ANALYST_SYSTEM = """You are a Quant Analyst for a stock advisory agent. Your role is to analyze the stock based purely on quantitative technical indicators and their mathematical values (RSI, MACD, ma_20, returns).

Respond in strict JSON only:
{
  "role": "Quant Analyst",
  "verdict": "BUY / HOLD / SELL",
  "trading_technique": "Quantitative strategy used",
  "rationale": "A concise quantitative argument (2-3 sentences) based on mathematical metrics.",
  "score_impact": "+ / - (points)"
}"""

RISK_ANALYST_SYSTEM = """You are a Risk Analyst for a stock advisory agent. Your role is to identify and assess potential risks associated with the stock (volatility, drawdowns, liquidity risk).

Respond in strict JSON only:
{
  "role": "Risk Analyst",
  "verdict": "BUY / HOLD / SELL",
  "trading_technique": "Risk management technique used",
  "rationale": "A concise risk-focused argument (2-3 sentences) based on risk metrics.",
  "score_impact": "+ / - (points)"
}"""

MACRO_ANALYST_SYSTEM = """You are a Macro Analyst. Assess the broader economic/market sentiment (KIBOR policy rates, exchange rate shocks, inflation) and its sector-specific sensitivity.

Respond in strict JSON only:
{
  "role": "Macro Analyst",
  "verdict": "BUY / HOLD / SELL",
  "trading_technique": "Macro-economic analysis technique used",
  "rationale": "A concise macro-economic argument (2-3 sentences) based on the macroeconomic environment.",
  "score_impact": "+ / - (points)"
}"""

CHAIRMAN_SYSTEM = """You are the Chairman of the AI Board Room. Your role is NOT to decide the final stock rating or override Shariah status, target prices, or stop losses.
Your task is to challenge, validate, and contextualize the quantitative recommendations. Synthesize the debate between the specialists (Bull, Bear, Quant, Risk, Macro) and detail the catalyst for success and the risks of failure.

Respond in strict JSON only:
{
  "role": "Chairman",
  "validation_status": "VALIDATED / CHALLENGED / WARNED",
  "explanation": "A comprehensive explanation (3-5 paragraphs) of the board's synthesis, highlighting catalysts of success and risks of failure.",
  "key_drivers": ["list of primary factors supporting validation"],
  "risk_factors": ["list of primary risk factors challenging the rating"],
  "analyst_consensus": "Brief summary of analyst convergence or divergence."
}"""

EXPLAINER_SYSTEM = """You are an Explainer AI for a deterministic trading system.
Provide a clear explanation of why the system reached its decision.

Respond in strict JSON only:
{
  "role": "Explainer",
  "explanation": "2-3 paragraphs explaining the decision based on indicator data.",
  "key_drivers": ["driver 1", "driver 2"],
  "risk_factors": ["risk 1", "risk 2"]
}"""

def run_ai_council(
    symbol: str,
    snapshot_data: dict,
    shariah_engine_verdict: str,
    shariah_engine_report: dict,
    macro_sentiment: str = "neutral",
    analyst_weights: Optional[dict] = None,
    progress_callback=None,
    analyst_inputs: Optional[dict[str, str]] = None,
    quant_verdict: str = "HOLD",
    quant_score: float = 50.0
) -> dict:
    """
    Runs the full multi-agent AI Council debate, challenging and validating the quant recommendation.
    """
    available_models = get_available_models()
    if not available_models:
        return {"error": "Ollama is not running or no models pulled."}

    analyst_model_name = pick_model(ANALYST_MODELS, available_models)
    chairman_model_name = pick_model(CHAIRMAN_MODEL, available_models)
    shariah_model_name = pick_model(SHARIAH_MODEL, available_models)
    explainer_model_name = pick_model(EXPLAINER_MODEL, available_models)

    if not (analyst_model_name and chairman_model_name and shariah_model_name and explainer_model_name):
        missing_models = []
        if not analyst_model_name: missing_models.append(ANALYST_MODELS)
        if not chairman_model_name: missing_models.append(CHAIRMAN_MODEL)
        if not shariah_model_name: missing_models.append(SHARIAH_MODEL)
        if not explainer_model_name: missing_models.append(EXPLAINER_MODEL)
        return {"error": f"Missing required Ollama models: {', '.join(missing_models)}."}

    shariah_verdict = shariah_engine_verdict

    # 1. Shariah Scholar (LLM analysis - Notes-only)
    if progress_callback:
        progress_callback(1, 7, "Consulting Shariah Scholar LLM...")
    
    sh_user_prompt = f"STOCK: {symbol}\nSHARIAH ENGINE VERDICT: {shariah_engine_verdict}\nSHARIAH ENGINE REPORT:\n{json.dumps(shariah_engine_report, indent=2)}"
    sh_raw = ollama_chat(shariah_model_name, SHARIAH_SYSTEM, sh_user_prompt) if shariah_model_name else None
    shariah_llm_output = parse_json_response(sh_raw) if sh_raw else {"notes": "LLM analysis failed.", "independent_investigation": "Could not generate LLM Shariah analysis."}

    # 2. Run Analysts in parallel
    if progress_callback:
        progress_callback(2, 7, "Analysts are debating...")

    analyst_roles = {
        "Bull Analyst": BULL_ANALYST_SYSTEM,
        "Bear Analyst": BEAR_ANALYST_SYSTEM,
        "Quant Analyst": QUANT_ANALYST_SYSTEM,
        "Risk Analyst": RISK_ANALYST_SYSTEM,
        "Macro Analyst": MACRO_ANALYST_SYSTEM,
    }
    
    analyst_tasks = []
    for role, system_prompt in analyst_roles.items():
        if analyst_inputs and role in analyst_inputs:
            analyst_user_prompt = analyst_inputs[role]
        else:
            analyst_user_prompt = f"STOCK: {symbol}\nDATA:\n{json.dumps(snapshot_data, indent=2)}\nMACRO SENTIMENT: {macro_sentiment}\nQUANT RECOMMENDED VERDICT: {quant_verdict} (Score: {quant_score})"
        
        analyst_tasks.append({"model": analyst_model_name, "system": system_prompt, "user_msg": analyst_user_prompt})

    analyst_raw_outputs = parallel_ollama_chat(analyst_tasks)
    
    analyst_results = {}
    for i, role in enumerate(analyst_roles.keys()):
        output = analyst_raw_outputs[i]
        parsed = parse_json_response(output) if output else {"verdict": "HOLD", "trading_technique": "Fallback analysis", "rationale": f"Failed to generate {role} rationale.", "score_impact": "0"}
        analyst_results[role] = parsed
    
    # 3. Chairman synthesizes debate & validates quant verdict
    if progress_callback:
        progress_callback(3, 7, "Chairman is validating...")

    chairman_prompt_data = {
        "stock": symbol,
        "quant_verdict": quant_verdict,
        "quant_score": quant_score,
        "shariah_verdict": shariah_verdict,
        "shariah_llm_notes": shariah_llm_output.get("notes", "N/A"),
        "macro_sentiment": macro_sentiment,
        "analyst_opinions": analyst_results
    }
    chairman_user_prompt = f"DEBATE DATA:\n{json.dumps(chairman_prompt_data, indent=2)}"
    
    chairman_raw = ollama_chat(chairman_model_name, CHAIRMAN_SYSTEM, chairman_user_prompt)
    chairman_decision = parse_json_response(chairman_raw) if chairman_raw else {
        "validation_status": "VALIDATED",
        "explanation": "Chairman validation failed to generate.",
        "key_drivers": [],
        "risk_factors": [],
        "analyst_consensus": "N/A"
    }
    
    # 4. Explainer
    if progress_callback:
        progress_callback(4, 7, "Generating System Explanation...")

    expl_brief = f"""
STOCK: {symbol}
QUANT VERDICT: {quant_verdict} (Score: {quant_score})
CHAIRMAN VALIDATION: {chairman_decision.get('validation_status')}
RAW DATA SNAPSHOT:
{json.dumps(snapshot_data, indent=2)}
"""
    explainer_raw = ollama_chat(explainer_model_name, EXPLAINER_SYSTEM, expl_brief)
    explainer_result = parse_json_response(explainer_raw) if explainer_raw else {"explanation": "Explanation failed to generate.", "key_drivers": [], "risk_factors": []}
    
    return {
        "symbol": symbol,
        "council_verdict": quant_verdict, # Locked to quant verdict
        "council_score": quant_score,     # Locked to quant score
        "validation_status": chairman_decision.get("validation_status", "VALIDATED"),
        "analyst_verdicts": analyst_results,
        "chairman_notes": chairman_decision.get("explanation"),
        "chairman_key_drivers": chairman_decision.get("key_drivers", []),
        "chairman_risk_factors": chairman_decision.get("risk_factors", []),
        "shariah_llm_output": shariah_llm_output,
        "shariah_engine_report": shariah_engine_report,
        "explainer": explainer_result
    }

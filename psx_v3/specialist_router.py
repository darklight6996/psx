"""
specialist_router.py — On-demand specialist opinions for the PSX V4 Advisor.

The advisor decides WHEN to invoke a specialist based on trigger keywords
in the user's message. Specialists are NOT run automatically on every turn.

Each specialist is a single focused Ollama call using the existing
system prompts from ollama_council.py. No duplication of prompt text —
we import and reuse them directly.

Specialists available:
  risk      → volatility, ATR, downside scenarios, stop loss sizing
  shariah   → compliance deep-dive, grey areas, purification
  macro     → KIBOR, sector policy, PKR, IMF, government action
  quant     → RSI, MACD, ML signals, anomaly validation

The router returns a short specialist opinion (3–5 sentences max)
that the advisor engine merges into its final response.
"""

import logging
from typing import Optional

logger = logging.getLogger("specialist_router")

# ---------------------------------------------------------------------------
# Trigger detection
# ---------------------------------------------------------------------------

SPECIALIST_TRIGGERS: dict[str, list[str]] = {
    "risk": [
        "stop loss", "risk", "downside", "volatility", "worst case",
        "how much to lose", "drawdown", "position size", "ATR",
        "how much to invest", "how many shares", "capital at risk",
        "circuit breaker", "lower lock", "can i afford",
    ],
    "shariah": [
        "halal", "haram", "shariah", "islamic", "compliant", "permissible",
        "grey area", "gray area", "purification", "sadaqah", "meezan",
        "interest", "riba", "debt ratio", "is it allowed",
    ],
    "macro": [
        "sector", "SBP", "sbp", "interest rate", "IMF", "imf", "PKR", "pkr",
        "KIBOR", "kibor", "inflation", "rupee", "devaluation", "policy",
        "government", "budget", "NEPRA", "OGRA", "circular debt",
        "macroeconomic", "economy", "gdp", "current account",
    ],
    "quant": [
        "RSI", "rsi", "MACD", "macd", "EMA", "ema", "bollinger",
        "technical", "indicator", "signal", "ML", "machine learning",
        "anomaly", "volume spike", "golden cross", "death cross",
        "breakout", "momentum score", "pattern",
    ],
}


def detect_specialists_needed(user_message: str) -> list[str]:
    """
    Scan user message for trigger keywords and return list of
    specialist roles that should be consulted.

    Returns a deduplicated list ordered by relevance (most triggers first).
    """
    msg_lower = user_message.lower()
    hit_counts: dict[str, int] = {}

    for role, triggers in SPECIALIST_TRIGGERS.items():
        count = sum(1 for t in triggers if t.lower() in msg_lower)
        if count > 0:
            hit_counts[role] = count

    # Sort by hit count descending, return role names
    return [role for role, _ in sorted(hit_counts.items(),
                                       key=lambda x: x[1], reverse=True)]


# ---------------------------------------------------------------------------
# Specialist system prompts (focused, shorter than full board room)
# ---------------------------------------------------------------------------

SPECIALIST_SYSTEMS: dict[str, str] = {

    "risk": """You are a Risk Specialist for a Pakistan Stock Exchange advisory system.
Your role: assess downside risk, position sizing, and stop loss for the given situation.
Be specific and numerical. Reference ATR, volatility percentile, and PKR amounts where possible.
PSX context: circuit breaker is 7.5% daily. Illiquid stocks can lock at lower circuit with no buyers.
Keep your response to 3–5 sentences. End with a concrete risk verdict: LOW / MEDIUM / HIGH / EXTREME.""",

    "shariah": """You are a Shariah Finance Specialist for a Pakistan Stock Exchange advisory system.
Your role: provide notes-only Shariah analysis based on the provided compliance data.
You CANNOT override the Shariah engine's status — you can only add context and flag grey areas.
Reference the 5 KMI criteria: core business, debt ratio <33%, non-halal income <5%,
illiquid assets >25%, market cap vs net liquid assets.
If grey area: suggest what manual verification is needed (check latest annual report for X).
Keep your response to 3–5 sentences.""",

    "macro": """You are a Macro Specialist for a Pakistan Stock Exchange advisory system.
Your role: assess the macroeconomic and sector-level context for the given stock/situation.
Key PSX macro factors: SBP KIBOR rate (bearish if >15%, bullish if <12%), IMF program status,
PKR/USD trajectory, circular debt (affects power/energy stocks), CPEC-related infrastructure spending.
Sector sensitivities: tech = PKR hedge (benefits from weak PKR), fertiliser = gas price dependent,
cement = PSDP budget sensitive, banks = KIBOR sensitive (avoid for Shariah investors).
Keep your response to 3–5 sentences. End with: macro tailwind / headwind / neutral for this stock.""",

    "quant": """You are a Quantitative Specialist for a Pakistan Stock Exchange advisory system.
Your role: validate or challenge the technical signal interpretation using the provided indicator data.
PSX calibration notes: RSI frequently runs to 80+ before reversing (retail-heavy market).
ADX needs >30 sustained for 5+ days to confirm a real trend on PSX.
Volume spikes >2x average are significant on PSX — confirm if institutional or retail noise.
MACD crossovers on PSX daily charts have ~58% hit rate historically.
Keep your response to 3–5 sentences. End with: signal CONFIRMED / WEAK / CONTRADICTED.""",
}


# ---------------------------------------------------------------------------
# Run a single specialist
# ---------------------------------------------------------------------------

def run_specialist(
    role: str,
    symbol: str,
    context_data: dict,
    user_question: str,
    available_models: list[str] = None,
) -> dict:
    """
    Run a single specialist Ollama call.

    Args:
        role:             'risk' | 'shariah' | 'macro' | 'quant'
        symbol:           PSX ticker
        context_data:     dict of relevant data (from advisor_tools.gather_symbol_context)
        user_question:    the original user message (for context)
        available_models: list from ollama_council.get_available_models()

    Returns:
        {
            "role": str,
            "opinion": str,
            "verdict_tag": str | None,   # extracted closing verdict if present
            "success": bool,
        }
    """
    system_prompt = SPECIALIST_SYSTEMS.get(role)
    if not system_prompt:
        return {"role": role, "opinion": f"Unknown specialist role: {role}", "success": False}

    # Build user message — focused brief with only relevant data
    user_msg = _build_specialist_brief(role, symbol, context_data, user_question)

    try:
        from council.ollama_council import ollama_chat, pick_model, get_available_models
        models = available_models or get_available_models()
        # Prefer the same model tiers as V3 council
        preferred = "qwen2.5:7b"
        model = pick_model(preferred, models)
        if not model:
            return {
                "role": role,
                "opinion": "Ollama unavailable — specialist could not be consulted.",
                "success": False,
            }

        raw = ollama_chat(model, system_prompt, user_msg, timeout=45)
        if not raw:
            return {
                "role": role,
                "opinion": "Specialist timed out or returned empty response.",
                "success": False,
            }

        # Try to extract a closing verdict tag (CONFIRMED/WEAK/HIGH/etc.)
        verdict_tag = _extract_verdict_tag(raw, role)

        return {
            "role": role,
            "opinion": raw.strip(),
            "verdict_tag": verdict_tag,
            "success": True,
        }

    except Exception as e:
        logger.error(f"Specialist {role} failed for {symbol}: {e}")
        return {
            "role": role,
            "opinion": f"Specialist error: {e}",
            "success": False,
        }


def _build_specialist_brief(
    role: str,
    symbol: str,
    ctx: dict,
    user_question: str,
) -> str:
    """Build a focused data brief for a specialist. Role-specific data selection."""

    base = f"STOCK: {symbol}\nUSER QUESTION: {user_question}\n\n"

    if role == "risk":
        targets = ctx.get("targets") or {}
        ml = ctx.get("ml") or {}
        return base + (
            f"CURRENT PRICE: PKR {ctx.get('price') or ctx.get('live_price') or 'N/A'}\n"
            f"SYSTEM VERDICT: {ctx.get('verdict', 'N/A')} (Score: {ctx.get('final_score', 'N/A')})\n"
            f"ATR: {targets.get('atr', 'N/A')}\n"
            f"TARGET PRICE: PKR {targets.get('target_price', 'N/A')} (+{targets.get('target_pct', '?')}%)\n"
            f"STOP LOSS: PKR {targets.get('stop_loss', 'N/A')} (-{targets.get('stop_pct', '?')}%)\n"
            f"RISK/REWARD: {targets.get('risk_reward_ratio', 'N/A')}\n"
            f"ML RELIABILITY: {ml.get('ml_signal_reliable', False)}\n"
            f"CONFIDENCE LABEL: {ctx.get('risk_matrix', {}).get('confidence_label', 'N/A') if isinstance(ctx.get('risk_matrix'), dict) else 'N/A'}\n"
        )

    elif role == "shariah":
        return base + (
            f"SHARIAH STATUS: {ctx.get('shariah_status', 'UNKNOWN')}\n"
            f"KMI LISTED: {ctx.get('kmi_listed', 'N/A')}\n"
            f"SECTOR: {ctx.get('sector_rotation', {}).get('sector', 'Unknown') if isinstance(ctx.get('sector_rotation'), dict) else 'Unknown'}\n"
        )

    elif role == "macro":
        macro = ctx.get("macro") or {}
        sr = ctx.get("sector_rotation") or {}
        ep = ctx.get("earnings_proximity") or {}
        return base + (
            f"KIBOR RATE: {macro.get('kibor_rate', 'N/A')}% ({macro.get('kibor_sentiment', 'N/A')})\n"
            f"MARKET BREADTH: {macro.get('market_breadth_status', 'N/A')} ({macro.get('breadth_sentiment', 'N/A')})\n"
            f"SECTOR: {sr.get('sector', 'N/A')} | RANK: {sr.get('rank', 'N/A')} | STATUS: {sr.get('status', 'N/A')}\n"
            f"SECTOR 10-DAY RETURN: {sr.get('return', 'N/A')}%\n"
            f"EARNINGS PROXIMITY: {ep.get('status', 'N/A')} ({ep.get('days_to_earnings', 'N/A')} days)\n"
        )

    elif role == "quant":
        ml = ctx.get("ml") or {}
        return base + (
            f"SYSTEM VERDICT: {ctx.get('verdict', 'N/A')} (Score: {ctx.get('final_score', 'N/A')})\n"
            f"TECHNICAL SCORE: {ctx.get('technical_score', 'N/A')}\n"
            f"ANOMALY BOOST: {ctx.get('anomaly_boost', 'N/A')}\n"
            f"ML DIRECTION: {ml.get('direction', 'N/A')} ({ml.get('confidence_pct', 'N/A')}% confidence)\n"
            f"ML RELIABLE: {ml.get('ml_signal_reliable', False)}\n"
            f"ML MODEL ACCURACY: {ml.get('model_accuracy_pct', 'N/A')}%\n"
        )

    return base + f"CONTEXT: {str(ctx)[:500]}"


def _extract_verdict_tag(text: str, role: str) -> Optional[str]:
    """Extract the closing verdict keyword from specialist output."""
    text_upper = text.upper()
    tags_by_role = {
        "risk":    ["LOW", "MEDIUM", "HIGH", "EXTREME"],
        "shariah": ["COMPLIANT", "NON_COMPLIANT", "GRAY_AREA", "GREY AREA"],
        "macro":   ["TAILWIND", "HEADWIND", "NEUTRAL"],
        "quant":   ["CONFIRMED", "WEAK", "CONTRADICTED"],
    }
    for tag in tags_by_role.get(role, []):
        if tag in text_upper:
            return tag
    return None


# ---------------------------------------------------------------------------
# Run multiple specialists (called by advisor_engine)
# ---------------------------------------------------------------------------

def run_needed_specialists(
    user_message: str,
    symbol: str,
    context_data: dict,
    max_specialists: int = 2,
) -> list[dict]:
    """
    Detect which specialists are needed, run them, and return opinions.
    Caps at max_specialists to avoid slow responses.

    Returns list of specialist result dicts.
    """
    roles = detect_specialists_needed(user_message)[:max_specialists]
    if not roles:
        return []

    results = []
    for role in roles:
        logger.info(f"Invoking {role} specialist for {symbol}")
        result = run_specialist(
            role=role,
            symbol=symbol,
            context_data=context_data,
            user_question=user_message,
        )
        results.append(result)

    return results


def format_specialist_opinions(opinions: list[dict]) -> str:
    """Format specialist opinions for injection into the advisor's Ollama prompt."""
    if not opinions:
        return ""
    lines = ["\nSPECIALIST OPINIONS:"]
    for op in opinions:
        role = op["role"].upper()
        tag = f" [{op['verdict_tag']}]" if op.get("verdict_tag") else ""
        lines.append(f"\n{role} SPECIALIST{tag}:\n{op['opinion']}")
    return "\n".join(lines)

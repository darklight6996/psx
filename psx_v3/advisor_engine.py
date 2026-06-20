"""
advisor_engine.py — Primary orchestration engine for the PSX V4 AI Advisor.

This is the brain. It:
  1. Maintains conversation state within a session
  2. Classifies user intent and extracts mentioned symbols
  3. Decides which tools to invoke
  4. Gathers context via advisor_tools.py
  5. Builds a rich system prompt
  6. Calls Ollama (single primary AI — Qwen3 14B preferred)
  7. Parses the structured recommendation package from the response
  8. Invokes specialists on-demand via specialist_router.py
  9. Persists the turn to advisor_memory.py
 10. Returns the response + structured data to the UI

Design:
  - One Ollama call per turn for the primary advisor
  - Optional specialist calls (1–2 max, parallel if needed)
  - All V3 data access via advisor_tools.py (never direct)
  - Graceful degradation: if any tool fails, advisor continues
    with whatever data it has

The advisor always writes a structured JSON package at the end of
its response (inside a ```json block). The engine parses this before
returning, strips it from the user-visible text, and stores it.
If parsing fails, conversation continues normally without a package.
"""

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger("advisor_engine")

# ---------------------------------------------------------------------------
# Model preferences
# ---------------------------------------------------------------------------

ADVISOR_MODEL_PREFERENCE = [
    "qwen3:14b",
    "qwen2.5:14b",
    "qwen2.5:7b",
    "mistral:7b",
    "llama3.2:3b",
]

# ---------------------------------------------------------------------------
# Intent classification keywords
# ---------------------------------------------------------------------------

INTENT_PATTERNS = {
    "analyze_stock": [
        "analyze", "analyse", "look at", "what do you think of", "tell me about",
        "should i buy", "should i sell", "thoughts on", "view on", "opinion on",
        "is it worth", "good buy", "bad buy", "recommend", "check",
    ],
    "find_stocks": [
        "find me", "screen for", "best stocks", "top picks", "halal swing",
        "what should i buy", "any buys", "buy ideas", "opportunities",
        "show me", "looking for stocks",
    ],
    "portfolio_discuss": [
        "my portfolio", "my positions", "i own", "i hold", "i bought",
        "should i hold", "should i exit", "take profit", "cut loss",
    ],
    "strategy_discuss": [
        "strategy", "approach", "how do you trade", "what is your method",
        "how should i", "explain", "teach me", "what does", "how does",
    ],
    "market_overview": [
        "market", "psx", "kse", "how is the market", "market today",
        "breadth", "overall", "macro", "pakistan economy",
    ],
    "set_strategy": [
        "day trade", "day trading", "swing", "long term", "long-term",
        "invest", "i want to", "my goal is",
    ],
}

# ---------------------------------------------------------------------------
# PSX ticker extraction
# ---------------------------------------------------------------------------

# Common PSX tickers — used to help extraction from free-form text
_KNOWN_TICKERS = {
    "SYS", "TRG", "NETSOL", "AVN", "AIRLINK", "OGDC", "PPL", "MARI", "POL",
    "PSO", "APL", "SNGP", "SSGC", "LUCK", "DGKC", "MLCF", "ENGRO", "EFERT",
    "FATIMA", "FFC", "FFBL", "HUBC", "KAPCO", "ICI", "NML", "NESTLE", "SEARL",
    "ISL", "ASTL", "MUGHAL", "HCAR", "INDU", "MTL", "GHGL", "TGL", "HBL",
    "UBL", "MCB", "ABL", "MEBL", "NBP", "PMPKL", "EFU", "PIOC", "CHCC",
    "FCCL", "NCL", "GATM", "KTML", "HINOON", "GLAXO", "ABOT", "FEROZ",
}


def extract_symbols(text: str) -> list[str]:
    """
    Extract PSX ticker symbols from free-form user text.

    Approach:
      1. Uppercase words of 2–6 chars that are in the known ticker list
      2. Words that look like tickers (ALL-CAPS, 2–6 chars) even if not in list
    Returns deduped list, max 5 symbols.
    """
    words = re.findall(r'\b[A-Za-z]{2,6}\b', text)
    found = []
    for w in words:
        wu = w.upper()
        if wu in _KNOWN_TICKERS:
            found.append(wu)
        elif w == w.upper() and len(w) >= 2:   # already uppercase in original
            found.append(wu)

    # Deduplicate preserving order
    seen = set()
    result = []
    for s in found:
        if s not in seen and s not in {"I", "A", "AN", "THE", "IN", "ON", "AT",
                                        "BY", "OR", "AND", "BUT", "FOR", "PSX",
                                        "KSE", "PKR", "RSI", "EMA", "ATR", "ML"}:
            seen.add(s)
            result.append(s)
    return result[:5]


def classify_intent(text: str) -> str:
    """Return the dominant intent category for a user message."""
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for intent, keywords in INTENT_PATTERNS.items():
        scores[intent] = sum(1 for kw in keywords if kw in text_lower)
    if not any(scores.values()):
        return "general"
    return max(scores, key=lambda k: scores[k])


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def build_system_prompt(
    strategy_mode: str,
    symbols: list[str],
    context_data: dict,           # from advisor_tools.gather_symbol_context
    lessons_text: str = "",
    historical_brief: str = "",
    specialist_opinions: str = "",
    macro_summary: str = "",
) -> str:
    """
    Assemble the full system prompt for the advisor Ollama call.
    Injected sections (all optional, skipped if empty):
      - Strategy addendum (always included)
      - Symbol context (price, verdict, score, ATR targets, ML, shariah)
      - Macro context
      - Historical brief (track record, reflections)
      - Past lessons
      - Specialist opinions
    """
    from strategy_profiles import get_profile
    profile = get_profile(strategy_mode)

    sections = []

    # Core identity
    sections.append("""You are a professional AI Investment Advisor specialising in the Pakistan Stock Exchange (PSX).
You have deep knowledge of Pakistani macroeconomics, PSX market microstructure, KMI Shariah compliance,
and quantitative momentum analysis. You are direct, honest, and specific — no vague platitudes.
You always cite the data behind your reasoning. You flag uncertainty clearly.
You are not just a signal machine — you think, challenge, debate, and advise like a trusted partner.

CRITICAL RULES:
- Always check Shariah status. Non-compliant (NON_COMPLIANT) stocks CANNOT be recommended BUY.
- GRAY_AREA stocks require explicit discussion before recommendation.
- If earnings proximity is HIGH_RISK (within 5 days), recommend WAIT not BUY.
- If ML signal is unreliable (ml_signal_reliable: false), ignore it and say so.
- Never invent numbers. If data is missing, say so.
- Express confidence as a percentage in every concrete recommendation.
- PSX-specific: RSI overbought is ~72 (not 70). ADX trending requires >30. Circuit breaker is 7.5%.""")

    # Strategy addendum
    sections.append(profile["system_prompt_addendum"].strip())

    # Symbol data
    if context_data:
        sym = context_data.get("symbol", "")
        price = context_data.get("live_price") or context_data.get("price")
        verdict = context_data.get("verdict")
        score = context_data.get("final_score")
        shariah = context_data.get("shariah_status")
        targets = context_data.get("targets") or {}
        ml = context_data.get("ml") or {}
        sr = context_data.get("sector_rotation") or {}
        ep = context_data.get("earnings_proximity") or {}
        ph = context_data.get("prediction_history") or {}
        pipeline_err = context_data.get("pipeline_error")

        ctx_lines = [f"\nCURRENT STOCK DATA — {sym}:"]
        if pipeline_err:
            ctx_lines.append(f"  ⚠ Pipeline data unavailable: {pipeline_err}")
            ctx_lines.append("  Advise based on general knowledge and ask user to run analysis first.")
        else:
            if price:
                ctx_lines.append(f"  Price: PKR {price:,.2f}")
            if verdict:
                ctx_lines.append(f"  System verdict: {verdict} (Score: {score}/100)")
            if shariah:
                ctx_lines.append(f"  Shariah: {shariah}")
            if targets.get("target_price"):
                ctx_lines.append(
                    f"  ATR target: PKR {targets['target_price']:,.2f} "
                    f"(+{targets.get('target_pct', '?')}%) | "
                    f"Stop: PKR {targets['stop_loss']:,.2f} "
                    f"(-{targets.get('stop_pct', '?')}%) | "
                    f"R/R: {targets.get('risk_reward_ratio', '?')}"
                )
            if targets.get("holding_label"):
                ctx_lines.append(f"  Holding period: {targets['holding_label']} — {targets.get('holding_description', '')}")
            if ml:
                reliable = ml.get("ml_signal_reliable", False)
                if reliable:
                    ctx_lines.append(
                        f"  ML: {ml.get('direction', '?')} "
                        f"({ml.get('confidence_pct', 0):.0f}% confidence, "
                        f"{ml.get('model_accuracy_pct', 0):.0f}% model accuracy)"
                    )
                else:
                    ctx_lines.append("  ML: UNRELIABLE (insufficient training data) — ignore ML signal.")
            if sr.get("sector"):
                ctx_lines.append(
                    f"  Sector: {sr['sector']} | {sr.get('status', 'N/A')} "
                    f"(rank {sr.get('rank', '?')}, {sr.get('return', 0):+.1f}% 10d)"
                )
            if ep.get("status") == "HIGH_RISK":
                ctx_lines.append(
                    f"  ⚠ EARNINGS IN {ep.get('days_to_earnings', '?')} DAYS — HIGH RISK"
                )
            if ph.get("hit_rate_pct") is not None:
                ctx_lines.append(
                    f"  Historical hit rate: {ph['hit_rate_pct']}% over {ph.get('lookback_days', 60)} days"
                )
        sections.append("\n".join(ctx_lines))

    # Macro
    if macro_summary:
        sections.append(f"\nMACRO CONTEXT:\n{macro_summary}")

    # Historical
    if historical_brief:
        sections.append(f"\nHISTORICAL CONTEXT:\n{historical_brief}")

    # Lessons
    if lessons_text:
        sections.append(f"\n{lessons_text}")

    # Specialist opinions
    if specialist_opinions:
        sections.append(specialist_opinions)

    # Output format instruction
    sections.append("""
RESPONSE FORMAT:
Write your response naturally in markdown. Be conversational but precise.

If you are making a CONCRETE RECOMMENDATION (not just discussing), append this JSON block
at the very end of your response — the system will parse and hide it from the user:

```json
{
  "symbol": "TICKER",
  "strategy": "DAY|SWING|LONGTERM",
  "action": "BUY|HOLD|SELL|WAIT|DISCUSS",
  "confidence": 75,
  "target_price": 0.0,
  "stop_loss": 0.0,
  "holding_period": "3-7 days",
  "shariah_status": "COMPLIANT|NON_COMPLIANT|GRAY_AREA|UNKNOWN",
  "ml_prediction": "UP 63% (reliable)|unreliable",
  "reasoning": "2-3 sentence internal reasoning summary"
}
```

If you are NOT making a concrete recommendation (just discussing, explaining, or asking
a clarifying question), omit the JSON block entirely.
""")

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def parse_advisor_response(raw_response: str) -> tuple[str, Optional[dict]]:
    """
    Split the advisor's raw Ollama output into:
      (user_visible_text, structured_package_or_None)

    Extracts the ```json block from the end, returns the rest as display text.
    """
    # Find JSON block
    json_pattern = r"```json\s*(\{.*?\})\s*```"
    match = re.search(json_pattern, raw_response, re.DOTALL)

    package = None
    if match:
        try:
            package = json.loads(match.group(1))
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse advisor JSON package: {e}")

        # Remove the JSON block from user-visible text
        display_text = raw_response[:match.start()].rstrip()
    else:
        display_text = raw_response

    return display_text.strip(), package


# ---------------------------------------------------------------------------
# Lesson writer (called by evaluate_advisor_conversations)
# ---------------------------------------------------------------------------

def write_lesson(
    symbol: str,
    action: str,
    price_then: float,
    price_now: float,
    move_pct: float,
    was_correct: bool,
    advisor_response: str,
) -> Optional[str]:
    """
    Ask Ollama to write a one-sentence lesson from an evaluated recommendation.
    Used by advisor_memory.evaluate_advisor_conversations().
    """
    try:
        from council.ollama_council import ollama_chat, pick_model, get_available_models
        models = get_available_models()
        model = pick_model("qwen2.5:7b", models)
        if not model:
            return None

        system = (
            "You are a self-learning trading AI. Write exactly ONE sentence describing "
            "what you got right or wrong and what to remember for next time. "
            "Be specific about the technical or macro reason. No preamble."
        )
        user = (
            f"Stock: {symbol}. Recommendation: {action}. "
            f"Price then: PKR {price_then:.2f}. Price now: PKR {price_now:.2f}. "
            f"Move: {move_pct:+.1f}%. Outcome: {'CORRECT' if was_correct else 'WRONG'}.\n"
            f"Original reasoning snippet: {advisor_response[:300]}"
        )
        result = ollama_chat(model, system, user, timeout=30)
        return result.strip() if result else None
    except Exception as e:
        logger.warning(f"write_lesson failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Main AdvisorEngine class
# ---------------------------------------------------------------------------

class AdvisorEngine:
    """
    Stateless per-turn engine. Session state is managed by the Streamlit UI
    (st.session_state) and passed in on each call.

    Usage:
        engine = AdvisorEngine()
        response = engine.chat(
            user_message="Should I buy ENGRO tomorrow?",
            session_id="abc123",
            turn_index=0,
            conversation_history=[],
            strategy_mode="swing",
        )
    """

    def __init__(self):
        pass

    def chat(
        self,
        user_message: str,
        session_id: str,
        turn_index: int,
        conversation_history: list[dict],
        strategy_mode: str = "swing",
    ) -> dict:
        """
        Process one conversation turn.

        Returns:
            {
                "display_text": str,           — markdown for the chat UI
                "structured_package": dict|None,
                "specialists_consulted": list[str],
                "tools_invoked": list[str],
                "primary_symbol": str|None,
                "symbols_discussed": list[str],
                "db_id": int,                  — row id in advisor_conversations
                "error": str|None,
            }
        """
        import advisor_tools as tools
        from advisor_memory import (
            save_conversation_turn, get_relevant_lessons,
            format_lessons_for_prompt,
        )
        from specialist_router import run_needed_specialists, format_specialist_opinions
        from historical_reasoning import build_historical_brief
        
        tools_invoked: list[str] = []
        specialists_consulted: list[str] = []

        # ── 1. Extract symbols and classify intent ────────────────────────────
        symbols = extract_symbols(user_message)
        # Also check last few turns for symbols
        for turn in conversation_history[-3:]:
            prev_syms = extract_symbols(turn.get("user_message", ""))
            for s in prev_syms:
                if s not in symbols:
                    symbols.append(s)
        symbols = symbols[:3]   # cap at 3

        intent = classify_intent(user_message)
        primary_symbol = symbols[0] if symbols else None

        # ── 2. Gather context data ────────────────────────────────────────────
        context_data: dict = {}
        macro_summary = ""

        if primary_symbol:
            tools_invoked.append("gather_symbol_context")
            context_data = tools.gather_symbol_context(primary_symbol, include_history=True)

        # Macro context (always useful)
        macro_result = tools.get_macro_context()
        tools_invoked.append("get_macro_context")
        if macro_result["status"] == "ok":
            macro_summary = macro_result["data"].get("summary", "")

        # ── 3. Historical brief ───────────────────────────────────────────────
        historical_brief = ""
        if primary_symbol:
            tools_invoked.append("build_historical_brief")
            historical_brief = build_historical_brief(primary_symbol)

        # ── 4. Past lessons ───────────────────────────────────────────────────
        lessons_text = ""
        if primary_symbol:
            lessons = get_relevant_lessons(symbol=primary_symbol, limit=3)
            lessons_text = format_lessons_for_prompt(lessons)

        # ── 5. Specialist detection and invocation ────────────────────────────
        specialist_opinions_text = ""
        if primary_symbol and intent in ("analyze_stock", "portfolio_discuss"):
            specialist_results = run_needed_specialists(
                user_message=user_message,
                symbol=primary_symbol,
                context_data=context_data,
                max_specialists=2,
            )
            specialists_consulted = [r["role"] for r in specialist_results if r["success"]]
            specialist_opinions_text = format_specialist_opinions(
                [r for r in specialist_results if r["success"]]
            )

        # ── 6. Build system prompt ────────────────────────────────────────────
        system_prompt = build_system_prompt(
            strategy_mode=strategy_mode,
            symbols=symbols,
            context_data=context_data,
            lessons_text=lessons_text,
            historical_brief=historical_brief,
            specialist_opinions=specialist_opinions_text,
            macro_summary=macro_summary,
        )

        # ── 7. Build conversation messages for Ollama ─────────────────────────
        messages = []

        # Previous turns (last 8 for context window management)
        for turn in conversation_history[-8:]:
            messages.append({
                "role": "user",
                "content": turn.get("user_message", ""),
            })
            messages.append({
                "role": "assistant",
                "content": turn.get("advisor_response", ""),
            })

        # Current user message
        messages.append({"role": "user", "content": user_message})

        # ── 8. Call Ollama ────────────────────────────────────────────────────
        raw_response = self._call_ollama(system_prompt, messages)

        if raw_response is None:
            error_msg = (
                "I'm unable to connect to the local AI model right now. "
                "Please ensure Ollama is running (`ollama serve`) and that "
                "you have at least one model pulled (e.g. `ollama pull qwen2.5:7b`)."
            )
            return {
                "display_text": error_msg,
                "structured_package": None,
                "specialists_consulted": specialists_consulted,
                "tools_invoked": tools_invoked,
                "primary_symbol": primary_symbol,
                "symbols_discussed": symbols,
                "db_id": None,
                "error": "Ollama unavailable",
            }

        # ── 9. Parse response ─────────────────────────────────────────────────
        display_text, package = parse_advisor_response(raw_response)

        # ── 10. Get price for outcome tracking ───────────────────────────────
        price_at_rec = context_data.get("live_price") or context_data.get("price")
        action_taken = package.get("action") if package else None

        # ── 11. Persist to DB ─────────────────────────────────────────────────
        db_id = None
        try:
            db_id = save_conversation_turn(
                session_id=session_id,
                turn_index=turn_index,
                user_message=user_message,
                advisor_response=display_text,
                symbols_discussed=symbols,
                strategy_mode=strategy_mode,
                action_recommended=action_taken,
                structured_package=package,
                specialists_consulted=specialists_consulted,
                tools_invoked=tools_invoked,
                price_at_recommendation=float(price_at_rec) if price_at_rec else None,
                primary_symbol=primary_symbol,
            )
        except Exception as e:
            logger.error(f"Failed to persist conversation turn: {e}")

        return {
            "display_text": display_text,
            "structured_package": package,
            "specialists_consulted": specialists_consulted,
            "tools_invoked": tools_invoked,
            "primary_symbol": primary_symbol,
            "symbols_discussed": symbols,
            "db_id": db_id,
            "error": None,
        }

    def _call_ollama(
        self,
        system_prompt: str,
        messages: list[dict],
    ) -> Optional[str]:
        """
        Call Ollama with the advisor model preference chain.
        Uses multi-turn message format (not single user_msg) for conversation continuity.
        """
        try:
            from council.ollama_council import get_available_models, pick_model
            import requests, os
            OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

            models = get_available_models()
            if not models:
                logger.error("No Ollama models available")
                return None

            model = None
            for preferred in ADVISOR_MODEL_PREFERENCE:
                m = pick_model(preferred, models)
                if m:
                    model = m
                    break

            if not model:
                model = models[0]

            payload = {
                "model": model,
                "messages": [{"role": "system", "content": system_prompt}] + messages,
                "stream": False,
                "options": {
                    "temperature": 0.15,       # low temperature for consistent financial advice
                    "num_predict": 1800,       # enough for thorough analysis + JSON package
                },
            }

            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json=payload,
                timeout=120,
            )

            if resp.status_code == 200:
                content = resp.json()["message"]["content"]
                logger.info(f"Advisor response generated ({len(content)} chars, model={model})")
                return content
            else:
                logger.error(f"Ollama returned {resp.status_code}: {resp.text[:200]}")
                return None

        except Exception as e:
            logger.error(f"Ollama call failed: {e}")
            return None

    def detect_strategy_mode(self, user_message: str) -> Optional[str]:
        """Detect if the user is setting their strategy mode."""
        from strategy_profiles import get_mode_from_text
        return get_mode_from_text(user_message)

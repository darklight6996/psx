"""
ui/advisor_chat.py — Streamlit Chat Tab for PSX V4 AI Advisor.

Tab label: 🤖 AI Advisor

Features:
  - Free-form multi-turn conversation
  - Strategy mode selector (shown once per session)
  - Recommendation card rendered below advisor response
  - Specialist invocation notifications
  - Advisor accuracy stats sidebar
  - Session history

Wires into app.py as tab10 (add to existing tab list).
"""

import streamlit as st
import uuid
from datetime import date


def _rating_color(action: str) -> str:
    return {"BUY": "#4ade80", "SELL": "#f87171", "HOLD": "#fbbf24",
            "WAIT": "#60a5fa", "DISCUSS": "#a78bfa"}.get(action, "#94a3b8")


def _rating_bg(action: str) -> str:
    return {"BUY": "#0f4c2a", "SELL": "#4a1818", "HOLD": "#3a2c0a",
            "WAIT": "#0c2340", "DISCUSS": "#2e1065"}.get(action, "#1e293b")


def _shariah_icon(status: str) -> str:
    return {"COMPLIANT": "✅", "NON_COMPLIANT": "❌",
            "GRAY_AREA": "⚠️", "UNKNOWN": "❓"}.get(status, "❓")


def render_recommendation_card(package: dict):
    """
    Render the structured recommendation package as a styled card.
    Only shown when the advisor issues a concrete BUY/HOLD/SELL/WAIT.
    """
    action = package.get("action", "DISCUSS")
    if action == "DISCUSS":
        return   # no card for pure discussion turns

    sym = package.get("symbol", "—")
    strategy = package.get("strategy", "—")
    confidence = package.get("confidence", 0)
    target = package.get("target_price")
    stop = package.get("stop_loss")
    holding = package.get("holding_period", "—")
    shariah = package.get("shariah_status", "UNKNOWN")
    ml_pred = package.get("ml_prediction", "—")

    rc = _rating_color(action)
    bg = _rating_bg(action)

    # Build target/stop line
    ts_line = ""
    if target and stop:
        ts_line = f"Target: PKR {target:,.2f} | Stop: PKR {stop:,.2f}"
    elif target:
        ts_line = f"Target: PKR {target:,.2f}"

    st.markdown(
        f"""<div style="background:{bg};border:1px solid {rc}44;border-radius:10px;
        padding:14px 20px;margin:10px 0;">
          <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:8px;">
            <span style="font-size:22px;font-weight:800;color:#f1f5f9">{sym}</span>
            <span style="background:{bg};color:{rc};border:1px solid {rc}66;
              padding:4px 14px;border-radius:16px;font-size:14px;font-weight:800">{action}</span>
            <span style="color:#94a3b8;font-size:13px">{strategy}</span>
            <span style="color:#fbbf24;font-size:13px;margin-left:auto">
              Confidence: {confidence}%</span>
          </div>
          <div style="display:flex;gap:20px;flex-wrap:wrap;font-size:13px;color:#cbd5e1;">
            {"<span>" + ts_line + "</span>" if ts_line else ""}
            {"<span>| Holding: " + holding + "</span>" if holding else ""}
            <span>| Shariah: {_shariah_icon(shariah)} {shariah}</span>
            <span>| ML: {ml_pred}</span>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_strategy_selector() -> str:
    """Show strategy mode selector. Returns chosen mode string."""
    from strategy_profiles import STRATEGY_PROFILES, STRATEGY_QUESTION
    st.markdown(STRATEGY_QUESTION)

    col1, col2, col3 = st.columns(3)
    chosen = None
    if col1.button("⚡ Day trading", key="strat_day", use_container_width=True):
        chosen = "day"
    if col2.button("📈 Swing trading", key="strat_swing", use_container_width=True):
        chosen = "swing"
    if col3.button("🏛️ Long-term", key="strat_longterm", use_container_width=True):
        chosen = "longterm"
    return chosen


def render_advisor_chat_tab():
    """Main render function — call from app.py in the advisor tab."""

    st.markdown("### 🤖 AI Investment Advisor")
    st.markdown(
        "_Free-form conversation powered by your local Ollama model. "
        "All V3 analytics (ML, Shariah, signals, history) are available to the advisor._"
    )

    # ── Session initialisation ────────────────────────────────────────────────
    if "advisor_session_id" not in st.session_state:
        st.session_state.advisor_session_id = str(uuid.uuid4())[:8]
    if "advisor_history" not in st.session_state:
        st.session_state.advisor_history = []
    if "advisor_strategy" not in st.session_state:
        st.session_state.advisor_strategy = None
    if "advisor_turn_index" not in st.session_state:
        st.session_state.advisor_turn_index = 0

    # ── Sidebar / accuracy panel ──────────────────────────────────────────────
    with st.sidebar:
        st.markdown("---")
        st.markdown("#### 🤖 Advisor Stats")
        try:
            from advisor_memory import get_advisor_accuracy_stats
            stats = get_advisor_accuracy_stats(lookback_days=30)
            if stats["total"] > 0:
                st.metric("Advisor Hit Rate (30d)", f"{stats['hit_rate']}%",
                          f"{stats['total']} evaluated")
                for action, av in stats.get("by_action", {}).items():
                    st.caption(f"{action}: {av['hit_rate']}% ({av['total']} calls)")
            else:
                st.caption("No evaluated advisor recommendations yet.")
        except Exception:
            st.caption("Advisor stats unavailable.")

        # Reset session
        if st.button("🔄 New session", key="advisor_reset"):
            st.session_state.advisor_session_id = str(uuid.uuid4())[:8]
            st.session_state.advisor_history = []
            st.session_state.advisor_strategy = None
            st.session_state.advisor_turn_index = 0
            st.rerun()

    # ── Strategy mode gate ────────────────────────────────────────────────────
    if not st.session_state.advisor_strategy:
        chosen = render_strategy_selector()
        if chosen:
            st.session_state.advisor_strategy = chosen
            st.rerun()
        return   # don't show chat until strategy is set

    # Show current strategy
    from strategy_profiles import describe_strategy
    mode_label = describe_strategy(st.session_state.advisor_strategy)
    st.caption(
        f"Mode: **{mode_label}** · Session: `{st.session_state.advisor_session_id}` "
        f"· {date.today().isoformat()}"
    )

    # Change strategy button
    if st.button("Change strategy mode", key="change_strat"):
        st.session_state.advisor_strategy = None
        st.rerun()

    st.markdown("---")

    # ── Render conversation history ───────────────────────────────────────────
    for turn in st.session_state.advisor_history:
        with st.chat_message("user"):
            st.markdown(turn["user_message"])

        with st.chat_message("assistant", avatar="📊"):
            st.markdown(turn["advisor_response"])
            # Render recommendation card if this turn had a package
            if turn.get("structured_package"):
                render_recommendation_card(turn["structured_package"])
            # Show specialists consulted
            specialists = turn.get("specialists_consulted", [])
            if specialists:
                st.caption(f"_Specialists consulted: {', '.join(specialists)}_")

    # ── Chat input ────────────────────────────────────────────────────────────
    user_input = st.chat_input(
        "Ask me anything — analyze a stock, find halal swing ideas, discuss your portfolio..."
    )

    if not user_input:
        # Show example prompts on first turn
        if not st.session_state.advisor_history:
            st.markdown("**Try asking:**")
            examples = [
                "Should I buy ENGRO tomorrow?",
                "What's your view on OGDC for a swing trade?",
                "Find me halal stocks with strong momentum.",
                "Argue against buying ISL right now.",
                "What would you do with PKR 500,000?",
                "How has LUCK been performing recently?",
            ]
            cols = st.columns(2)
            for i, ex in enumerate(examples):
                if cols[i % 2].button(ex, key=f"ex_{i}"):
                    user_input = ex
                    break

    if user_input:
        # Show user message immediately
        with st.chat_message("user"):
            st.markdown(user_input)

        # Check if user is setting strategy mode mid-conversation
        from advisor_engine import AdvisorEngine
        engine = AdvisorEngine()
        new_mode = engine.detect_strategy_mode(user_input)
        if new_mode and new_mode != st.session_state.advisor_strategy:
            st.session_state.advisor_strategy = new_mode
            from strategy_profiles import describe_strategy as ds
            with st.chat_message("assistant", avatar="📊"):
                st.markdown(
                    f"Switching to **{ds(new_mode)}** mode. "
                    f"My recommendations will now be calibrated accordingly. "
                    f"What would you like to discuss?"
                )
            # Add to history
            st.session_state.advisor_history.append({
                "user_message": user_input,
                "advisor_response": f"Switching to {ds(new_mode)} mode.",
                "structured_package": None,
                "specialists_consulted": [],
            })
            st.session_state.advisor_turn_index += 1
            st.rerun()

        # Show thinking indicator with specialist notifications
        with st.chat_message("assistant", avatar="📊"):
            with st.spinner("Analysing..."):
                # Check specialist triggers for UI notification
                from specialist_router import detect_specialists_needed
                specialists_expected = detect_specialists_needed(user_input)
                if specialists_expected:
                    st.caption(
                        f"_Consulting: {', '.join(s.title() + ' Specialist' for s in specialists_expected[:2])}..._"
                    )

                result = engine.chat(
                    user_message=user_input,
                    session_id=st.session_state.advisor_session_id,
                    turn_index=st.session_state.advisor_turn_index,
                    conversation_history=st.session_state.advisor_history,
                    strategy_mode=st.session_state.advisor_strategy,
                )

            # Render response
            if result.get("error") and not result.get("display_text"):
                st.error(result["error"])
            else:
                st.markdown(result["display_text"])

                # Recommendation card
                if result.get("structured_package"):
                    render_recommendation_card(result["structured_package"])

                # Specialists notification
                if result.get("specialists_consulted"):
                    st.caption(
                        f"_Specialists consulted: "
                        f"{', '.join(result['specialists_consulted'])}_"
                    )

        # Save to session history
        st.session_state.advisor_history.append({
            "user_message": user_input,
            "advisor_response": result["display_text"],
            "structured_package": result.get("structured_package"),
            "specialists_consulted": result.get("specialists_consulted", []),
        })
        st.session_state.advisor_turn_index += 1

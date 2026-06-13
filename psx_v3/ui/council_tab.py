"""
ui/council_tab.py — Static AI Board Room results viewer.

Displays the results of the multi-agent debate for shortlisted stocks.
No manual trigger buttons allowed.
"""

import streamlit as st
import json

def render_council_tab(daily_results: dict, macro: dict):
    st.markdown("### 🏛️ AI Board Room (Multi-Agent Debate Results)")

    st.markdown("""
    The AI Board Room displays the validation and debate summary for shortlisted candidates (top candidates that passed the Tier 1.5 Micro-Agent Spotter filter).
    """)

    valid = [sym for sym, r in daily_results.items() if "error" not in r]
    if not valid:
        st.warning("Run the Daily Analysis first to populate results.")
        return

    selected = st.selectbox("Select stock to view debate:", valid, key="council_stock_select_static")

    if selected:
        r = daily_results[selected]
        
        if r.get("council_run") == 1:
            c_res = r.get("council_result", {})
            validation = c_res.get("validation_status", "VALIDATED")
            val_color = {"VALIDATED": "#4ade80", "CHALLENGED": "#f87171", "WARNED": "#fbbf24"}.get(validation, "#cbd5e1")
            
            st.markdown(
                f"""<div style="background:#1e293b;border:1px solid {val_color}44;padding:16px 20px;border-radius:10px;margin-bottom:20px;">
                    <strong>Board Room Validation Status:</strong> <span style="color:{val_color};font-weight:800;font-size:16px;">{validation}</span><br>
                    <span style="font-size:13px;color:#94a3b8;">Debate processed during pipeline run. Rating is locked to technical scoring.</span>
                </div>""", unsafe_allow_html=True
            )
            
            # Chairman notes
            st.markdown("#### 💬 Chairman Summary & Synthesis")
            st.write(c_res.get("chairman_notes", "No Chairman notes generated."))
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("##### ✅ Catalysts of Success (Key Drivers)")
                for kd in c_res.get("key_drivers", []):
                    st.markdown(f"• {kd}")
            with col2:
                st.markdown("##### ⚠️ Risks of Failure (Risk Factors)")
                for rf in c_res.get("risk_factors", []):
                    st.markdown(f"• {rf}")
                    
            st.markdown("---")
            st.markdown("#### 🗣️ Specialist Analyst Debate")
            
            local_verdicts = c_res.get("local_verdicts", {})
            if local_verdicts:
                for analyst, data in local_verdicts.items():
                    with st.expander(f"👤 {analyst} — Verdict: {data.get('verdict', 'HOLD')}", expanded=True):
                        st.markdown(f"**Technique:** {data.get('trading_technique', 'N/A')}")
                        st.write(data.get("rationale", "No rationale written."))
            else:
                st.info("No individual analyst verdicts stored.")
        else:
            st.info(f"ℹ️ {selected} was not shortlisted for a Tier 2 debate. Debates are reserved for candidates with triggered anomalies or high score profiles.")

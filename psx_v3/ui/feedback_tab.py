"""
ui/feedback_tab.py — Streamlit Feedback and Calibrations Tab.

Allows users to submit corrections, view pending calibration proposals,
and manually approve/reject proposals.
"""

import streamlit as st
import pandas as pd
from memory.db import get_conn
from memory.feedback_analyser import log_user_feedback, analyze_feedback_and_propose, approve_proposal, reject_proposal
from ui.outcome_review_tab import render_outcome_review

def render_feedback_tab(results: dict):
    st.markdown("### 🎛️ Feedback & Calibration Control Room")
    st.markdown("_Submit corrections on system verdicts and manage calibration proposals._")

    # ── Section 0: Quick Outcome Review (NEW — simplified 1-tap review) ──
    render_outcome_review()

    st.markdown("---")
    st.markdown("#### 📝 Manual Verdict Correction _(Advanced)_")
    st.caption("Use this only for nuanced corrections with extra context (news type, pattern, notes).")
    
    valid_symbols = [sym for sym, r in results.items() if "error" not in r]
    if not valid_symbols:
        st.warning("Please run the daily analysis first to populate symbols.")
        return
        
    with st.form("feedback_form"):
        c1, c2, c3 = st.columns(3)
        symbol = c1.selectbox("Stock Ticker", valid_symbols)
        
        # Read current verdict if symbol chosen
        sys_verdict = results[symbol]["advisory"]["rating"]
        c2.markdown(f"**Current System Verdict:**\n`{sys_verdict}`")
        
        user_verdict = c3.selectbox("Correct Verdict (What it should be)", ["BUY", "HOLD", "SELL"])
        
        c4, c5 = st.columns(2)
        pattern = c4.text_input("Pattern Type / Reason (e.g., volume_spike, rsi_divergence)", placeholder="volume_spike")
        user_note = c5.text_input("Additional Notes", placeholder="System was wrong because of market manipulation.")
        
        c6, c7 = st.columns(2)
        is_news = c6.checkbox("Was this move news-driven?")
        news_type = c7.selectbox("News Category", ["EARNINGS", "DIVIDEND", "POLICY", "MACRO", "OTHER"])
        
        submitted = st.form_submit_button("💾 Submit Verdict Correction")
        
        if submitted:
            r = results[symbol]
            price = r.get("current_price", 0.0)
            sector = r.get("sector", "")
            
            fb_id = log_user_feedback(
                symbol=symbol,
                system_verdict=sys_verdict,
                user_verdict=user_verdict,
                user_note=user_note,
                sector=sector,
                was_news_driven=is_news,
                news_type=news_type,
                pattern_type=pattern,
                price_at_signal=price,
                price_now=price,
                signals_at_time=r.get("signals")
            )
            
            # Analyze feedback to see if new proposals are generated
            new_props = analyze_feedback_and_propose()
            
            st.success("✅ Verdict correction logged successfully!")
            if new_props:
                st.info(f"🚨 New calibration proposals generated: {len(new_props)} proposal(s). Check the queue below.")
            st.rerun()
            
    st.markdown("---")
    
    # ── Section 2: Calibration Proposals Dashboard (Manual Approval Queue) ──
    st.markdown("#### 🏛️ Pending Calibration Proposals")
    st.markdown("_proposals are generated automatically when multiple corrections point to the same indicator/sector. They must be approved manually below._")
    
    with get_conn() as conn:
        proposals = conn.execute("""
            SELECT * FROM calibration_proposals WHERE status = 'PENDING'
        """).fetchall()
        
    if proposals:
        for p in proposals:
            p_id = p["id"]
            st.markdown(
                f"""<div style="background:#1e293b;border:1px solid #3b82f644;border-radius:8px;padding:16px;margin-bottom:12px;">
                    <div style="display:flex;justify-content:between;">
                        <strong>Signal/Target:</strong> <code>{p['signal_name']}</code> &nbsp;&nbsp;|&nbsp;&nbsp; 
                        <strong>Sector/Context:</strong> <code>{p['sector_context']}</code>
                    </div>
                    <div style="margin-top:8px;font-size:14px;color:#cbd5e1;">
                        Current Weight: <code>{p['current_weight']}</code> &nbsp;&nbsp;→&nbsp;&nbsp; 
                        Proposed Weight: <strong style="color:#fbbf24;">{p['proposed_weight']}</strong>
                    </div>
                    <div style="margin-top:8px;font-size:13px;color:#94a3b8;">
                        <strong>Reasoning:</strong> {p['reasoning']} (Evidence count: {p['evidence_count']})
                    </div>
                </div>""", unsafe_allow_html=True
            )
            btn_col1, btn_col2, _ = st.columns([1.5, 1.5, 7])
            if btn_col1.button("✅ Approve Calibration", key=f"app_{p_id}"):
                approve_proposal(p_id)
                st.success(f"Approved proposal #{p_id}")
                st.rerun()
            if btn_col2.button("❌ Reject Calibration", key=f"rej_{p_id}"):
                reject_proposal(p_id)
                st.error(f"Rejected proposal #{p_id}")
                st.rerun()
    else:
        st.info("No pending calibration proposals in queue.")
        
    st.markdown("---")
    
    # ── Section 3: Active Approved Calibrations ──
    st.markdown("#### ⚡ Active Approved Calibrations")
    with get_conn() as conn:
        approved = conn.execute("""
            SELECT * FROM calibration_proposals WHERE status = 'APPROVED'
        """).fetchall()
        
    if approved:
        df_app = pd.DataFrame([dict(a) for a in approved])
        st.dataframe(df_app[["proposal_date", "signal_name", "sector_context", "current_weight", "proposed_weight", "approved_at"]], use_container_width=True, hide_index=True)
    else:
        st.caption("No custom calibrations active. The system is running on default weights.")

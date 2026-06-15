"""
ui/analysis_details_tab.py — Streamlit Explanation & Deep Dive Tab (Tab 3).

Provides the complete "why recommended" screen, breaking down technical indicators,
anomaly boosts, mathematical confidence, Shariah rules, and Board Room validation.
"""

import streamlit as st
import json
import pandas as pd

def render_analysis_details_tab(results: dict):
    st.markdown("### 🔍 Recommendation Deep Dive (Why Recommended?)")
    
    valid_symbols = [sym for sym, r in results.items() if "error" not in r]
    if not valid_symbols:
        st.warning("No valid analysis results available. Run the daily analysis first.")
        return
        
    selected = st.selectbox("Select Stock for Deep Dive", valid_symbols, key="details_stock_select")
    
    if selected:
        r = results[selected]
        
        # ── 1. Header ──
        verdict = r["advisory"]["rating"]
        score = r["advisory"]["score"]
        price = r["current_price"]
        sector = r.get("sector", "Unknown")
        
        vc = {"BUY": "#4ade80", "SELL": "#f87171", "HOLD": "#fbbf24"}.get(verdict, "#cbd5e1")
        bg = {"BUY": "#0f4c2a", "SELL": "#4a1818", "HOLD": "#3a2c0a"}.get(verdict, "#334155")
        
        st.markdown(
            f"""<div style="background:{bg};border:1px solid {vc}55;border-radius:10px;padding:20px;margin-bottom:20px;">
                <div style="display:flex;justify-content:between;align-items:center;flex-wrap:wrap;gap:12px;">
                    <div>
                        <span style="font-size:32px;font-weight:800;color:#f1f5f9;">{selected}</span>
                        <span style="font-size:14px;color:#94a3b8;margin-left:10px;">{sector}</span>
                    </div>
                    <div style="margin-left:auto;display:flex;gap:10px;align-items:center;">
                        <span style="background:{vc}22;color:{vc};border:1px solid {vc}44;padding:6px 16px;border-radius:20px;font-size:16px;font-weight:800;">{verdict}</span>
                        <span style="background:#1e293b;color:#f1f5f9;border:1px solid #334155;padding:6px 16px;border-radius:20px;font-size:16px;font-weight:800;">Score: {score:.1f}/100</span>
                    </div>
                </div>
                <div style="margin-top:10px;color:#cbd5e1;font-size:15px;">
                    Current Price: <strong>PKR {price:,.2f}</strong>
                </div>
            </div>""", unsafe_allow_html=True
        )
        
        # ── 2. Two-Column Layout (Left: Math & Rules, Right: AI Board Room) ──
        col_left, col_right = st.columns([1, 1])
        
        with col_left:
            # Confidence Breakdown
            st.markdown("#### 🎯 Mathematical Confidence")
            conf_score = r.get("confidence", 50.0)
            conf_label = r.get("confidence_label", "MODERATE")
            conf_comp = r.get("confidence_components", {})
            
            lbl_color = {"VERY_HIGH": "#4ade80", "HIGH": "#60a5fa", "MODERATE": "#fbbf24", "LOW": "#f87171"}.get(conf_label, "#fafafa")
            st.markdown(f"Overall Conviction: <strong style='color:{lbl_color};font-size:18px;'>{conf_label} ({conf_score:.1f}%)</strong>", unsafe_allow_html=True)
            
            for name, val in conf_comp.items():
                st.markdown(f"**{name.replace('_', ' ').title()}**")
                st.progress(min(max(float(val) / 100.0, 0.0), 1.0))
                st.caption(f"Score contribution: {val:.1f}%")
                
            st.markdown("---")
            
            # Anomaly Triggers
            st.markdown("#### 🚨 Anomaly Triggers & Score Boosts")
            anomalies = r.get("anomaly_details", [])
            if anomalies:
                for a in anomalies:
                    bst = a.get("boost", 0)
                    sign = "+" if bst >= 0 else ""
                    st.markdown(
                        f"""<div style="background:#1e293b;border-left:4px solid #3b82f6;padding:10px 14px;border-radius:4px;margin-bottom:8px;">
                            <strong>{a.get('flag','').replace('_',' ').title()}</strong> ({sign}{bst} pts)<br>
                            <span style="font-size:12px;color:#94a3b8;">{a.get('detail','')}</span>
                        </div>""", unsafe_allow_html=True
                    )
            else:
                st.info("No anomalous triggers or unusual market patterns detected.")
                
            st.markdown("---")
            
            # Technical Signals Detailed
            st.markdown("#### 🔧 Indicator Breakdown")
            signals = r["technicals"].get("signals", {})
            for ind, details in signals.items():
                val = details.get("value") or details.get("pct_b") or details.get("label") or "N/A"
                label = details.get("label") or ""
                st.markdown(f"• **{ind.upper()}**: {val} _({label})_")
                
        with col_right:
            # Shariah Panel
            st.markdown("#### ☽ Shariah Compliance Screen")
            shariah = r["shariah"]
            sh_status = shariah.get("overall_status", "UNKNOWN")
            sh_color = {"COMPLIANT": "#4ade80", "GRAY_AREA": "#fbbf24", "NON_COMPLIANT": "#f87171"}.get(sh_status, "#cbd5e1")
            
            st.markdown(
                f"""<div style="background:#1e293b;border:1px solid {sh_color}44;padding:12px 18px;border-radius:8px;margin-bottom:12px;">
                    Status: <strong style="color:{sh_color};font-size:18px;">{sh_status}</strong><br>
                    <span style="font-size:13px;color:#94a3b8;">{shariah.get('recommendation', '')}</span>
                </div>""", unsafe_allow_html=True
            )
            
            # Shariah qualitative note from LLM if exists
            sh_llm = r.get("council_result", {}).get("shariah_llm_output", {}) if r.get("council_result") else {}
            if sh_llm:
                st.markdown(f"**Scholar's Notes:** {sh_llm.get('notes', 'N/A')}")
                st.markdown(f"**Scholar's Investigation:** {sh_llm.get('independent_investigation', 'N/A')}")
                
            st.markdown("---")
            
            # Board Room Debate (Tier 2)
            st.markdown("#### 🏛️ AI Board Room Debate")
            if r.get("council_run") == 1:
                c_res = r.get("council_result", {})
                validation = c_res.get("validation_status", "VALIDATED")
                val_color = {"VALIDATED": "#4ade80", "CHALLENGED": "#f87171", "WARNED": "#fbbf24"}.get(validation, "#cbd5e1")
                
                st.markdown(f"Board Room Validation: <strong style='color:{val_color};'>{validation}</strong>", unsafe_allow_html=True)
                st.markdown(f"**Chairman Synthesis:**")
                st.write(c_res.get("chairman_notes", "N/A"))
                
                st.markdown("**Catalysts of Success (Key Drivers):**")
                for d in c_res.get("key_drivers", []):
                    st.markdown(f"✅ {d}")
                    
                st.markdown("**Risks of Failure (Risk Factors):**")
                for f in c_res.get("risk_factors", []):
                    st.markdown(f"⚠️ {f}")
                    
                with st.expander("💬 View Specialist Analyst Rationales", expanded=False):
                    for role, data in c_res.get("local_verdicts", {}).items():
                        st.markdown(f"**{role}** (Verdict: `{data.get('verdict')}`)")
                        st.markdown(f"_{data.get('trading_technique', '')}_")
                        st.write(data.get("rationale"))
                        st.markdown("---")
            else:
                st.info("Stock was not debated. Only Tier 2 shortlisted candidates undergo a full Board Room debate.")
                
        # ── 3. Lifecycle ──
        st.markdown("---")
        st.markdown("#### 📅 Recommendation Lifecycle & Targets")
        hz = r.get("horizon", {})
        if hz and "error" not in hz:
            l_col1, l_col2, l_col3 = st.columns(3)
            l_col1.metric("Target Price (Upside)", f"PKR {hz.get('target_price', 0.0):,.2f}", f"+{hz.get('target_pct', 0.0):.1f}%")
            l_col2.metric("Stop Loss (Downside)", f"PKR {hz.get('stop_loss', 0.0):,.2f}", f"-{hz.get('stop_pct', 0.0):.1f}%")
            l_col3.metric("Holding Period", hz.get("holding_period", {}).get("holding_label", "N/A"))
            
            st.caption(f"Holding description: {hz.get('holding_period', {}).get('holding_description', '')}")
            st.caption("Status: `OPEN` (Expires in 14 days or when Target/Stop is hit)")

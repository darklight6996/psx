"""
ui/predictions_tab.py — Streamlit Predictions & Rankings Tab (Tab 2).

Shows:
- Sorted rankings based on Rating, Score, and Confidence.
- Detailed ATR target/stop and Shariah purification calculators.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.hqm_engine    import calc_position_size
from core.shariah_engine import calc_purification
from core.portfolio     import add_position, remove_position, get_total_capital, update_capital


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

def _rating_color(rating: str) -> str:
    return {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}.get(rating, "⚪")

def _shariah_color(status: str) -> str:
    return {"COMPLIANT": "✅", "GRAY_AREA": "⚠️", "NON_COMPLIANT": "❌"}.get(status, "❓")

def _criterion_icon(status: str) -> str:
    return {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "UNKNOWN": "❓"}.get(status, "❓")


# ---------------------------------------------------------------------------
# Rankings table
# ---------------------------------------------------------------------------

def render_rankings_table(results: dict) -> pd.DataFrame:
    """Build a sortable ranking DataFrame sorted by verdict priority, score, and confidence."""
    rows = []
    for sym, r in results.items():
        if "error" in r:
            rows.append({
                "Symbol":      sym,
                "Company":     "",
                "Rating":      "ERROR",
                "ML Dir":      "—",
                "Score":       0.0,
                "Confidence":  0.0,
                "Regime":      "—",
                "RSI":         None,
                "Trend":       "—",
                "Shariah":     "—",
                "Price (PKR)": None,
                "SortKey":     999
            })
            continue

        tech_signals = r["technicals"].get("signals", {})
        rsi_val  = tech_signals.get("rsi", {}).get("value", None)
        if rsi_val == "—":
            rsi_val = None
        trend    = tech_signals.get("ema_trend", {}).get("label", "—")
        regime   = r.get("regime", {}).get("regime", "—")

        ml = r.get("ml_signals", {})
        ml_dir  = ml.get("direction", "—") if ml.get("status") not in ("error", None) else "—"
        ml_dir_label = {"UP": "🟢 UP", "NOT_UP": "🔴 NOT_UP", "DOWN": "🔴 DOWN", "SIDEWAYS": "🟡 SIDE"}.get(ml_dir, ml_dir)

        rating = r["advisory"]["rating"]
        shariah_status = r["shariah"]["overall_status"]
        
        # SortKey mapping: BUY+COMPLIANT=1, BUY+GRAY_AREA/REVIEW=2, HOLD=3, SELL=4
        if rating == "BUY":
            if shariah_status == "COMPLIANT":
                sort_key = 1
            else:
                sort_key = 2
        elif rating == "HOLD":
            sort_key = 3
        else:
            sort_key = 4

        rows.append({
            "Symbol":      sym,
            "Company":     r.get("company_name", sym)[:25],
            "Rating":      f"{_rating_color(rating)} {rating}",
            "ML Dir":      ml_dir_label,
            "Score":       r["advisory"]["score"],
            "Confidence":  r.get("confidence", 0.0),
            "Regime":      regime,
            "RSI":         rsi_val,
            "Trend":       trend,
            "Shariah":     f"{_shariah_color(shariah_status)} {shariah_status}",
            "Price (PKR)": r.get("current_price"),
            "SortKey":     sort_key
        })

    df = pd.DataFrame(rows)
    if "RSI" in df.columns:
        df["RSI"] = pd.to_numeric(df["RSI"], errors="coerce")
    if "Price (PKR)" in df.columns:
        df["Price (PKR)"] = pd.to_numeric(df["Price (PKR)"], errors="coerce")
    
    if not df.empty:
        df = df.sort_values(by=["SortKey", "Score", "Confidence"], ascending=[True, False, False])
        df = df.drop(columns=["SortKey"])
    return df


# ---------------------------------------------------------------------------
# Detailed stock panel
# ---------------------------------------------------------------------------

def render_stock_detail(symbol: str, result: dict):
    """Render detailed analysis for a selected stock."""
    if "error" in result:
        st.error(f"Analysis error for {symbol}: {result['error']}")
        return

    advisory  = result["advisory"]
    shariah   = result["shariah"]
    tech      = result["technicals"]
    signals   = tech.get("signals", {})

    # Header
    rating    = advisory["rating"]
    rc        = {"BUY": "#4ade80", "SELL": "#f87171", "HOLD": "#fbbf24"}.get(rating, "#94a3b8")
    bg        = {"BUY": "#0f4c2a", "SELL": "#4a1818", "HOLD": "#3a2c0a"}.get(rating, "#1e293b")

    regime = result.get("regime", {}).get("regime", "CHOPPY")
    regime_colors = {
        "TRENDING UP": ("#4ade80", "#0f4c2a"),
        "TRENDING DOWN": ("#f87171", "#4a1818"),
        "CHOPPY": ("#fbbf24", "#3a2c0a"),
        "TRANSITIONING": ("#60a5fa", "#1e3a8a")
    }
    regime_color, regime_bg = regime_colors.get(regime, ("#cbd5e1", "#334155"))

    st.markdown(
        f"""<div style="display:flex;align-items:center;gap:16px;margin-bottom:20px;flex-wrap:wrap">
        <span style="font-size:28px;font-weight:800;color:#f1f5f9">{symbol}</span>
        <span style="font-size:14px;font-weight:600;color:#94a3b8">Advisory Verdict:</span>
        <span style="background:{bg};color:{rc};border:1px solid {rc}55;padding:6px 18px;
        border-radius:20px;font-size:14px;font-weight:700">{rating}</span>
        <span style="background:{regime_bg};color:{regime_color};border:1px solid {regime_color}55;padding:6px 18px;
        border-radius:20px;font-size:14px;font-weight:700">Regime: {regime}</span>
        <span style="color:#64748b;font-size:16px">PKR {result['current_price']:,.2f}</span>
        <span style="color:#475569;font-size:13px">{result.get('sector','')}</span>
        </div>""", unsafe_allow_html=True,
    )
    st.caption("Produced by rule engine + indicator voting. See AI Board Room for full council analysis.")

    # Rationale
    for reason in advisory.get("rationale", []):
        st.markdown(f"• {reason}")

    # ── ML Signals (inline mini-panel) ───────────────────────────────────────
    ml = result.get("ml_signals", {})
    if ml and ml.get("status") not in ("error", None):
        ml_dir   = ml.get("direction", "SIDEWAYS")
        ml_conf  = ml.get("confidence_pct", 0)
        ml_str   = ml.get("signal_strength", "WEAK")
        ml_acc   = ml.get("model_accuracy_pct", 0)
        is_reliable = ml.get("ml_signal_reliable", False)
        dir_color = {"UP": "#10b981", "NOT_UP": "#ef4444", "DOWN": "#ef4444", "SIDEWAYS": "#f59e0b"}.get(ml_dir, "#94a3b8")
        str_color = {"STRONG": "#10b981", "MODERATE": "#f59e0b", "WEAK": "#ef4444"}.get(ml_str, "#94a3b8")
        
        reliability_badge = ""
        if not is_reliable:
            reliability_badge = '<span style="background:#4a1818;color:#f87171;border:1px solid #f8717155;padding:2px 8px;border-radius:10px;font-size:10px;margin-left:10px;font-weight:700">⚠️ UNRELIABLE SIGNAL (ACCURACY < 52%)</span>'
            
        st.markdown(
            f"""<div style="background:#0f172a;border:1px solid #1e40af44;border-radius:10px;
            padding:12px 18px;margin:10px 0;display:flex;gap:24px;flex-wrap:wrap;align-items:center">
              <div>
                <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px">🤖 RF Direction {reliability_badge}</div>
                <div style="font-size:20px;font-weight:800;color:{dir_color}">{ml_dir}</div>
                <div style="font-size:11px;color:{str_color}">{ml_str} · {ml_conf}% conf</div>
              </div>
              <div style="border-left:1px solid #334155;padding-left:18px">
                <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px">Model Performance</div>
                <div style="font-size:20px;font-weight:800;color:{dir_color}">Random Forest</div>
                <div style="font-size:11px;color:#64748b">CV Acc: {ml_acc}%</div>
              </div>
            </div>""", unsafe_allow_html=True
        )

    st.markdown("---")

    # ── Horizon & Target ──
    st.markdown("#### ⏳ Target Price, Stop Loss, and Holding Period (ATR-based)")
    hz = result.get("horizon", {})
    if hz and "error" not in hz:
        hz_cols = st.columns(4)
        hz_cols[0].metric("Target Price", f"PKR {hz.get('target_price', 0.0):,.2f}")
        hz_cols[1].metric("Stop Loss", f"PKR {hz.get('stop_loss', 0.0):,.2f}")
        hz_cols[2].metric("Risk/Reward Ratio", f"{hz.get('risk_reward_ratio', 0.0):.2f}")
        hz_cols[3].metric("Holding Period", hz.get("holding_period", {}).get("holding_label", "N/A"))
        st.write(f"ℹ️ {hz.get('holding_period', {}).get('holding_description', '')}")

    st.markdown("---")

    # ── Technical Signals ────────────────────────────────────────────────────
    st.markdown("#### 🔧 Technical Signals")
    tc1, tc2, tc3, tc4 = st.columns(4)
    rsi_data   = signals.get("rsi", {})
    bb_data    = signals.get("bollinger", {})
    macd_data  = signals.get("macd", {})
    trend_data = signals.get("ema_trend", {})

    tc1.metric("RSI (14)",    f"{rsi_data.get('value','—')}", rsi_data.get("label",""))
    tc2.metric("Bollinger",   bb_data.get("label","—")[:20])
    tc3.metric("MACD",        macd_data.get("label","—")[:20])
    tc4.metric("EMA Trend",   trend_data.get("label","—")[:20])

    # ── Shariah Compliance ───────────────────────────────────────────────────
    st.markdown("#### ☽ Shariah Compliance")

    sc_status = shariah["overall_status"]
    sc_color  = {"COMPLIANT": "#4ade80", "GRAY_AREA": "#fbbf24", "NON_COMPLIANT": "#f87171"}.get(sc_status, "#94a3b8")
    sc_bg     = {"COMPLIANT": "#0f4c2a", "GRAY_AREA": "#3a2c0a",  "NON_COMPLIANT": "#4a1818"}.get(sc_status, "#334155")
    kmi_check = shariah.get("kmi_check", {})
    source    = kmi_check.get("source", "hardcoded_fallback")
    conf      = kmi_check.get("confidence", "LOW")
    updated   = (kmi_check.get("last_updated") or "")[:10]
    listed    = shariah.get("kmi_listed", False)
    icon      = "✅" if listed else "⚠️"
    kmi_badge = f"{icon} {'KMI Listed' if listed else 'Not in KMI'} · {source.replace('_',' ')} · {conf} confidence"
    if updated:
        kmi_badge += f" · updated {updated}"

    st.markdown(
        f"""<div style="background:{sc_bg};border:1px solid {sc_color}55;border-radius:8px;
        padding:12px 18px;margin-bottom:12px;">
        <strong style="color:{sc_color};font-size:16px">{_shariah_color(sc_status)} {sc_status}</strong>
        &nbsp;&nbsp;<span style="color:#94a3b8;font-size:13px">{kmi_badge}</span><br>
        <span style="color:#cbd5e1;font-size:13px">{shariah.get('recommendation','')}</span>
        </div>""", unsafe_allow_html=True,
    )

    if source == "hardcoded_fallback":
        st.warning("⚠️ Live KMI data unavailable — using static list. Verify at almeezangroup.com/kmi-shariah-screener")

    if shariah.get("risk_flag"):
        st.warning(shariah["risk_flag"])

    # Criteria table
    for crit in shariah.get("criteria", []):
        icon  = _criterion_icon(crit["status"])
        col_a, col_b = st.columns([3, 7])
        col_a.markdown(f"{icon} **{crit['name']}**")
        note = crit.get("note","")
        val  = crit.get("value","")
        thr  = crit.get("threshold","")
        col_b.markdown(f"{note}" + (f" _(value: {val}, limit: {thr})_" if val else ""))

    # Purification
    if shariah.get("purification_pct", 0) > 0:
        st.markdown("---")
        st.markdown("#### ⚗️ Purification Calculator")
        st.info(shariah.get("purification_note",""))
        div_input = st.number_input("Dividend received (PKR):", min_value=0.0,
                                    step=100.0, value=1000.0, key=f"div_{symbol}")
        if div_input > 0:
            purif = calc_purification(div_input, shariah["purification_pct"] / 100)
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric("Dividend Received",   f"PKR {purif['dividend_received']:,.2f}")
            pc2.metric("Give to Charity",      f"PKR {purif['purification_amount']:,.2f}",
                       f"{purif['non_halal_pct']:.1f}% of dividend")
            pc3.metric("You Keep",             f"PKR {purif['you_keep']:,.2f}")

    st.markdown("---")

    # ── Risk Prevention & Directional Checklist ──────────────────────────────
    with st.expander("🛡️ PSX Capital Protection & Trend Checklist", expanded=False):
        st.markdown("### 🛡️ Phase 1: Protecting Your Capital (Risk Prevention Checklist)")
        st.markdown("Before buying any stock on the PSX, analyze these four foundational areas to ensure the investment will not cost you significantly.")
        
        # Display the exact ASCII matrix from user
        st.code("""box
┌────────────────────────────────────────────────────────────────────────┐
│                        PSX RISK PREVENTION MATRIX                      │
├───────────────────┬────────────────────────────────────────────────────┤
│ 1. Free Float     │ Avoid stocks with < 20% free float to prevent      │
│    & Liquidity    │ getting trapped in "upper/lower locks" (no buyers).│
├───────────────────┼────────────────────────────────────────────────────┤
│ 2. P/E vs. Sector │ Avoid paying overvalued prices. Benchmark the      │
│    average        │ trailing and forward P/E against the KSE-100.      │
├───────────────────┼────────────────────────────────────────────────────┤
│ 3. Macro & Policy │ Check if the sector depends heavily on SBP policy  │
│    Sensitivities  │ rates, IMF program reforms, or PKR devaluation.     │
├───────────────────┼────────────────────────────────────────────────────┤
│ 4. Leverage       │ Target companies with a Debt-to-Equity ratio < 1.0 │
│    & Debt Cover   │ to survive high local borrowing/interest costs.    │
└───────────────────┴────────────────────────────────────────────────────┘""", language="")
        
        st.markdown("""
        **1. Free Float and Daily Volume (Liquidity Risk)**
        *   **The Check:** Verify the stock’s Free Float (the percentage of shares available to the public) and average daily trading volume via the PSX Data Portal.
        *   **Why It Matters:** Many smaller, illiquid companies on the PSX frequently hit their daily price limits ("lower locks"). If a stock hits a lower lock, trading halts for that price floor, and you cannot sell your shares because there are zero buyers. Stick to high-volume KSE-100 index stocks to ensure easy entry and exit.

        **2. Valuation Ratios (Overpayment Risk)**
        *   **The Check:** Look at the Price-to-Earnings (P/E) Ratio, Price-to-Book (P/B) Ratio, and Dividend Yield. Compare these metrics against the stock's historical average and its specific sector average.
        *   **Why It Matters:** Buying a stock at a P/E significantly higher than its sector means you are paying a premium based on speculation. Look for high dividend-yielding blue chips (e.g., in the Fertilizer or Energy sectors) which provide a structural cash cushion during market downturns.

        **3. Macroeconomic and Policy Headwinds**
        *   **The Check:** Analyze how the company handles State Bank of Pakistan (SBP) policy rates, circular debt, and PKR devaluation.
        *   **Why It Matters:**
            *   *High Interest Rates:* Heavily leveraged sectors suffer massive profit drops when interest rates rise.
            *   *Devaluation:* Import-dependent sectors suffer compressed margins when the rupee weakens. Look for export-oriented sectors (like IT) or natural hedges (like Oil & Gas exploration) to protect against currency depreciation.

        **4. Leverage and Debt-to-Equity Ratio**
        *   **The Check:** Read the company’s latest quarterly financial report on the PSX portal and calculate the Debt-to-Equity (D/E) Ratio.
        *   **Why It Matters:** Companies with a D/E ratio greater than 1.5 are heavily reliant on borrowing. In high-inflation economies, the cost of servicing this debt can rapidly wipe out net profits, pushing the stock price down.
        """)

    # ── Position sizing ──────────────────────────────────────────────────────
    st.markdown("#### 🧮 Position Sizing Calculator")
    total_cap = get_total_capital()

    ps1, ps2 = st.columns(2)
    with ps1:
        user_cap    = st.number_input("Total capital (PKR):", value=float(total_cap),
                                      step=10000.0, key=f"cap_{symbol}")
        num_pos     = st.slider("Number of positions:", 3, 20, 10, key=f"npos_{symbol}")
    with ps2:
        custom_alloc = st.slider("Or set % allocation:", 1, 25, 0,
                                 key=f"alloc_{symbol}",
                                 help="Set to 0 to use equal-weight split")

    alloc_pct = custom_alloc / 100 if custom_alloc > 0 else None
    sizing = calc_position_size(user_cap, num_pos, result["current_price"], alloc_pct)

    sz1, sz2, sz3, sz4 = st.columns(4)
    sz1.metric("Capital Allocated", f"PKR {sizing['capital_allocated']:,.0f}")
    sz2.metric("Shares to Buy",     f"{sizing['shares']:,} shares")
    sz3.metric("Total Cost",        f"PKR {sizing['cost']:,.0f}")
    sz4.metric("Remaining Cash",    f"PKR {sizing['remaining_capital']:,.0f}")

    # Add to portfolio
    st.markdown("---")
    st.markdown("#### ➕ Add to Portfolio")
    col_add1, col_add2, col_add3 = st.columns([1,1,2])
    entry_p = col_add1.number_input("Entry price (PKR):",
                                    value=result["current_price"],
                                    key=f"entry_{symbol}")
    shares_n = col_add2.number_input("Shares:", value=float(sizing["shares"]),
                                     min_value=0.0, step=1.0, key=f"shares_{symbol}")
    if col_add3.button(f"💾 Save {symbol} to Portfolio", key=f"save_{symbol}"):
        add_position(symbol, entry_p, int(shares_n))
        update_capital(user_cap)
        st.success(f"✅ Added {symbol} — {int(shares_n)} shares @ PKR {entry_p:,.2f}")
        st.rerun()


# ---------------------------------------------------------------------------
# Main tab renderer
# ---------------------------------------------------------------------------

def render_predictions_tab(results: dict, accuracy: dict):
    st.markdown("### 📈 Predictions & Rankings")

    # Accuracy tracker
    if accuracy and accuracy["total_checked"] > 0:
        hr = accuracy["hit_rate_pct"]
        color = "#4ade80" if hr >= 60 else "#fbbf24" if hr >= 50 else "#f87171"
        st.markdown(
            f"""<div style="background:#1e293b;padding:10px 18px;border-radius:8px;
            margin-bottom:16px;display:inline-block;">
            🎯 Prediction accuracy (last session): 
            <strong style="color:{color}">{hr:.1f}%</strong>
            ({accuracy['hits']}/{accuracy['total_checked']} correct)
            </div>""", unsafe_allow_html=True,
        )

    # Rankings table
    df_rank = render_rankings_table(results)
    st.dataframe(df_rank, width="stretch", hide_index=True,
                 column_config={
                     "Score":      st.column_config.ProgressColumn("Score", min_value=0, max_value=100),
                     "Confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=100,
                                                                   help="Mathematical confidence score (0-100)"),
                     "RSI":        st.column_config.NumberColumn("RSI", format="%.1f"),
                     "Price (PKR)": st.column_config.NumberColumn("Price (PKR)", format="%.2f"),
                 })

    st.markdown("---")
    st.markdown("### 🔍 Detailed Stock Analysis")

    valid_symbols = [sym for sym, r in results.items() if "error" not in r]
    if not valid_symbols:
        st.warning("No valid analysis results. Run the daily analysis first.")
        return

    selected = st.selectbox("Select stock for detail", valid_symbols, key="pred_stock_select")
    if selected:
        render_stock_detail(selected, results[selected])

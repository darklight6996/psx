"""
ui/portfolio_tab.py — Portfolio Management Tab (Tab 4).

Shows:
- Current positions with live P&L
- Add / remove positions
- Capital settings
- Prediction accuracy history
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.portfolio import (
    load_portfolio, get_positions, get_total_capital,
    add_position, remove_position, update_capital,
    portfolio_summary, load_memory,
)
from core.data_engine import get_latest_price


def render_portfolio_tab():
    st.markdown("### 💼 Portfolio Manager")

    # ── Capital setting ───────────────────────────────────────────────────────
    st.markdown("#### 🏦 Total Capital")
    cur_capital = get_total_capital()
    new_capital = st.number_input(
        "Set total portfolio capital (PKR):",
        value=float(cur_capital),
        step=10_000.0,
        min_value=1_000.0,
        key="capital_input",
    )
    if st.button("💾 Update Capital", key="update_capital_btn"):
        update_capital(new_capital)
        st.success(f"✅ Capital updated to PKR {new_capital:,.0f}")
        st.rerun()

    st.markdown("---")

    # ── Add position ──────────────────────────────────────────────────────────
    st.markdown("#### ➕ Add New Position")
    col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 1])
    ticker_in   = col1.text_input("Ticker", placeholder="e.g. SYS", key="add_ticker").upper()
    entry_in    = col2.number_input("Entry Price (PKR)", min_value=0.01, step=0.5, key="add_entry")
    shares_in   = col3.number_input("Shares", min_value=1, step=1, key="add_shares")
    date_in     = col4.date_input("Date", key="add_date")

    if col5.button("Add ✚", key="add_pos_btn"):
        if ticker_in and entry_in > 0 and shares_in > 0:
            add_position(ticker_in, entry_in, int(shares_in), str(date_in))
            st.success(f"✅ Added {ticker_in}: {int(shares_in)} shares @ PKR {entry_in:,.2f}")
            st.rerun()
        else:
            st.error("Please fill in all fields correctly.")

    st.markdown("---")

    # ── Current positions ─────────────────────────────────────────────────────
    st.markdown("#### 📋 Current Positions")
    positions = get_positions()

    if not positions:
        st.info("No positions yet. Add your first position above.")
        return

    # Fetch live prices
    with st.spinner("Fetching live prices..."):
        live_prices = {}
        for sym in positions:
            p = get_latest_price(sym)
            if p:
                live_prices[sym] = p

    summary = portfolio_summary(live_prices)

    # Summary KPIs
    k1, k2, k3, k4, k5 = st.columns(5)
    pnl_delta = f"{summary['total_pnl_pct']:+.1f}%"
    k1.metric("Positions",       str(summary["num_positions"]))
    k2.metric("Total Invested",  f"PKR {summary['total_invested']:,.0f}")
    k3.metric("Market Value",    f"PKR {summary['current_value']:,.0f}", delta=pnl_delta)
    k4.metric("Total P&L",       f"PKR {summary['total_pnl']:+,.0f}")
    k5.metric("Cash Available",  f"PKR {summary['cash_remaining']:,.0f}")

    # Allocation pie
    if summary["positions"]:
        labels = [p["ticker"] for p in summary["positions"]]
        values = [p["current_value"] for p in summary["positions"]]
        fig_pie = go.Figure(go.Pie(
            labels=labels, values=values,
            hole=0.5,
            marker_colors=[
                "#38bdf8","#4ade80","#fbbf24","#f87171",
                "#a78bfa","#34d399","#fb923c","#e879f9",
                "#60a5fa","#facc15",
            ],
        ))
        fig_pie.update_layout(
            height=300,
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
            margin=dict(t=20,b=20,l=20,r=20),
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig_pie, use_container_width=True, key="portfolio_pie")

    # Positions table with remove buttons
    for pos in summary["positions"]:
        sym    = pos["ticker"]
        pnl_c  = "#4ade80" if pos["pnl"] >= 0 else "#f87171"
        arrow  = "▲" if pos["pnl"] >= 0 else "▼"

        with st.container():
            row = st.columns([1.5, 1.5, 1.5, 1.5, 1.5, 2, 1])
            row[0].markdown(f"**{sym}**")
            row[1].markdown(f"Entry: PKR {pos['entry_price']:,.2f}")
            row[2].markdown(f"Now: PKR {pos['current_price']:,.2f}" if pos['current_price'] else "Now: N/A")
            row[3].markdown(f"Shares: {pos['shares']:,}")
            row[4].markdown(f"Cost: PKR {pos['cost_basis']:,.0f}")
            row[5].markdown(
                f"<span style='color:{pnl_c}'>{arrow} PKR {pos['pnl']:+,.0f} ({pos['pnl_pct']:+.1f}%)</span>",
                unsafe_allow_html=True,
            )
            if row[6].button("✕ Remove", key=f"remove_{sym}"):
                remove_position(sym)
                st.success(f"Removed {sym}")
                st.rerun()

        st.markdown("<hr style='border-color:#1e293b;margin:4px 0'>", unsafe_allow_html=True)

    # ── Prediction accuracy history ───────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🎯 Prediction Accuracy History")

    memory = load_memory()
    acc    = memory.get("prediction_accuracy", {})

    if acc.get("total", 0) > 0:
        hit_rate = acc["hits"] / acc["total"] * 100
        a1, a2, a3 = st.columns(3)
        a1.metric("Total Predictions Tracked", str(acc["total"]))
        a2.metric("Correct",                   str(acc["hits"]))
        a3.metric("Hit Rate",                  f"{hit_rate:.1f}%",
                  delta="Good" if hit_rate >= 55 else "Needs improvement")
    else:
        st.info("No prediction accuracy data yet. Run the daily analysis across multiple days to build up accuracy tracking.")

    # Daily snapshots count
    snapshots = memory.get("daily_snapshots", {})
    if snapshots:
        st.markdown(f"**Tracking history:** {len(snapshots)} days of data stored")
        dates = sorted(snapshots.keys())
        st.markdown(f"First snapshot: `{dates[0]}`  |  Last: `{dates[-1]}`")

        if st.button("🗑️ Clear prediction history", key="clear_history"):
            from core.portfolio import _save_json, MEMORY_FILE
            _save_json(MEMORY_FILE, {"daily_snapshots": {}, "prediction_accuracy": {"hits": 0, "misses": 0, "total": 0}})
            st.success("History cleared.")
            st.rerun()

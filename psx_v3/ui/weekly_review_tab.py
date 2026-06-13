"""
ui/weekly_review_tab.py — Weekly Performance Review Tab

The core "money memory" tab:
- Shows every investment you made, where, how much
- Current value vs invested
- Week-over-week P&L narrative
- Divest / Add More recommendations
- Full investment history
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.db import (
    get_open_investments, get_all_investments,
    get_investment_summary, generate_weekly_review,
    close_investment, get_weekly_history,
    get_agent_log, add_investment,
)
from core.data_engine import get_latest_price


def render_weekly_review_tab(daily_results: dict = None):
    st.markdown("### 📅 Weekly Performance Review")
    st.markdown("_Your personal investment memory — what you put in, what it's worth now, what to do next._")

    # ── Fetch live prices for open positions ─────────────────────────────────
    open_positions = get_open_investments()
    if not open_positions:
        st.info("""
No investments recorded yet.

After the board recommends **BUY** in the 🏛️ AI Board Room tab,
click **"I invested PKR X in SYMBOL"** to record it here.
Or use the **Add Investment** form below to record a manual entry.
        """)
        _render_add_investment_form()
        return

    with st.spinner("Fetching live prices for your positions..."):
        live_prices = {}
        for pos in open_positions:
            sym = pos["symbol"]
            # Try daily_results first (already fetched), else fetch fresh
            if daily_results and sym in daily_results and "current_price" in daily_results[sym]:
                live_prices[sym] = daily_results[sym]["current_price"]
            else:
                p = get_latest_price(sym)
                if p:
                    live_prices[sym] = p

    # ── Weekly review ─────────────────────────────────────────────────────────
    review = generate_weekly_review(live_prices)

    # Portfolio headline
    total_in  = review["total_invested"]
    total_now = review["total_current_value"]
    total_pnl = review["total_pnl_pkr"]
    pnl_pct   = review["total_pnl_pct"]
    pnl_color = "#4ade80" if total_pnl >= 0 else "#f87171"
    arrow     = "▲" if total_pnl >= 0 else "▼"

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#0f172a,#1e1b4b);border:1px solid #334155;
    border-radius:14px;padding:24px;margin-bottom:20px">
        <div style="font-size:13px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">
            Your Portfolio — {date.today().strftime('%d %B %Y')}
        </div>
        <div style="display:flex;gap:32px;flex-wrap:wrap">
            <div>
                <div style="font-size:12px;color:#64748b">Total Invested</div>
                <div style="font-size:26px;font-weight:800;color:#f1f5f9">PKR {total_in:,.0f}</div>
            </div>
            <div>
                <div style="font-size:12px;color:#64748b">Current Value</div>
                <div style="font-size:26px;font-weight:800;color:#f1f5f9">PKR {total_now:,.0f}</div>
            </div>
            <div>
                <div style="font-size:12px;color:#64748b">Total P&L</div>
                <div style="font-size:26px;font-weight:800;color:{pnl_color}">
                    {arrow} PKR {abs(total_pnl):,.0f} ({pnl_pct:+.1f}%)
                </div>
            </div>
            <div>
                <div style="font-size:12px;color:#64748b">Positions</div>
                <div style="font-size:26px;font-weight:800;color:#f1f5f9">{len(open_positions)}</div>
            </div>
        </div>
        <p style="color:#94a3b8;font-size:13px;margin-top:16px;line-height:1.6">
            {review['portfolio_narrative']}
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Winners / Losers
    if review["winners"] or review["losers"]:
        wc, lc = st.columns(2)
        with wc:
            if review["winners"]:
                st.success(f"📈 **Winning this week:** {', '.join(review['winners'])}")
        with lc:
            if review["losers"]:
                st.error(f"📉 **Under pressure:** {', '.join(review['losers'])}")

    st.markdown("---")
    st.markdown("#### 📊 Position-by-Position Review")

    # Position cards
    for pos_review in review["positions"]:
        sym      = pos_review["symbol"]
        invested = pos_review["invested"]
        now_val  = pos_review["now_value"]
        pnl_pkr  = pos_review["pnl_pkr"]
        pnl_pct  = pos_review["pnl_pct"]
        rec      = pos_review["recommendation"]
        signal   = pos_review["signal"]
        weeks    = pos_review["weeks_held"]

        pc = "#4ade80" if pnl_pkr >= 0 else "#f87171"
        pbg= "#0f4c2a" if pnl_pkr >= 0 else "#4a1818"
        rec_color = {"HOLD": "#fbbf24", "CONSIDER PARTIAL DIVEST": "#f97316",
                     "WATCH — approaching stop": "#f59e0b",
                     "⚠️ REVIEW — stop loss territory": "#f87171"}.get(rec, "#94a3b8")


        with st.container():
            col_sym, col_vals, col_pnl, col_stop, col_rec, col_action = st.columns([1.5, 2.5, 2, 2, 2, 1.5])

            col_sym.markdown(f"**{sym}**\n\n_{weeks}w held_")
            col_vals.markdown(
                f"Invested: **PKR {invested:,.0f}**\n\n"
                f"Now: **PKR {now_val:,.0f}**"
            )
            col_pnl.markdown(
                f'<span style="color:{pc};font-weight:700;font-size:15px">'
                f'{"▲" if pnl_pkr>=0 else "▼"} PKR {abs(pnl_pkr):,.0f} ({pnl_pct:+.1f}%)'
                f'</span>', unsafe_allow_html=True
            )
            
            # Trailing stop column calculation
            from core.indicators import calc_trailing_stop
            inv_records = [i for i in open_positions if i["symbol"] == sym]
            if inv_records:
                entry_p = inv_records[0]["entry_price"]
                cur_p = live_prices.get(sym, entry_p)
                stop_status = calc_trailing_stop(entry_p, cur_p, stop_pct=0.10)
                stop_val = stop_status['stop_price']
                col_stop.markdown(f"Stop: **PKR {stop_val:.2f}**\n\n_{stop_status['drawdown_pct']:.1f}% draw_")
            else:
                col_stop.markdown("Stop: **N/A**")
                
            col_rec.markdown(
                f'<span style="color:{rec_color};font-size:13px">{rec}</span>',
                unsafe_allow_html=True
            )
            inv_records = [i for i in open_positions if i["symbol"] == sym]
            if inv_records and col_action.button(f"Close {sym}", key=f"close_{sym}"):
                inv_id = inv_records[0]["id"]
                close_price = live_prices.get(sym, inv_records[0]["entry_price"])
                close_investment(inv_id, close_price)
                realised = (close_price - inv_records[0]["entry_price"]) * inv_records[0]["shares"]
                st.success(f"✅ Closed {sym} @ PKR {close_price:,.2f}. "
                           f"Realised P&L: PKR {realised:+,.0f}")
                st.rerun()

            st.markdown(
                f'<div style="background:#1e293b;border-radius:6px;padding:8px 12px;'
                f'margin-bottom:12px;font-size:12px;color:#94a3b8">'
                f'{signal} — {pos_review["narrative"]}'
                f'</div>', unsafe_allow_html=True
            )

    # ── P&L over time chart ───────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 📈 Weekly P&L History")
    weekly_hist = get_weekly_history(weeks=12)

    if len(weekly_hist) >= 2:
        df_wh = pd.DataFrame(weekly_hist)
        df_wh["snapshot_date"] = pd.to_datetime(df_wh["snapshot_date"])

        # Aggregate by date
        agg = df_wh.groupby("snapshot_date").agg(
            total_value=("value_now", "sum"),
            total_cost=("value_then", "sum"),
        ).reset_index()
        agg["pnl"] = agg["total_value"] - agg["total_cost"]

        fig = go.Figure()
        colors = ["#4ade80" if p >= 0 else "#f87171" for p in agg["pnl"]]
        fig.add_trace(go.Bar(
            x=agg["snapshot_date"], y=agg["pnl"],
            name="Weekly P&L", marker_color=colors,
        ))
        fig.add_trace(go.Scatter(
            x=agg["snapshot_date"], y=agg["total_value"],
            name="Portfolio Value", yaxis="y2",
            line=dict(color="#38bdf8", width=2),
        ))
        fig.update_layout(
            height=320,
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
            xaxis=dict(gridcolor="#1e293b"),
            yaxis=dict(gridcolor="#1e293b", title="Weekly P&L (PKR)"),
            yaxis2=dict(overlaying="y", side="right", showgrid=False, title="Portfolio Value"),
            legend=dict(orientation="h", y=1.05),
            margin=dict(t=30,b=30,l=60,r=60),
        )
        fig.add_hline(y=0, line_color="#334155", line_width=1)
        st.plotly_chart(fig, width="stretch", key="weekly_pnl_chart")
    else:
        st.info("Weekly history will appear here after multiple sessions. Check back next week.")

    # ── Full investment history ───────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 📋 Full Investment History")
    all_inv = get_all_investments()
    if all_inv:
        df_all = pd.DataFrame(all_inv)
        cols_show = ["symbol","company_name","pkr_invested","shares","entry_price",
                     "exit_price","entry_date","exit_date","status","notes"]
        cols_show = [c for c in cols_show if c in df_all.columns]
        st.dataframe(df_all[cols_show], width="stretch", hide_index=True)
    else:
        st.info("No investment history yet.")

    # ── Add manual investment ─────────────────────────────────────────────────
    st.markdown("---")
    _render_add_investment_form()

    # ── Agent activity log ────────────────────────────────────────────────────
    with st.expander("📋 Agent Activity Log", expanded=False):
        logs = get_agent_log(limit=50)
        if logs:
            for log in logs:
                icon = {"INVEST": "💰", "DIVEST": "💸", "COUNCIL": "🏛️",
                        "WEEKLY_REVIEW": "📅", "ANALYSIS": "📊"}.get(log["event_type"], "•")
                st.markdown(
                    f'<div style="font-size:12px;color:#94a3b8;margin-bottom:4px">'
                    f'{icon} <strong>{log["created_at"][:16]}</strong> '
                    f'[{log["event_type"]}] {log["message"]}'
                    f'</div>', unsafe_allow_html=True
                )
        else:
            st.info("No activity logged yet.")


def _render_add_investment_form():
    st.markdown("#### ➕ Manually Record an Investment")
    with st.form("manual_investment_form"):
        c1, c2, c3, c4 = st.columns(4)
        sym_in    = c1.text_input("Ticker", placeholder="SYS").upper()
        pkr_in    = c2.number_input("PKR Invested", min_value=100.0, step=500.0, value=10000.0)
        price_in  = c3.number_input("Entry Price (PKR)", min_value=0.01, step=0.5, value=100.0)
        date_in   = c4.date_input("Date", value=date.today())

        import math
        shares_est = math.floor(pkr_in / price_in) if price_in > 0 else 0
        st.markdown(f"→ **{shares_est} shares** at PKR {price_in:,.2f} = PKR {shares_est * price_in:,.0f}")

        notes_in = st.text_input("Notes (optional)", placeholder="Board recommended BUY, HQM 72")
        submitted = st.form_submit_button("💾 Record Investment")

        if submitted and sym_in and pkr_in > 0 and price_in > 0:
            add_investment(sym_in, sym_in, pkr_in, shares_est, price_in, str(date_in), notes_in)
            st.success(f"✅ Recorded {shares_est} shares of {sym_in} @ PKR {price_in:,.2f}")
            st.rerun()

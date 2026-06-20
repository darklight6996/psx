"""
ui/dashboard_tab.py — Streamlit Dashboard Tab (Tab 1).

Shows:
- Live Index Ticker Row
- Sorted Active Alerts (STOP_HIT first, SELL second, then others)
- Portfolio Overview
- Interactive Candlestick Charts & Volume
- Order Book bid/ask ratios for selected stocks
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.data_engine  import fetch_ohlcv, fetch_multi_timeframe
from core.indicators   import calc_rsi, calc_bollinger, calc_macd, calc_ema
from core.portfolio    import get_positions, get_total_capital
from core.psx_live     import get_live_quote


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def make_candlestick_chart(df: pd.DataFrame, symbol: str, show_indicators: bool = True) -> go.Figure:
    """Full candlestick chart with RSI, Bollinger, MACD sub-plots."""
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        subplot_titles=(f"{symbol} — Price & Bollinger", "RSI (14)", "MACD"),
        row_heights=[0.6, 0.2, 0.2],
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name=symbol,
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ), row=1, col=1)

    if show_indicators:
        # Bollinger bands
        bb = calc_bollinger(df)
        if not bb.empty:
            fig.add_trace(go.Scatter(x=df.index, y=bb["bb_upper"], name="BB Upper",
                line=dict(color="rgba(150,150,255,0.5)", width=1), showlegend=False), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=bb["bb_lower"], name="BB Lower",
                line=dict(color="rgba(150,150,255,0.5)", width=1),
                fill="tonexty", fillcolor="rgba(150,150,255,0.07)", showlegend=False), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=bb["bb_mid"], name="BB Mid",
                line=dict(color="rgba(200,200,200,0.4)", width=1, dash="dot"), showlegend=False), row=1, col=1)

        # EMA
        emas = calc_ema(df, [20, 50])
        fig.add_trace(go.Scatter(x=df.index, y=emas["ema_20"], name="EMA 20",
            line=dict(color="#ff9800", width=1.2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=emas["ema_50"], name="EMA 50",
            line=dict(color="#2196f3", width=1.2)), row=1, col=1)

        # RSI
        rsi = calc_rsi(df)
        if not rsi.empty:
            fig.add_trace(go.Scatter(x=df.index, y=rsi, name="RSI",
                line=dict(color="#9c27b0", width=1.5)), row=2, col=1)
            fig.add_hline(y=70, line_dash="dash", line_color="#ef5350", line_width=1, row=2, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="#26a69a", line_width=1, row=2, col=1)
            fig.add_hrect(y0=70, y1=100, fillcolor="rgba(239,83,80,0.08)", line_width=0, row=2, col=1)
            fig.add_hrect(y0=0,  y1=30,  fillcolor="rgba(38,166,154,0.08)", line_width=0, row=2, col=1)

        # MACD
        macd_df = calc_macd(df)
        if not macd_df.empty:
            colors = ["#26a69a" if v >= 0 else "#ef5350" for v in macd_df["macd_hist"]]
            fig.add_trace(go.Bar(x=df.index, y=macd_df["macd_hist"], name="MACD Hist",
                marker_color=colors, opacity=0.7), row=3, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=macd_df["macd"], name="MACD",
                line=dict(color="#2196f3", width=1.2)), row=3, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=macd_df["macd_signal"], name="Signal",
                line=dict(color="#ff9800", width=1.2)), row=3, col=1)

    fig.update_layout(
        height=700,
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font_color="#fafafa",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=50, b=40, l=60, r=20),
    )
    fig.update_xaxes(gridcolor="#1e293b", showgrid=True)
    fig.update_yaxes(gridcolor="#1e293b", showgrid=True)

    return fig


def make_volume_chart(df: pd.DataFrame, symbol: str) -> go.Figure:
    avg_vol = df["Volume"].rolling(20).mean()
    colors  = ["#26a69a" if c >= o else "#ef5350" for c, o in zip(df["Close"], df["Open"])]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume",
        marker_color=colors, opacity=0.8))
    fig.add_trace(go.Scatter(x=df.index, y=avg_vol, name="20-day avg",
        line=dict(color="#ff9800", width=1.5, dash="dash")))

    fig.update_layout(
        title=f"{symbol} — Volume",
        height=200,
        plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
        margin=dict(t=40, b=30, l=60, r=20),
        showlegend=True,
    )
    fig.update_xaxes(gridcolor="#1e293b")
    fig.update_yaxes(gridcolor="#1e293b")
    return fig


# ---------------------------------------------------------------------------
# Main tab renderer
# ---------------------------------------------------------------------------

def render_dashboard_tab(daily_results: dict, macro: dict, alerts: list, port_summary: dict):
    # ── Market Status & Macro Banner ──────────────────────────────────────────
    from core.data_engine import get_market_status
    mstatus = get_market_status()
    
    col_m1, col_m2 = st.columns([1, 2])
    with col_m1:
        if mstatus["status"] == "OPEN":
            st.markdown(
                f"""<div style="background:#0f4c2a;padding:12px 20px;border-radius:8px;
                margin-bottom:16px;border:1px solid #22c55e;text-align:center;min-height:72px;">
                🟢 <strong style="color:#4ade80;">Live Market: OPEN</strong><br>
                <span style="font-size:11px;color:#a7f3d0;">{mstatus['pkt_time']}</span>
                </div>""",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""<div style="background:#2a1a1a;padding:12px 20px;border-radius:8px;
                margin-bottom:16px;border:1px solid #ef4444;text-align:center;min-height:72px;">
                🔴 <strong style="color:#f87171;">Market is CLOSED</strong><br>
                <span style="font-size:10px;color:#fca5a5;">{mstatus['reason']}</span>
                </div>""",
                unsafe_allow_html=True,
            )
            
    with col_m2:
        sentiment = macro.get("sentiment", "neutral")
        color_map  = {"bullish": "#0f4c2a", "bearish": "#4a1818", "neutral": "#1e293b"}
        icon_map   = {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}
        st.markdown(
            f"""<div style="background:{color_map[sentiment]};padding:12px 20px;border-radius:8px;
            margin-bottom:16px;border:1px solid #334155;min-height:72px;display:flex;align-items:center;">
            <div>
            {icon_map[sentiment]} <strong>Macro Sentiment: {sentiment.upper()}</strong> — {macro.get('summary','')}
            </div>
            </div>""",
            unsafe_allow_html=True,
        )

    # ── Live Index Ticker Row (PSX Data Portal) ──────────────────────────────
    from core.psx_index_pipeline import get_cached_indices
    indices_data = get_cached_indices()
    last_updated = indices_data.get("last_updated", "Never")
    indices = indices_data.get("indices", {})
    
    if indices:
        st.markdown(f"#### 🏛️ PSX Live Market Indices <span style='font-size:12px;color:#64748b;font-weight:400;'>As of {last_updated}</span>", unsafe_allow_html=True)
        
        idx_cols = st.columns(4)
        for idx, (sym, data) in enumerate(indices.items()):
            name = data.get("name", sym)
            val = data.get("value", 0.0)
            change = data.get("change", 0.0)
            pct_change = data.get("pct_change", 0.0)
            high = data.get("high", 0.0)
            low = data.get("low", 0.0)
            volume = data.get("volume", 0)
            
            # Formatting
            sign = "+" if change >= 0 else ""
            color = "#4ade80" if change >= 0 else "#f87171"
            arrow = "▲" if change >= 0 else "▼"
            
            with idx_cols[idx]:
                st.markdown(f"""
                <div style="background:#1e293b;border:1px solid #334155;border-radius:10px;padding:12px 16px;">
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;font-weight:600;">{name}</div>
                    <div style="font-size:20px;font-weight:800;color:#f1f5f9;margin-top:4px;">{val:,.2f}</div>
                    <div style="color:{color};font-size:13px;font-weight:700;margin-top:2px;">
                        {arrow} {sign}{change:,.2f} ({sign}{pct_change:.2f}%)
                    </div>
                    <div style="color:#475569;font-size:10px;margin-top:6px;line-height:1.4;">
                        High: <span style="color:#94a3b8;">{high:,.2f}</span> | Low: <span style="color:#94a3b8;">{low:,.2f}</span><br>
                        Vol: <span style="color:#94a3b8;">{volume:,}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        st.markdown("<hr style='margin:16px 0 24px 0; border-color:#334155;'>", unsafe_allow_html=True)

    # ── Sorted Alerts (STOP_HIT first, SELL second, then others) ──────────────
    if alerts:
        st.markdown("### ⚠️ Active Alerts")
        def alert_priority(a):
            t = a.get("type", "")
            if t == "STOP_HIT":
                return 1
            elif t == "SELL":
                return 2
            else:
                return 3
        sorted_alerts = sorted(alerts, key=alert_priority)
        for alert in sorted_alerts:
            color = "#f87171" if alert["type"] in ("SELL", "STOP_HIT") else "#fbbf24"
            st.markdown(
                f"""<div style="background:#1e293b;border-left:4px solid {color};
                padding:10px 16px;border-radius:4px;margin-bottom:8px;font-size:14px;">
                <strong>[{alert['type']}]</strong> {alert['symbol']} — {alert['reason']}</div>""",
                unsafe_allow_html=True,
            )

    # ── Portfolio summary cards ──────────────────────────────────────────────
    if port_summary and port_summary.get("num_positions", 0) > 0:
        st.markdown("### 💼 Portfolio Overview")
        c1, c2, c3, c4 = st.columns(4)
        pnl_color = "#4ade80" if port_summary["total_pnl"] >= 0 else "#f87171"
        c1.metric("Total Capital",    f"PKR {port_summary['total_capital']:,.0f}")
        c2.metric("Invested",         f"PKR {port_summary['total_invested']:,.0f}")
        c3.metric("Current Value",    f"PKR {port_summary['current_value']:,.0f}",
                  delta=f"{port_summary['total_pnl_pct']:+.1f}%")
        c4.metric("Cash Remaining",   f"PKR {port_summary['cash_remaining']:,.0f}")

        # Position table
        if port_summary["positions"]:
            df_pos = pd.DataFrame(port_summary["positions"])
            df_pos["pnl_color"] = df_pos["pnl"].apply(lambda x: "🟢" if x >= 0 else "🔴")
            st.dataframe(
                df_pos[["ticker","entry_price","current_price","shares","cost_basis","current_value","pnl","pnl_pct"]],
                use_container_width=True, hide_index=True,
            )

    # ── Stock chart viewer & Live Order Book Ratios ───────────────────────────
    st.markdown("### 📊 Price Charts & Live Market Depth")

    available = [sym for sym, r in daily_results.items() if "error" not in r]
    if not available:
        st.warning("No stock data available. Run analysis first.")
        return

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        selected = st.selectbox("Select stock", available, key="dashboard_stock_select")
    with col2:
        timeframe = st.selectbox("Timeframe", ["6 months","1 year","3 months","1 month"], key="tf_select")
    with col3:
        show_ind  = st.checkbox("Show indicators", value=True, key="show_indicators")

    period_map = {"1 month": "1mo", "3 months": "3mo", "6 months": "6mo", "1 year": "1y"}
    period     = period_map.get(timeframe, "6mo")

    if selected:
        result = daily_results[selected]

        # Rating badge
        rating = result["advisory"]["rating"]
        rc = {"BUY": "#4ade80", "SELL": "#f87171", "HOLD": "#fbbf24"}[rating]
        bg = {"BUY": "#0f4c2a", "SELL": "#4a1818", "HOLD": "#3a2c0a"}[rating]

        st.markdown(
            f"""<div style="display:inline-flex;align-items:center;gap:12px;margin-bottom:12px;">
            <span style="font-size:20px;font-weight:700;color:#f1f5f9">{selected}</span>
            <span style="background:{bg};color:{rc};border:1px solid {rc}55;padding:4px 14px;
            border-radius:20px;font-size:13px;font-weight:700">{rating}</span>
            <span style="color:#64748b;font-size:14px">PKR {result['current_price']:,.2f}</span>
            </div>""", unsafe_allow_html=True,
        )

        # ── Live Quote and Order Book Imbalance Ratio ──
        lq = get_live_quote(selected)
        if lq and lq.get("last_price") is not None:
            bid_vol = lq.get("bid_volume", 0.0)
            ask_vol = lq.get("ask_volume", 0.0)
            if ask_vol > 0:
                ob_ratio = bid_vol / ask_vol
            else:
                ob_ratio = 1.0 if bid_vol > 0 else 0.0
                
            st.markdown(
                f"""<div style="background:#1e293b;border:1px solid #334155;border-radius:10px;padding:12px 18px;margin-bottom:16px;display:flex;gap:20px;flex-wrap:wrap;">
                    <div><strong>Live Bid:</strong> PKR {lq.get('bid'):,.2f} ({int(bid_vol):,})</div>
                    <div style="border-left:1px solid #334155;padding-left:20px;"><strong>Live Ask:</strong> PKR {lq.get('ask'):,.2f} ({int(ask_vol):,})</div>
                    <div style="border-left:1px solid #334155;padding-left:20px;"><strong>Order Book Ratio (Bid/Ask Vol):</strong> {ob_ratio:.2f}</div>
                </div>""", unsafe_allow_html=True
            )

        # Fetch chart data
        df_chart = fetch_ohlcv(selected, period=period, interval="1d")
        if df_chart is not None and not df_chart.empty:
            st.plotly_chart(make_candlestick_chart(df_chart, selected, show_ind),
                           use_container_width=True, key=f"candle_{selected}")
            st.plotly_chart(make_volume_chart(df_chart, selected),
                           use_container_width=True, key=f"vol_{selected}")
        else:
            st.error(f"Could not load chart data for {selected}")

        # Intraday (1h)
        with st.expander("📈 Intraday View (1-hour candles)"):
            df_1h = fetch_ohlcv(selected, period="1mo", interval="60m")
            if df_1h is not None:
                fig_1h = go.Figure(go.Candlestick(
                    x=df_1h.index,
                    open=df_1h["Open"], high=df_1h["High"],
                    low=df_1h["Low"], close=df_1h["Close"],
                    increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
                ))
                fig_1h.update_layout(
                    height=350, plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                    font_color="#fafafa", xaxis_rangeslider_visible=False,
                    margin=dict(t=30,b=30,l=60,r=20),
                )
                fig_1h.update_xaxes(gridcolor="#1e293b")
                fig_1h.update_yaxes(gridcolor="#1e293b")
                st.plotly_chart(fig_1h, use_container_width=True, key=f"1h_{selected}")

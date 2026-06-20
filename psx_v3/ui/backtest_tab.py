"""
ui/backtest_tab.py — Backtester Tab (Tab 3).

Lets user run a historical momentum strategy backtest and view:
- Equity curve vs KSE100 benchmark
- Trade log
- Performance metrics
- Survivorship bias warning
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.backtester import run_backtest
from core.kmi_data import KMI_ALL_SHARE, DEFAULT_WATCHLIST


def render_backtest_tab():
    st.markdown("### 🧪 Strategy Backtester")

    st.warning(
        "⚠️ **Survivorship Bias Warning:** This backtester only uses stocks currently "
        "available on Yahoo Finance. Companies that went bankrupt or were delisted are "
        "**not** included, which inflates performance. Treat all results as optimistic estimates."
    )

    with st.expander("ℹ️ How the backtest works", expanded=False):
        st.markdown("""
        **Strategy:** High-Quality Momentum (HQM)
        1. Every N days, score all stocks by their 1M / 3M / 6M / 12M return percentile ranks.
        2. Buy equal-weight in the top N highest-scoring stocks.
        3. Apply a trailing stop loss per position.
        4. Rebalance, exiting positions that fall out of the top picks.
        5. Compare final equity to the KSE100 benchmark.

        **This is a paper backtest — no real money is involved.**
        Use it to validate whether the HQM strategy would have worked historically,
        before trusting it with real capital.
        """)

    # ── Configuration ─────────────────────────────────────────────────────────
    st.markdown("#### ⚙️ Backtest Settings")

    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input("Start date", value=pd.Timestamp("2019-01-01"))
        end_date   = st.date_input("End date",   value=pd.Timestamp("2024-01-01"))
        initial_cap = st.number_input("Initial capital (PKR)", value=500_000, step=50_000)

    with c2:
        top_n           = st.slider("Top N stocks to hold",    3, 15, 5)
        rebalance_days  = st.slider("Rebalance every N days", 15, 90, 30)
        stop_loss_pct   = st.slider("Trailing stop (%)",       5, 25, 10) / 100

    universe_choice = st.radio(
        "Universe to test",
        ["Default Watchlist (fast)", "Full KMI All Share (slow ~5 min)"],
        horizontal=True,
    )

    symbols = DEFAULT_WATCHLIST if "Default" in universe_choice else KMI_ALL_SHARE

    st.markdown(f"**Universe:** {len(symbols)} stocks")

    run_btn = st.button("▶️ Run Backtest", type="primary", key="run_backtest_btn")

    if run_btn:
        with st.spinner(f"Running backtest on {len(symbols)} stocks from {start_date} to {end_date}... This may take several minutes."):
            results = run_backtest(
                symbols         = symbols,
                start_date      = str(start_date),
                end_date        = str(end_date),
                rebalance_days  = rebalance_days,
                top_n           = top_n,
                stop_loss_pct   = stop_loss_pct,
                initial_capital = float(initial_cap),
            )

        if "error" in results:
            st.error(f"Backtest failed: {results['error']}")
            return

        st.session_state["backtest_results"] = results

    # ── Display results ───────────────────────────────────────────────────────
    if "backtest_results" not in st.session_state:
        st.info("Configure settings above and click **Run Backtest** to begin.")
        return

    results = st.session_state["backtest_results"]
    summary = results["summary"]

    st.markdown("---")
    st.markdown("#### 📊 Performance Summary")

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    ret_color = "normal" if summary["total_return_pct"] >= 0 else "inverse"
    m1.metric("Total Return",    f"{summary['total_return_pct']:+.1f}%")
    m2.metric("CAGR",            f"{summary['cagr_pct']:+.1f}%")
    m3.metric("Max Drawdown",    f"{summary['max_drawdown_pct']:.1f}%")
    m4.metric("Sharpe Ratio",    f"{summary['sharpe_ratio']:.2f}")
    m5.metric("Win Rate",        f"{summary['win_rate_pct']:.1f}%")
    if summary.get("benchmark_return") is not None:
        alpha = summary["total_return_pct"] - summary["benchmark_return"]
        m6.metric("Alpha vs KSE100", f"{alpha:+.1f}%",
                  delta=f"Benchmark: {summary['benchmark_return']:+.1f}%")
    else:
        m6.metric("Total Trades",    str(summary["total_trades"]))

    # ── Equity curve ──────────────────────────────────────────────────────────
    st.markdown("#### 📈 Equity Curve")

    eq_df = pd.DataFrame(results["equity_curve"])
    if not eq_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=eq_df["date"], y=eq_df["equity"],
            name="Strategy", line=dict(color="#38bdf8", width=2),
            fill="tozeroy", fillcolor="rgba(56,189,248,0.08)",
        ))

        # Benchmark line (normalised to same starting capital)
        if summary.get("benchmark_return") is not None:
            import numpy as np
            bench_final = summary["initial_capital"] * (1 + summary["benchmark_return"] / 100)
            bench_vals  = pd.Series(
                index=eq_df["date"],
                data=np.linspace(summary["initial_capital"], bench_final, len(eq_df)),
            )
            fig.add_trace(go.Scatter(
                x=eq_df["date"], y=bench_vals,
                name="KSE100 (linear approx)", line=dict(color="#f59e0b", width=1.5, dash="dash"),
            ))

        fig.update_layout(
            height=400,
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
            xaxis=dict(gridcolor="#1e293b"),
            yaxis=dict(gridcolor="#1e293b", tickprefix="PKR "),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(t=30, b=30, l=80, r=20),
        )
        st.plotly_chart(fig, use_container_width=True, key="equity_curve_chart")

    # ── Trade log ─────────────────────────────────────────────────────────────
    with st.expander(f"📋 Trade Log ({len(results['trade_log'])} trades)"):
        trade_df = pd.DataFrame(results["trade_log"])
        if not trade_df.empty:
            trade_df["pnl"] = trade_df["pnl"].apply(
                lambda x: f"PKR {x:+,.0f}" if x is not None else "—"
            )
            st.dataframe(trade_df, use_container_width=True, hide_index=True)

    st.info(results.get("survivorship_bias_warning", ""))

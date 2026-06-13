"""
ui/learning_tab.py — UI component to display AI's Self-Learning and Reflection Logs.
"""

import streamlit as st
from memory.db import get_reflections
from core.portfolio import load_memory

def render_learning_tab():
    st.markdown("## 🧠 AI Self-Learning & Performance Log")
    st.markdown(
        "This section tracks how well the AI Council's recommendations are performing. "
        "Every day the daily refresh is run, the agent compares past ratings against actual "
        "closes over a **5-trading-day holding horizon**, incorporating relative benchmark filters "
        "for market-neutral HOLD positions. It then writes a self-critical reflection to learn from its successes and errors."
    )

    # ── Accuracy Metrics & Overhaul ───────────────────────────────────────────
    memory = load_memory()
    acc = memory.get("prediction_accuracy", {})
    
    total = acc.get("total", 0)
    hits = acc.get("hits", 0)
    misses = acc.get("misses", 0)
    
    buy_hits = acc.get("buy_hits", 0)
    buy_misses = acc.get("buy_misses", 0)
    buy_total = buy_hits + buy_misses
    buy_rate = (buy_hits / buy_total * 100) if buy_total > 0 else 0.0
    
    sell_hits = acc.get("sell_hits", 0)
    sell_misses = acc.get("sell_misses", 0)
    sell_total = sell_hits + sell_misses
    sell_rate = (sell_hits / sell_total * 100) if sell_total > 0 else 0.0
    
    hold_hits = acc.get("hold_hits", 0)
    hold_misses = acc.get("hold_misses", 0)
    hold_total = hold_hits + hold_misses
    hold_rate = (hold_hits / hold_total * 100) if hold_total > 0 else 0.0
    
    high_conv_hits = acc.get("high_conv_hits", 0)
    high_conv_misses = acc.get("high_conv_misses", 0)
    high_conv_total = high_conv_hits + high_conv_misses
    high_conv_rate = (high_conv_hits / high_conv_total * 100) if high_conv_total > 0 else 0.0

    # Actionable Signal Accuracy (BUY + SELL signals only)
    actionable_hits = buy_hits + sell_hits
    actionable_total = buy_total + sell_total
    actionable_rate = (actionable_hits / actionable_total * 100) if actionable_total > 0 else 0.0
    
    overall_rate = (hits / total * 100) if total > 0 else 0.0

    # CSS for premium glassmorphism card styles
    st.markdown(
        """
        <style>
        .metric-card {
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 12px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            transition: transform 0.2s ease, border-color 0.2s ease;
        }
        .metric-card:hover {
            transform: translateY(-2px);
            border-color: rgba(255, 255, 255, 0.15);
        }
        .metric-value {
            font-size: 32px;
            font-weight: 800;
            margin-bottom: 4px;
            letter-spacing: -0.5px;
        }
        .metric-title {
            font-size: 13px;
            font-weight: 600;
            color: #94a3b8;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .metric-subtext {
            font-size: 11px;
            color: #64748b;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown("### 📊 Actionable Signal Performance (5-Day Horizon)")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(
            f"""
            <div class="metric-card" style="background: linear-gradient(135deg, hsla(210, 40%, 15%, 0.7), hsla(210, 40%, 10%, 0.7));">
                <div class="metric-title">Actionable Hit Rate 🎯</div>
                <div class="metric-value" style="color: #60a5fa;">{actionable_rate:.1f}%</div>
                <div class="metric-subtext">{actionable_hits} Hits / {actionable_total} Signals</div>
                <div class="metric-subtext" style="margin-top: 4px;">BUY & SELL signals only</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        
    with col2:
        st.markdown(
            f"""
            <div class="metric-card" style="background: linear-gradient(135deg, hsla(142, 40%, 15%, 0.7), hsla(142, 40%, 10%, 0.7));">
                <div class="metric-title">BUY Signal Win Rate 📈</div>
                <div class="metric-value" style="color: #4ade80;">{buy_rate:.1f}%</div>
                <div class="metric-subtext">{buy_hits} Hits / {buy_total} Signals</div>
                <div class="metric-subtext" style="margin-top: 4px;">Gains >= 1.5% in 5 days</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        
    with col3:
        st.markdown(
            f"""
            <div class="metric-card" style="background: linear-gradient(135deg, hsla(350, 40%, 15%, 0.7), hsla(350, 40%, 10%, 0.7));">
                <div class="metric-title">SELL Signal Win Rate 📉</div>
                <div class="metric-value" style="color: #f87171;">{sell_rate:.1f}%</div>
                <div class="metric-subtext">{sell_hits} Hits / {sell_total} Signals</div>
                <div class="metric-subtext" style="margin-top: 4px;">Drops >= -1.5% in 5 days</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        
    with col4:
        st.markdown(
            f"""
            <div class="metric-card" style="background: linear-gradient(135deg, hsla(270, 40%, 15%, 0.7), hsla(270, 40%, 10%, 0.7));">
                <div class="metric-title">High-Conviction Win Rate 💎</div>
                <div class="metric-value" style="color: #c084fc;">{high_conv_rate:.1f}%</div>
                <div class="metric-subtext">{high_conv_hits} Hits / {high_conv_total} Signals</div>
                <div class="metric-subtext" style="margin-top: 4px;">Score >= 75 and rating BUY</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Secondary row for HOLD & Overall Statistics
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f"""
            <div class="metric-card" style="background: linear-gradient(135deg, hsla(40, 45%, 12%, 0.6), hsla(40, 45%, 8%, 0.6)); display: flex; justify-content: space-between; align-items: center; padding: 18px 24px;">
                <div>
                    <div class="metric-title" style="margin-bottom: 4px;">Neutral HOLD Stability ⏸️</div>
                    <div class="metric-subtext">Correct if stock is flat (abs &lt; 4.0%) or outperforming index in bear markets / not lagging in bull markets</div>
                    <div class="metric-subtext" style="margin-top: 4px;">{hold_hits} Hits / {hold_total} HOLD Signals</div>
                </div>
                <div class="metric-value" style="color: #fbbf24; font-size: 36px; margin-left: 20px;">{hold_rate:.1f}%</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with c2:
        st.markdown(
            f"""
            <div class="metric-card" style="background: linear-gradient(135deg, hsla(0, 0%, 15%, 0.6), hsla(0, 0%, 10%, 0.6)); display: flex; justify-content: space-between; align-items: center; padding: 18px 24px;">
                <div>
                    <div class="metric-title" style="margin-bottom: 4px;">Overall AI Accuracy 📊</div>
                    <div class="metric-subtext">Directional hit rate across all generated watchlist recommendations (BUY, SELL, and HOLD)</div>
                    <div class="metric-subtext" style="margin-top: 4px;">{hits} Hits / {total} Total Checked Predictions</div>
                </div>
                <div class="metric-value" style="color: #e2e8f0; font-size: 36px; margin-left: 20px;">{overall_rate:.1f}%</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("---")
    st.markdown("### 🛡️ Fundamental Framework: PSX Risk Prevention Matrix & Trend Checklist")
    st.markdown(
        "A premium structured checklist to ensure your capital is protected and your directional entries are high-probability."
    )
    
    # Render the Matrix inside a glassmorphic-styled container
    # Render the Matrix inside a glassmorphic-styled container
    st.markdown("""
    <div style="background: linear-gradient(135deg, rgba(30, 41, 59, 0.4), rgba(15, 23, 42, 0.4)); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 16px; padding: 24px; margin-bottom: 24px;">
        <h4 style="margin-top:0; color:#fbbf24; font-weight: 700;">Phase 1: Protecting Your Capital (Risk Prevention Checklist)</h4>
        <p style="font-size:13px; color:#94a3b8; margin-bottom:16px;">Before buying any stock on the PSX, analyze these four foundational areas to ensure the investment will not cost you significantly.</p>
    </div>
    """, unsafe_allow_html=True)

    st.code("""┌────────────────────────────────────────────────────────────────────────┐
│                        PSX RISK PREVENTION MATRIX                      │
├───────────────────┬────────────────────────────────────────────────────┤
│ 1. Free Float     │ Avoid stocks with < 20% free float to prevent      │
│    & Liquidity    │ getting trapped in "upper/lower locks" (no buyers).│
├───────────────────┼────────────────────────────────────────────────────┤
│ 2. P/E vs. Sector │ Avoid paying overvalued prices. Benchmark the      │
│    Average        │ trailing and forward P/E against the KSE-100.      │
├───────────────────┼────────────────────────────────────────────────────┤
│ 3. Macro & Policy │ Check if the sector depends heavily on SBP policy  │
│    Sensitivities  │ rates, IMF program reforms, or PKR devaluation.     │
├───────────────────┼────────────────────────────────────────────────────┤
│ 4. Leverage       │ Target companies with a Debt-to-Equity ratio < 1.0 │
│    & Debt Cover   │ to survive high local borrowing/interest costs.    │
└───────────────────┴────────────────────────────────────────────────────┘""", language="")

    st.markdown("""
    <div style="background: linear-gradient(135deg, rgba(30, 41, 59, 0.2), rgba(15, 23, 42, 0.2)); border: 1px solid rgba(255, 255, 255, 0.03); border-radius: 12px; padding: 20px; margin-bottom: 24px;">
        <div style="margin-bottom: 16px;">
            <strong style="color: #fbbf24; font-size: 15px;">1. Free Float and Daily Volume (Liquidity Risk)</strong><br/>
            <span style="color: #94a3b8; font-size: 12px; font-weight: 600;">The Check:</span> <span style="color: #cbd5e1; font-size: 13px;">Verify the stock’s Free Float (the percentage of shares available to the public) and average daily trading volume via the PSX Data Portal.</span><br/>
            <span style="color: #94a3b8; font-size: 12px; font-weight: 600;">Why It Matters:</span> <span style="color: #cbd5e1; font-size: 13px;">Many smaller, illiquid companies on the PSX frequently hit their daily price limits ("lower locks"). If a stock hits a lower lock, trading halts for that price floor, and you cannot sell your shares because there are zero buyers. Stick to high-volume KSE-100 index stocks to ensure easy entry and exit.</span>
        </div>
        <div style="margin-bottom: 16px; border-top: 1px solid rgba(255, 255, 255, 0.05); padding-top: 12px;">
            <strong style="color: #fbbf24; font-size: 15px;">2. Valuation Ratios (Overpayment Risk)</strong><br/>
            <span style="color: #94a3b8; font-size: 12px; font-weight: 600;">The Check:</span> <span style="color: #cbd5e1; font-size: 13px;">Look at the Price-to-Earnings (P/E) Ratio, Price-to-Book (P/B) Ratio, and Dividend Yield. Compare these metrics against the stock's historical average and its specific sector average.</span><br/>
            <span style="color: #94a3b8; font-size: 12px; font-weight: 600;">Why It Matters:</span> <span style="color: #cbd5e1; font-size: 13px;">Buying a stock at a P/E significantly higher than its sector means you are paying a premium based on speculation. Look for high dividend-yielding blue chips (e.g., in the Fertilizer or Energy sectors) which provide a structural cash cushion during market downturns.</span>
        </div>
        <div style="margin-bottom: 16px; border-top: 1px solid rgba(255, 255, 255, 0.05); padding-top: 12px;">
            <strong style="color: #fbbf24; font-size: 15px;">3. Macroeconomic and Policy Headwinds</strong><br/>
            <span style="color: #94a3b8; font-size: 12px; font-weight: 600;">The Check:</span> <span style="color: #cbd5e1; font-size: 13px;">Analyze how the company handles State Bank of Pakistan (SBP) policy rates, circular debt, and PKR devaluation.</span><br/>
            <span style="color: #94a3b8; font-size: 12px; font-weight: 600;">Why It Matters:</span><br/>
            <span style="color: #94a3b8; font-size: 12px; margin-left: 10px;">• High Interest Rates:</span> <span style="color: #cbd5e1; font-size: 13px;">Heavily leveraged sectors (like Independent Power Producers - IPPs or Textiles) suffer massive profit drops when interest rates rise.</span><br/>
            <span style="color: #94a3b8; font-size: 12px; margin-left: 10px;">• Devaluation:</span> <span style="color: #cbd5e1; font-size: 13px;">Import-dependent sectors (like Automobile assemblers or Pharma) suffer compressed margins when the rupee weakens. Look for export-oriented sectors (like IT or Software) or natural hedges (like Oil & Gas exploration) to protect against currency depreciation.</span>
        </div>
        <div style="margin-bottom: 8px; border-top: 1px solid rgba(255, 255, 255, 0.05); padding-top: 12px;">
            <strong style="color: #fbbf24; font-size: 15px;">4. Leverage and Debt-to-Equity Ratio</strong><br/>
            <span style="color: #94a3b8; font-size: 12px; font-weight: 600;">The Check:</span> <span style="color: #cbd5e1; font-size: 13px;">Read the company’s latest quarterly financial report on the PSX portal and calculate the Debt-to-Equity (D/E) Ratio and Interest Coverage Ratio.</span><br/>
            <span style="color: #94a3b8; font-size: 12px; font-weight: 600;">Why It Matters:</span> <span style="color: #cbd5e1; font-size: 13px;">Companies with a D/E ratio greater than 1.5 are heavily reliant on borrowing. In high-inflation economies, the cost of servicing this debt can rapidly wipe out net profits, pushing the stock price down.</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_bull_tab, col_bear_tab = st.columns(2)
    with col_bull_tab:
        st.markdown("""
        <div style="background: rgba(16, 185, 129, 0.03); border: 1px solid rgba(16, 185, 129, 0.1); border-radius: 12px; padding: 20px; min-height: 360px;">
            <h4 style="margin-top:0; color:#4ade80; font-weight: 700;">📈 Phase 2: Upward (Bullish) Trend Signals</h4>
            <ul style="font-size:13px; color:#cbd5e1; line-height:1.7; padding-left:20px;">
                <li><b>Institutional Buying (NCCPL Data):</b> Monitor the daily National Clearing Company of Pakistan (NCCPL) data. If Foreign Corporates, Local Mutual Funds, or Banks are consistently net buyers of a sector, the stock price will structurally trend upward.</li>
                <li><b>Breakout with High Volume:</b> Watch for the stock price breaking past a major psychological or historical resistance level accompanied by a massive spike in daily trading volume. Higher volume confirms the price move is backed by real money, not retail manipulation.</li>
                <li><b>Moving Average Golden Cross:</b> Look for the 50-day Exponential Moving Average (EMA) crossing above the 200-day EMA on a daily chart. This indicates long-term momentum has flipped positive.</li>
                <li><b>Earnings Surprises and Policy Relief:</b> Positive triggers include a surprise dividend announcement, dropping circular debt settlements, or SBP interest rate cuts that favor capital-intensive industries.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    with col_bear_tab:
        st.markdown("""
        <div style="background: rgba(239, 68, 68, 0.03); border: 1px solid rgba(239, 68, 68, 0.1); border-radius: 12px; padding: 20px; min-height: 360px;">
            <h4 style="margin-top:0; color:#f87171; font-weight: 700;">📉 Phase 2: Downward (Bearish) Trend Signals</h4>
            <ul style="font-size:13px; color:#cbd5e1; line-height:1.7; padding-left:20px;">
                <li><b>The "Lower Lock" Breakdown:</b> If a stock breaks below its key support level on high volume, or opens consecutive sessions at a lower lock, institutional distribution is happening.</li>
                <li><b>Moving Average Death Cross:</b> The 50-day EMA crossing below the 200-day EMA. This is an explicit signal to cut your losses, as it indicates a prolonged macro-downtrend.</li>
                <li><b>Relative Strength Index (RSI) Divergence:</b> If the stock price is making new highs but the RSI indicator is making lower highs (Bearish Divergence in the overbought &gt;70 region), upward momentum is exhausting and a steep correction is imminent.</li>
                <li><b>Insider/Sponsor Selling:</b> Check the "Director Notices" section on the PSX website. If company directors or majority sponsors are steadily offloading their own shares, it signals internal structural weakness or a peak in earnings.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown("---")

    # ── Reflections Log ────────────────────────────────────────────────────────
    st.markdown("### 📝 AI Self-Reflection & Critique Timeline")
    
    reflections = get_reflections(limit=100)
    if not reflections:
        st.info("No reflections logged yet. Run a **Daily Analysis** to generate the first self-learning reflections!")
        return

    for r in reflections:
        is_hit = r["is_correct"] == 1
        status_text = "🎯 HIT (CORRECT)" if is_hit else "❌ MISS (INCORRECT)"
        status_color = "#10b981" if is_hit else "#ef4444"
        bg_color = "rgba(16, 185, 129, 0.05)" if is_hit else "rgba(239, 68, 68, 0.05)"
        border_color = "rgba(16, 185, 129, 0.2)" if is_hit else "rgba(239, 68, 68, 0.2)"

        pct = r["price_change_pct"]
        pct_color = "#34d399" if pct > 0 else "#f87171"

        st.markdown(
            f"""
            <div style="background-color: {bg_color}; border: 1px solid {border_color}; padding: 18px; border-radius: 12px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div>
                        <span style="font-size: 18px; font-weight: 700; color: #f1f5f9;">{r['symbol']}</span>
                        <span style="font-size: 13px; color: #64748b; margin-left: 8px;">({r['decision_date']})</span>
                    </div>
                    <span style="background-color: {status_color}; color: #ffffff; font-size: 12px; font-weight: 800; padding: 4px 10px; border-radius: 20px;">
                        {status_text}
                    </span>
                </div>
                <div style="display: flex; gap: 20px; font-size: 14px; margin-bottom: 12px; color: #94a3b8;">
                    <div>Verdict: <strong style="color: #ffffff;">{r['verdict']}</strong></div>
                    <div>Price at Decision: <strong style="color: #ffffff;">PKR {r['price_at_decision']:,.2f}</strong></div>
                    <div>Price 5-Days Later: <strong style="color: #ffffff;">PKR {r['price_now']:,.2f}</strong></div>
                    <div>5-Day Return: <strong style="color: {pct_color};">{pct:+.2f}%</strong></div>
                </div>
                <div style="background-color: #0b0f19; border-left: 4px solid {status_color}; padding: 12px; border-radius: 4px; font-size: 14px; line-height: 1.5; color: #cbd5e1; font-style: italic;">
                    <strong>🧠 AI Critique & Lessons Learned:</strong><br>
                    "{r['reflection_notes']}"
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

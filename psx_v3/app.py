"""
app.py — PSX Advisory Agent v3
Cross-platform: Windows 10/11 + Linux
Local AI Council via Ollama + SQLite memory

Run with:
    streamlit run app.py
    OR: launch.bat (Windows) / ./launch.sh (Linux)
"""

import sys, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import streamlit as st

st.set_page_config(
    page_title="PSX Advisory Agent v3",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stApp { background-color: #0a0f1a; }
    div[data-testid="metric-container"] {
        background: #1e293b; border: 1px solid #334155;
        border-radius: 8px; padding: 12px 16px;
    }
    .stMetricLabel { color: #64748b !important; font-size: 12px !important; }
    .stDataFrame { border-radius: 8px; overflow: hidden; }
    .stButton > button {
        background: linear-gradient(135deg, #0ea5e9, #6366f1);
        color: white; border: none; border-radius: 8px; font-weight: 600;
    }
    .stButton > button:hover { opacity: 0.9; }
    hr { border-color: #1e293b; }
    .stExpander { border-color: #334155 !important; }
    .block-container { padding-top: 4.5rem !important; }
    .stTabs [data-baseweb="tab-list"], [data-testid="stTabBar"] {
        background-color: #111827 !important;
        border-radius: 12px;
        padding: 6px;
        gap: 8px;
        border: 1px solid #1f2937;
        margin-bottom: 20px;
    }
    .stTabs button[data-baseweb="tab"], [data-testid="stTab"] {
        color: #9ca3af !important;
        font-weight: 600 !important;
        font-size: 15px !important;
        background-color: transparent !important;
        border-radius: 8px !important;
        padding: 10px 20px !important;
        transition: all 0.2s ease-in-out !important;
        border: none !important;
    }
    .stTabs button[data-baseweb="tab"]:hover, [data-testid="stTab"]:hover {
        color: #ffffff !important;
        background-color: #1f2937 !important;
    }
    .stTabs button[aria-selected="true"], [data-testid="stTab"][aria-selected="true"] {
        color: #ffffff !important;
        background: linear-gradient(135deg, #3b82f6, #8b5cf6) !important;
        box-shadow: 0 4px 14px rgba(59, 130, 246, 0.3) !important;
    }
    .stSelectbox > div > div, .stTextInput > div > div,
    .stNumberInput > div > div, .stTextArea > div > div {
        background: #1e293b; border-color: #334155;
    }
</style>
""", unsafe_allow_html=True)

# ── Imports ────────────────────────────────────────────────────────────────────
from agent import run_daily_analysis, analyse_stock
from core.kmi_data import DEFAULT_WATCHLIST
from memory.db import init_db
from ui.dashboard_tab      import render_dashboard_tab
from ui.predictions_tab    import render_predictions_tab
from ui.analysis_details_tab import render_analysis_details_tab
from ui.council_tab        import render_council_tab
from ui.backtest_tab       import render_backtest_tab
from ui.weekly_review_tab  import render_weekly_review_tab
from ui.feedback_tab       import render_feedback_tab
from ui.learning_tab       import render_learning_tab

# Ensure DB is initialised
init_db()

# Start background PSX indices tracker thread by default
try:
    from core.psx_index_pipeline import start_background_index_tracker
    start_background_index_tracker()
    tracker_status = "Online"
except Exception as e:
    import logging
    logging.getLogger("app").warning(f"Could not start background PSX tracker: {e}")
    tracker_status = "Offline"

# Check statuses
import requests
from council.ollama_council import get_available_models
db_status = "Connected"

try:
    resp = requests.get("https://dps.psx.com.pk", timeout=3)
    dps_status = "Online" if resp.status_code == 200 else "Offline"
except Exception:
    dps_status = "Offline"

try:
    models = get_available_models()
    ollama_status = f"Online ({len(models)} models)" if models else "Offline"
except Exception:
    ollama_status = "Offline"

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style='text-align:center;padding:10px 0 20px'>
        <div style='font-size:40px'>📈</div>
        <div style='font-size:18px;font-weight:800;color:#f1f5f9'>PSX Advisory Agent</div>
        <div style='font-size:11px;color:#64748b'>Pakistan Stock Exchange · v3</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Status Indicators ──
    st.markdown("#### ⚙️ System Status")
    st.markdown(f"💾 **SQLite DB:** <span style='color:#4ade80;'>{db_status}</span>", unsafe_allow_html=True)
    st.markdown(f"🏛️ **DPS Portal:** <span style='color:#{'4ade80' if dps_status=='Online' else 'f87171'};'>{dps_status}</span>", unsafe_allow_html=True)
    st.markdown(f"🤖 **Ollama local:** <span style='color:#{'4ade80' if 'Online' in ollama_status else 'f87171'};'>{ollama_status}</span>", unsafe_allow_html=True)
    st.markdown(f"⏱️ **Tracker Loop:** <span style='color:#{'4ade80' if tracker_status=='Online' else 'f87171'};'>{tracker_status}</span>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### 🔍 Analysis Scope")
    analysis_scope = st.radio(
        "Select Scope:",
        ["Curated Watchlist", "Whole PSX Market (API)"],
        index=0,
        key="analysis_scope_select"
    )
    
    if analysis_scope == "Curated Watchlist":
        watchlist_text = st.text_area(
            "Stocks (one per line):",
            value="\n".join(DEFAULT_WATCHLIST),
            height=180,
            key="watchlist_input",
        )
        watchlist = [s.strip().upper() for s in watchlist_text.split("\n") if s.strip()]
    else:
        # Fall back to KMI_ALL_SHARE for full market
        from core.kmi_data import KMI_ALL_SHARE
        watchlist = KMI_ALL_SHARE

    st.markdown("---")
    include_portfolio = st.checkbox("Include portfolio stocks", value=True)
    force_refresh     = st.checkbox("Force refresh data", value=False)
    st.markdown("---")
    run_btn = st.button("🚀 Run Daily Analysis", type="primary", width="stretch")

    st.markdown("---")
    quick_sym = st.text_input("Quick analyse:", placeholder="e.g. SYS").upper().strip()
    quick_btn = st.button("Analyse →", width="stretch", key="quick_btn")

    st.markdown("---")
    st.markdown("""
    <div style='font-size:11px;color:#475569;line-height:1.7'>
    🧠 <strong>AI:</strong> Local Ollama models<br>
    ⚖️ <strong>Chairman:</strong> Claude (optional)<br>
    💾 <strong>Memory:</strong> SQLite (data/psx_memory.db)<br>
    ☽ <strong>Shariah:</strong> KMI All Share<br><br>
    ⚠️ Advisory only — not financial advice
    </div>
    """, unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────────────────────────
for k, v in [
    ("daily_results", {}),
    ("macro", {"sentiment":"neutral","summary":"Run analysis for macro data.","headlines":[]}),
    ("accuracy", {}), ("alerts", []), ("portfolio_summary", {}),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── Triggers ───────────────────────────────────────────────────────────────────
if run_btn:
    with st.spinner("🔄 Running daily analysis..."):
        out = run_daily_analysis(
            watchlist=watchlist, force_refresh=force_refresh,
            include_portfolio=include_portfolio,
        )
        st.session_state.update({
            "daily_results":    out["results"],
            "macro":            out["macro"],
            "accuracy":         out["accuracy"],
            "alerts":           out["alerts"],
            "portfolio_summary":out["portfolio"],
        })
    n = len([r for r in out["results"].values() if "error" not in r])
    st.success(f"✅ {n} stocks analysed · {len(out['alerts'])} alert(s)")

if quick_btn and quick_sym:
    with st.spinner(f"Analysing {quick_sym}..."):
        result = analyse_stock(
            quick_sym,
            macro_sentiment=st.session_state["macro"].get("sentiment","neutral"),
            force_refresh=force_refresh,
        )
        st.session_state["daily_results"][quick_sym] = result
    if "error" not in result:
        st.success(f"✅ {quick_sym} — **{result['advisory']['rating']}** | {result['advisory']['score']:.0f}/100")
    else:
        st.error(f"❌ {result['error']}")

# ── Tab Ordering ──
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
    "📊 Dashboard",
    "📈 Predictions",
    "🔍 Analysis Details",
    "🏛️ AI Board Room",
    "📅 My Money",
    "🧪 Backtester",
    "💼 Portfolio",
    "🎛️ Feedback & Calibrations",
    "🧠 AI Lessons",
])

results = st.session_state["daily_results"]

with tab1:
    if not results:
        st.info("👈 Click **🚀 Run Daily Analysis** to start.")
        st.markdown("""
### Getting started
1. Edit the watchlist in the sidebar
2. Click 🚀 Run Daily Analysis
3. Use 🏛️ AI Board Room for deep analysis of individual stocks
4. Record investments in 📅 My Money — it tracks your P&L automatically
        """)
    else:
        render_dashboard_tab(
            results, st.session_state["macro"],
            st.session_state["alerts"],
            st.session_state["portfolio_summary"],
        )

with tab2:
    if not results:
        st.info("Run the daily analysis first.")
    else:
        render_predictions_tab(results, st.session_state["accuracy"])

with tab3:
    render_analysis_details_tab(results)

with tab4:
    render_council_tab(results, st.session_state["macro"])

with tab5:
    render_weekly_review_tab(results)

with tab6:
    render_backtest_tab()

with tab7:
    from ui.portfolio_tab import render_portfolio_tab
    render_portfolio_tab()

with tab8:
    render_feedback_tab(results)

with tab9:
    render_learning_tab()

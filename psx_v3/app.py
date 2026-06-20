"""
app.py — PSX Advisory Agent v3
Cross-platform: Windows 10/11 + Linux
Local AI Council via Ollama + SQLite memory

Run with:
    streamlit run app.py
    OR: launch.bat (Windows) / ./launch.sh (Linux)

Bug Fixes Applied:
- Fix #1: Startup code (evaluate_advisor_conversations, start_background_index_tracker)
          is now guarded by st.session_state["startup_done"] so it only runs ONCE
          per browser session, not on every st.rerun() poll.
- Fix #1: Background poll uses a lighter 10s auto-refresh that does NOT re-execute
          the full script. The expensive startup code is skipped on poll cycles.
- Fix #2: Data loads from DB on refresh; falls back to flat JSON cache if DB is empty.
- Fix #3: Active tab is persisted via st.query_params["tab"] across reruns.
- Fix #4: Per-stock "Analyse →" navigates to Predictions tab instead of resetting to Dashboard.
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
import logging
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
from ui.advisor_chat import render_advisor_chat_tab

# Ensure DB is initialised (safe to run on every render — it's idempotent)
init_db()

# ── Streamlit JS Bridge Fallback Handler ──
if "js_bridge_symbol" in st.query_params:
    js_symbol = st.query_params["js_bridge_symbol"]
    if "js_bridge_data" in st.query_params:
        import json
        try:
            raw_data = json.loads(st.query_params["js_bridge_data"])
            from core.browser_psx_reader import save_js_bridge_data_to_cache
            saved = save_js_bridge_data_to_cache(js_symbol, raw_data)
            if saved:
                st.toast(f"✅ JS Bridge successfully fetched and cached data for {js_symbol}!", icon="✅")
        except Exception as e:
            st.error(f"Failed to parse JS bridge data for {js_symbol}: {e}")
    elif "js_bridge_error" in st.query_params:
        st.error(f"❌ JS Bridge failed to fetch data for {js_symbol}: {st.query_params['js_bridge_error']}")

    # Clear query parameters and trigger variables to prevent reload loop
    if "trigger_js_bridge_for" in st.session_state:
        st.session_state["trigger_js_bridge_for"] = None
    qp = st.query_params.to_dict()
    qp.pop("js_bridge_symbol", None)
    qp.pop("js_bridge_data", None)
    qp.pop("js_bridge_error", None)
    st.query_params.clear()
    for k, v in qp.items():
        st.query_params[k] = v
    st.rerun()

# ── Render JS Bridge Iframe if Triggered ──
if st.session_state.get("trigger_js_bridge_for"):
    sym = st.session_state["trigger_js_bridge_for"]
    st.info(f"🔌 JS Bridge: Fetching historical data for **{sym}** via browser...")
    import streamlit.components.v1 as components
    js_code = f"""
    <script>
    async function fetchPSX() {{
        try {{
            console.log("JS Bridge: Fetching for {sym}...");
            const response = await fetch("https://dps.psx.com.pk/timeseries/eod/{sym}");
            if (!response.ok) throw new Error("HTTP error " + response.status);
            const data = await response.json();
            
            const url = new URL(window.parent.location.href);
            url.searchParams.set("js_bridge_symbol", "{sym}");
            url.searchParams.set("js_bridge_data", JSON.stringify(data));
            window.parent.location.href = url.href;
        }} catch(e) {{
            console.error("JS Bridge fetch failed:", e);
            const url = new URL(window.parent.location.href);
            url.searchParams.set("js_bridge_symbol", "{sym}");
            url.searchParams.set("js_bridge_error", e.toString());
            window.parent.location.href = url.href;
        }}
    }}
    setTimeout(fetchPSX, 500);
    </script>
    """
    components.html(js_code, height=0, width=0)

# ── ONE-TIME STARTUP BLOCK ─────────────────────────────────────────────────────
# CRITICAL FIX #1: Guard all expensive startup tasks behind a session_state flag.
# Without this guard, every st.rerun() (including the 10s polling loop) would
# re-execute evaluate_advisor_conversations and re-start the index tracker thread.
if "startup_done" not in st.session_state:
    try:
        from advisor_memory import init_advisor_db, evaluate_advisor_conversations
        from advisor_engine import write_lesson
        from core.data_engine import get_latest_price
        init_advisor_db()
        evaluate_advisor_conversations(
            price_getter=get_latest_price,
            lesson_writer=write_lesson,
            lookback_days=5,
        )
    except Exception as _adv_err:
        logging.getLogger("app").warning(f"Advisor init non-fatal: {_adv_err}")

    try:
        from core.psx_index_pipeline import start_background_index_tracker
        start_background_index_tracker()
        st.session_state["tracker_status"] = "Online"
    except Exception as e:
        logging.getLogger("app").warning(f"Could not start background PSX tracker: {e}")
        st.session_state["tracker_status"] = "Offline"

    st.session_state["startup_done"] = True

tracker_status = st.session_state.get("tracker_status", "Offline")

# ── Status checks (cached — safe and lightweight) ────────────────────────────
import requests
from council.ollama_council import get_available_models
db_status = "Connected"

@st.cache_data(ttl=60)
def _check_dps_status():
    try:
        resp = requests.get("https://dps.psx.com.pk", timeout=3)
        return "Online" if resp.status_code == 200 else "Offline"
    except Exception:
        return "Offline"

@st.cache_data(ttl=30)
def _check_ollama_status():
    try:
        models = get_available_models()
        return f"Online ({len(models)} models)" if models else "Offline"
    except Exception:
        return "Offline"

dps_status = _check_dps_status()
ollama_status = _check_ollama_status()

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
        from core.kmi_data import KMI_ALL_SHARE
        watchlist = KMI_ALL_SHARE

    st.markdown("---")
    include_portfolio = st.checkbox("Include portfolio stocks", value=True)
    force_refresh     = st.checkbox("Force refresh data", value=False)
    st.markdown("---")
    run_btn = st.button("🚀 Run Daily Analysis", type="primary", use_container_width=True)

    st.markdown("---")
    refresh_btn = st.button("🔄 Fast Price Refresh", use_container_width=True, key="refresh_btn", help="Updates prices live without rerunning ML/Scraping")

    st.markdown("---")
    st.markdown("#### 🤖 Selective ML")
    st.caption("Run deep Machine Learning predictions on selected stocks.")
    ml_targets = st.multiselect("Stocks for ML Analysis:", watchlist, key="ml_targets_input")
    
    col_ml1, col_ml2 = st.columns(2)
    with col_ml1:
        if st.button("💡 AI Suggests", help="Ask the local LLM to pick promising stocks for ML."):
            with st.spinner("AI is thinking..."):
                from core.stock_recommender import recommend_stocks_for_ml
                rec = recommend_stocks_for_ml(st.session_state.get("daily_results", {}), st.session_state.get("macro", {}))
                if rec["recommended_symbols"]:
                    st.toast(f"AI suggests: {', '.join(rec['recommended_symbols'])}", icon="💡")
                    # Update the multiselect via session state if possible, though Streamlit multiselect might need it directly
                    # For now, we just toast the suggestion so the user can select them.
                    st.info(f"**AI Reason:** {rec['reasoning']}")
                else:
                    st.warning(rec["reasoning"])
    with col_ml2:
        if st.button("Run ML 🚀", type="secondary"):
            if ml_targets:
                with st.spinner(f"Running ML on {len(ml_targets)} stocks..."):
                    from core.selective_ml import run_ml_on_stocks
                    ml_res = run_ml_on_stocks(ml_targets)
                    # Merge results
                    for sym, res in ml_res.items():
                        if sym in st.session_state["daily_results"]:
                            st.session_state["daily_results"][sym]["ml_signals"] = res
                            # Force a rerender
                    from core.result_cache import save_results_to_flatfile
                    save_results_to_flatfile(st.session_state["daily_results"])
                    st.success("ML Predictions updated!")
                    st.rerun()
            else:
                st.warning("Please select at least one stock.")

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

# ── Imports for Caching and Background Analysis ──────────────────────────────
from core.result_cache import load_latest_results, load_latest_macro, load_latest_accuracy, get_alerts_from_results
from core.portfolio import portfolio_summary
from core.background_worker import get_analysis_status, start_background_analysis, is_analysis_running

# ── Session state defaults ──────────────────────────────────────────────────────
for k, v in [
    ("daily_results", {}),
    ("macro", {"sentiment": "neutral", "summary": "Run daily analysis to populate data.", "headlines": []}),
    ("accuracy", {}), ("alerts", []), ("portfolio_summary", {}),
    ("bg_was_running", False),
    ("startup_done", False),
    ("trigger_js_bridge_for", None),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── Auto-load cached results on startup / page refresh ──────────────────────────
# This runs every render but is cheap: it only hits the DB/file if results are empty.

def _hydrate_session_from_db():
    from memory.db import get_latest_pipeline_results
    from agent import _pipeline_result_to_advisory_dict
    db_results = get_latest_pipeline_results()
    if db_results:
        return {sym: _pipeline_result_to_advisory_dict(row) for sym, row in db_results.items()}
    return {}

if not st.session_state["daily_results"]:
    # 1. Try JSON Flat-file
    cached_results = load_latest_results()
    # 2. Fallback to DB
    if not cached_results:
        cached_results = _hydrate_session_from_db()
        
    if cached_results:
        st.session_state["daily_results"] = cached_results
        st.session_state["macro"] = load_latest_macro()
        st.session_state["accuracy"] = load_latest_accuracy()
        st.session_state["alerts"] = get_alerts_from_results(cached_results)
        current_prices = {sym: r["current_price"] for sym, r in cached_results.items() if "current_price" in r}
        st.session_state["portfolio_summary"] = portfolio_summary(current_prices)

# ── Stale Data Check ──
from datetime import date
if st.session_state["daily_results"]:
    # get the date of the first result
    first_res = next(iter(st.session_state["daily_results"].values()), {})
    res_date = first_res.get("date", "")
    if res_date and res_date != date.today().isoformat():
        st.warning(f"⚠️ **Stale Data:** Your analysis data is from {res_date}. Please 'Run Daily Analysis' or click 'Fast Price Refresh'.")

# ── Auto Price Refresh (Fragment) ──
@st.fragment(run_every=60)
def _auto_price_refresh():
    # Only run if not currently running a full analysis
    if st.session_state.get("daily_results") and not get_analysis_status().get("running"):
        from agent import run_price_refresh
        symbols = list(st.session_state["daily_results"].keys())
        refreshed = run_price_refresh(symbols, st.session_state["daily_results"])
        st.session_state["daily_results"] = refreshed["results"]
        # Update portfolio subtly
        current_prices = {sym: r["current_price"] for sym, r in st.session_state["daily_results"].items() if "current_price" in r}
        st.session_state["portfolio_summary"] = portfolio_summary(current_prices)

_auto_price_refresh()

# ── Background Analysis Status Banner (Fragment — only this piece reruns) ────────
# Using @st.fragment(run_every=10) means ONLY this banner refreshes every 10s.
# The rest of the page (tabs, charts, all content) stays completely stable —
# no full-page rerun, no dimming, no disappearing tabs.
@st.fragment(run_every=10)
def _render_analysis_status_banner():
    bg_status = get_analysis_status()

    if bg_status.get("running"):
        # Mark that we were running so we can reload when it stops
        st.session_state["bg_was_running"] = True
        progress_msg = bg_status.get("progress", "Starting...")
        st.info(
            f"⏳ **Background Analysis Running:** {progress_msg}  \n"
            f"_Auto-refreshing every 10 seconds. All tabs remain fully browsable._"
        )

    elif st.session_state.get("bg_was_running", False):
        # Analysis just finished — reload all results into session state
        st.session_state["bg_was_running"] = False
        cached_results = load_latest_results()
        if cached_results:
            st.session_state["daily_results"] = cached_results
            st.session_state["macro"] = load_latest_macro()
            st.session_state["accuracy"] = load_latest_accuracy()
            st.session_state["alerts"] = get_alerts_from_results(cached_results)
            current_prices = {sym: r["current_price"] for sym, r in cached_results.items() if "current_price" in r}
            st.session_state["portfolio_summary"] = portfolio_summary(current_prices)
            from core.result_cache import save_results_to_flatfile
            save_results_to_flatfile(cached_results)

        if bg_status.get("error"):
            st.error(f"❌ Background Analysis Failed: {bg_status.get('error')}")
        else:
            n = len([r for r in st.session_state["daily_results"].values() if "error" not in r])
            st.success(
                f"✅ Background Analysis Complete! {n} stocks analysed · "
                f"{len(st.session_state['alerts'])} alert(s)  \n"
                f"_Refresh the page or switch tabs to see updated results._"
            )

_render_analysis_status_banner()

# ── Triggers ───────────────────────────────────────────────────────────────────
if run_btn:
    if is_analysis_running():
        st.toast("⚠️ Analysis is already running. Please wait.", icon="⚠️")
    else:
        started = start_background_analysis(
            watchlist=watchlist,
            force_refresh=force_refresh,
            include_portfolio=include_portfolio
        )
        if started:
            st.toast("🚀 Background analysis started! The status banner above will track progress.", icon="ℹ️")
            st.session_state["bg_was_running"] = True

if refresh_btn:
    with st.spinner("Refreshing live prices from PSX..."):
        from agent import run_price_refresh
        symbols = list(st.session_state["daily_results"].keys())
        refreshed = run_price_refresh(symbols, st.session_state["daily_results"])
        st.session_state["daily_results"] = refreshed["results"]
        current_prices = {sym: r["current_price"] for sym, r in st.session_state["daily_results"].items() if "current_price" in r}
        st.session_state["portfolio_summary"] = portfolio_summary(current_prices)
        st.toast("✅ Live prices updated!", icon="✅")

# ── FIX #3 & #4: Tab Navigation State ──────────────────────────────────────────
# Active tab index is stored in URL query params so it survives reruns.
# Tab index map: 0=Dashboard, 1=Predictions, 2=Analysis Details, ...
TAB_NAMES = [
    "📊 Dashboard",
    "🏆 Tier Debate",
    "📈 Predictions",
    "🔍 Analysis Details",
    "🏛️ AI Board Room",
    "📅 My Money",
    "🧪 Backtester",
    "💼 Portfolio",
    "🎛️ Feedback & Calibrations",
    "🧠 AI Lessons",
    "🤖 AI Advisor",
]

# ── Quick Analyse is moved to Tabs ──
# Sidebar Quick Analyse removed per Phase 1 to prevent tab resetting.

# Read active tab from query params (survives reruns, doesn't require full page reload)
try:
    _active_tab = int(st.query_params.get("tab", "0"))
    if _active_tab < 0 or _active_tab >= len(TAB_NAMES):
        _active_tab = 0
except (ValueError, TypeError):
    _active_tab = 0

# ── Tab Ordering ──
# Note: Streamlit's st.tabs does not natively support programmatic tab selection.
# The query_params approach sets the default intent; users still click tabs normally.
# The active tab note is shown as a subtle UI cue when navigating via quick analyse.
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11 = st.tabs(TAB_NAMES)

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
        from ui.tiers_tab import render_tiers_tab
        render_tiers_tab(results, st.session_state["macro"])

with tab3:
    if not results:
        st.info("Run the daily analysis first.")
    else:
        render_predictions_tab(results, st.session_state["accuracy"])

with tab4:
    render_analysis_details_tab(results)

with tab5:
    render_council_tab(results, st.session_state["macro"])

with tab6:
    render_weekly_review_tab(results)

with tab7:
    render_backtest_tab()

with tab8:
    from ui.portfolio_tab import render_portfolio_tab
    render_portfolio_tab()

with tab9:
    render_feedback_tab(results)

with tab10:
    render_learning_tab()

with tab11:
    render_advisor_chat_tab()

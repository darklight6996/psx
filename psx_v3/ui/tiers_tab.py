"""
ui/tiers_tab.py — Streamlit Tier Debate & Macro News Tab.

Groups stocks into:
- Tier 1: Quant Screen
- Tier 2: ML Signals
- Tier 3: AI Council

Displays relevant news/broadcasts for the stock, and a separate panel for general world/macro news.
"""

import streamlit as st

def render_tiers_tab(results: dict, macro: dict):
    st.markdown("### 🏆 Tier Debate & Selection")
    
    col_main, col_macro = st.columns([2, 1])
    
    with col_main:
        st.markdown("#### 📊 Stock Tiers")
        
        # Categorize stocks
        tier1 = []
        tier2 = []
        tier3 = []
        
        for sym, r in results.items():
            if "error" in r:
                continue
            
            # Simple tiering logic for display purposes:
            # Tier 3: AI Council ran
            # Tier 2: ML signals present and significant
            # Tier 1: Base Quant
            if r.get("council_run", False):
                tier3.append(sym)
            elif r.get("ml_signals", {}).get("status") in ("ok", "trained_now", "cached"):
                tier2.append(sym)
            else:
                tier1.append(sym)
                
        # Helper to render a tier
        def render_tier(title, symbols, description):
            st.markdown(f"**{title}** — {description}")
            if not symbols:
                st.info("No stocks in this tier.")
                return
            
            for sym in symbols:
                r = results[sym]
                advisory = r.get("advisory", {})
                rating = advisory.get("rating", "HOLD")
                score = advisory.get("score", 0.0)
                color = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}.get(rating, "⚪")
                
                with st.expander(f"{color} {sym} — Score: {score:.0f}"):
                    st.write(f"**Rating:** {rating}")
                    
                    st.markdown("**Why it was selected for this tier:**")
                    if "Tier 3" in title:
                        st.write("This stock was elevated to the AI Council for an in-depth fundamental and macro debate.")
                        st.write(f"*Chairman Verdict:* {r.get('council_result', {}).get('validation_status', 'N/A')}")
                    elif "Tier 2" in title:
                        st.write("This stock was processed by the ML model due to recent anomalous price action or user request.")
                        ml_dir = r.get("ml_signals", {}).get("direction", "UNKNOWN")
                        st.write(f"*ML Predicted Direction:* {ml_dir}")
                    else:
                        st.write("This stock was screened using the foundational Quant/Technical rule engine.")
                        
                    st.markdown("**Relevant News & Broadcasts (Stock Specific):**")
                    news = r.get("news", {})
                    verified = news.get("verified_facts", [])
                    retail = news.get("retail_sentiment", [])

                    if verified:
                        for n in verified:
                            st.info(f"**Verified ({n.get('source')}):** {n.get('content')}")
                    if retail:
                        for n in retail:
                            st.write(f"💬 **Retail (X/Twitter):** {n.get('content')}")

                    # Google Search news (if available)
                    g_news = r.get("google_news", [])
                    if g_news:
                        st.markdown("**🔍 Latest Web News (Google Search):**")
                        for gn in g_news[:4]:
                            date_tag = f" `{gn['published_date']}`" if gn.get('published_date') else ""
                            url = gn.get("url", "")
                            title = gn.get("title", "No title")
                            snippet = gn.get("snippet", "")
                            src = gn.get("displayed_url", "")
                            if url:
                                st.markdown(f"📰 [{title}]({url}){date_tag}  \n_{snippet}_  \n<small>{src}</small>", unsafe_allow_html=True)
                            else:
                                st.markdown(f"📰 **{title}**{date_tag}  \n_{snippet}_")

                    if not verified and not retail and not g_news:
                        st.caption("No relevant stock-specific news currently available.")
                        
        render_tier("🥇 Tier 3: AI Council", tier3, "Stocks deeply analyzed by the multi-agent AI council.")
        render_tier("🥈 Tier 2: ML Signals", tier2, "Stocks analyzed by the predictive Machine Learning pipeline.")
        render_tier("🥉 Tier 1: Quant Screen", tier1, "Stocks evaluated purely on technical/quantitative indicators.")
        
    with col_macro:
        st.markdown("#### 🌍 World & Macro News")
        st.caption("News not tied to specific stocks but affecting the general market.")
        
        st.markdown(f"**Overall Sentiment:** {macro.get('sentiment', 'Unknown').upper()}")
        st.write(macro.get("summary", "No macro summary available."))
        
        headlines = macro.get("headlines", [])
        if headlines:
            for hl in headlines:
                st.markdown(f"- {hl}")
        else:
            st.info("No global/macro news headlines currently available.")

        # Google-powered Pakistan macro news
        st.markdown("---")
        st.markdown("**🔍 Google: Live Pakistan Macro News**")
        try:
            from core.google_search import search_macro_pakistan_news, get_quota_status
            quota = get_quota_status()
            if quota["enabled"]:
                st.caption(f"💡 Google Search: {quota['remaining']}/{quota['limit']} queries remaining today")
                macro_gnews = search_macro_pakistan_news(lookback_days=3)
                if macro_gnews:
                    for gn in macro_gnews[:6]:
                        date_tag = f" `{gn['published_date']}`" if gn.get('published_date') else ""
                        url = gn.get("url", "")
                        title = gn.get("title", "")
                        snippet = gn.get("snippet", "")
                        if url:
                            st.markdown(f"📰 [{title}]({url}){date_tag}  \n_{snippet[:140]}_", unsafe_allow_html=False)
                        else:
                            st.markdown(f"📰 **{title}**{date_tag}  \n_{snippet[:140]}_")
                else:
                    st.caption("No recent Pakistan macro news found via Google.")
            else:
                st.caption(
                    "🔑 Google Search not configured. Add `GOOGLE_SEARCH_API_KEY` and `GOOGLE_CSE_ID` "
                    "to your `.env` file to enable real-time web news."
                )
        except Exception as _gse:
            st.caption(f"Google news unavailable: {_gse}")
            
        st.markdown("---")
        st.markdown("**🐦 X / Twitter Feed (Market Sentiment):**")
        try:
            from core.x_feed import fetch_recent_tweets
            mkt_tweets = fetch_recent_tweets("#PSX OR #KSE100 -is:retweet", max_results=5)
            if mkt_tweets:
                for t in mkt_tweets:
                    st.markdown(f"💬 {t.get('text', '')[:250]}")
                    st.caption(f"👍 {t.get('likes', 0)} · 🔁 {t.get('retweets', 0)}")
            else:
                st.caption("No recent X market sentiment available.")
        except Exception as _xe:
            st.caption(f"X feed unavailable: {_xe}")

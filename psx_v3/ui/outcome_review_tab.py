"""
ui/outcome_review_tab.py — Streamlined Prediction Outcome Review.

Replaces the old per-stock drop-down submit form with a one-tap review grid.
Shows every open prediction and lets the user mark CORRECT / WRONG / SKIP
with a single button click. Results feed directly into the feedback pipeline
so the calibration engine has clean, unambiguous signal.
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime
from memory.db import get_conn


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_pending_reviews(limit: int = 30) -> list[dict]:
    """
    Pull predictions from pipeline_results that have not yet been reviewed.
    Returns newest first.
    """
    try:
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT pr.symbol, pr.run_date, pr.final_score, pr.advisory_rating,
                       pr.price_at_run,
                       COALESCE(r.user_verdict, '') AS user_verdict
                FROM pipeline_results pr
                LEFT JOIN user_outcome_reviews r
                       ON r.symbol = pr.symbol AND r.prediction_date = pr.run_date
                WHERE r.id IS NULL
                  AND pr.run_date < date('now')
                ORDER BY pr.run_date DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _mark_reviewed(symbol: str, prediction_date: str, outcome: str, note: str = ""):
    """
    Persist a review outcome.
    outcome: 'CORRECT' | 'WRONG' | 'SKIP'
    """
    try:
        with get_conn() as conn:
            # Ensure the table exists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_outcome_reviews (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol          TEXT    NOT NULL,
                    prediction_date TEXT    NOT NULL,
                    reviewed_at     TEXT    NOT NULL,
                    user_verdict    TEXT    NOT NULL,  -- CORRECT | WRONG | SKIP
                    note            TEXT    DEFAULT '',
                    UNIQUE(symbol, prediction_date)
                )
            """)
            conn.execute("""
                INSERT OR REPLACE INTO user_outcome_reviews
                    (symbol, prediction_date, reviewed_at, user_verdict, note)
                VALUES (?, ?, ?, ?, ?)
            """, (
                symbol.upper(),
                prediction_date,
                datetime.now().isoformat(),
                outcome,
                note,
            ))
    except Exception as e:
        st.error(f"Failed to save review: {e}")


def _get_review_history(limit: int = 100) -> list[dict]:
    """Recent reviewed outcomes for the accuracy chart."""
    try:
        with get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_outcome_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL, prediction_date TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL, user_verdict TEXT NOT NULL,
                    note TEXT DEFAULT '', UNIQUE(symbol, prediction_date)
                )
            """)
            rows = conn.execute("""
                SELECT r.symbol, r.prediction_date, r.user_verdict, r.note,
                       pr.advisory_rating, pr.final_score, pr.price_at_run
                FROM user_outcome_reviews r
                LEFT JOIN pipeline_results pr
                       ON pr.symbol = r.symbol AND pr.run_date = r.prediction_date
                ORDER BY r.reviewed_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_outcome_review():
    """
    Simplified 1-tap prediction outcome review.
    Call this from the Feedback & Calibrations tab or as a standalone section.
    """
    st.markdown("#### 🎯 Prediction Outcome Review")
    st.caption(
        "Quickly mark whether the system's past BUY / HOLD / SELL calls were correct. "
        "Your feedback directly trains the calibration engine."
    )

    pending = _get_pending_reviews(limit=20)

    if not pending:
        st.success("✅ All predictions reviewed! No pending items.")
        _render_accuracy_summary()
        return

    st.markdown(f"**{len(pending)} predictions awaiting your review:**")

    # Group by date for clarity
    by_date: dict[str, list] = {}
    for p in pending:
        by_date.setdefault(p["prediction_date"], []).append(p)

    for pred_date, items in sorted(by_date.items(), reverse=True):
        age = (date.today() - datetime.strptime(pred_date, "%Y-%m-%d").date()).days
        label = f"📅 {pred_date}  _(~{age} day{'s' if age != 1 else ''} ago)_"
        with st.expander(label, expanded=(age <= 7)):
            cols_header = st.columns([2, 2, 1.5, 5])
            cols_header[0].markdown("**Stock**")
            cols_header[1].markdown("**System Call**")
            cols_header[2].markdown("**Score**")
            cols_header[3].markdown("**Mark Outcome**")
            st.divider()

            for item in items:
                sym         = item["symbol"]
                rating      = item["advisory_rating"] or "?"
                score       = item.get("final_score", 0)
                price       = item.get("price_at_run", 0)
                rating_icon = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}.get(rating, "⚪")

                c1, c2, c3, c4 = st.columns([2, 2, 1.5, 5])

                c1.markdown(f"**{sym}**  \n_@ PKR {price:,.1f}_")
                c2.markdown(f"{rating_icon} **{rating}**")
                c3.markdown(f"`{score:.0f}`")

                # 3-button outcome row — each button is its own unique key
                key_base = f"review_{sym}_{pred_date}"
                btn1, btn2, btn3 = c4.columns(3)

                if btn1.button("✅ Correct", key=f"{key_base}_correct", use_container_width=True):
                    _mark_reviewed(sym, pred_date, "CORRECT")
                    st.toast(f"✅ Marked {sym} {rating} as CORRECT", icon="✅")
                    st.rerun()

                if btn2.button("❌ Wrong", key=f"{key_base}_wrong", use_container_width=True):
                    _mark_reviewed(sym, pred_date, "WRONG")
                    # Automatically log to feedback analyser so calibration can learn
                    try:
                        from memory.feedback_analyser import log_user_feedback, analyze_feedback_and_propose
                        opposite = {"BUY": "SELL", "SELL": "BUY", "HOLD": "HOLD"}.get(rating, "HOLD")
                        log_user_feedback(
                            symbol=sym,
                            system_verdict=rating,
                            user_verdict=opposite,
                            user_note=f"User-marked wrong via outcome review for {pred_date}",
                            price_at_signal=price,
                            price_now=price,
                        )
                        analyze_feedback_and_propose()
                    except Exception:
                        pass
                    st.toast(f"❌ Marked {sym} {rating} as WRONG — feedback logged", icon="❌")
                    st.rerun()

                if btn3.button("⏭ Skip", key=f"{key_base}_skip", use_container_width=True):
                    _mark_reviewed(sym, pred_date, "SKIP")
                    st.rerun()

    st.markdown("---")
    _render_accuracy_summary()


def _render_accuracy_summary():
    """Show a compact accuracy breakdown from user reviews."""
    history = _get_review_history(limit=200)
    if not history:
        st.caption("No review history yet. Start reviewing predictions above.")
        return

    df = pd.DataFrame(history)
    reviewed = df[df["user_verdict"].isin(["CORRECT", "WRONG"])]

    if reviewed.empty:
        return

    total   = len(reviewed)
    correct = (reviewed["user_verdict"] == "CORRECT").sum()
    rate    = correct / total * 100

    st.markdown("#### 📊 Your Review Accuracy Stats")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Reviewed", total)
    c2.metric("Correct Calls", int(correct))
    c3.metric("Hit Rate", f"{rate:.1f}%", delta=f"{rate - 50:.1f}% vs coin flip")

    # Per-rating breakdown
    if "advisory_rating" in reviewed.columns:
        by_rating = reviewed.groupby("advisory_rating")["user_verdict"].apply(
            lambda x: (x == "CORRECT").sum() / len(x) * 100
        ).reset_index()
        by_rating.columns = ["Rating", "Hit Rate %"]
        by_rating["Hit Rate %"] = by_rating["Hit Rate %"].round(1)
        st.dataframe(by_rating, use_container_width=True, hide_index=True)

    # Recent history table
    with st.expander("📋 Recent Reviews", expanded=False):
        cols_show = ["symbol", "prediction_date", "advisory_rating", "final_score", "user_verdict", "note"]
        cols_show = [c for c in cols_show if c in df.columns]
        st.dataframe(df[cols_show].head(50), use_container_width=True, hide_index=True)

"""
memory/db.py — Persistent SQLite memory for the PSX Advisory Agent.

Tracks:
  - Every investment made (symbol, PKR amount, date, price)
  - Every council decision (what the board decided and why)
  - Weekly P&L snapshots (value then vs now)
  - Trade history (buy/sell events with timestamps)
  - Weekly performance narrative (human-readable "your week in review")

The DB file lives at data/psx_memory.db — it survives app restarts,
reboots, and updates. Never deleted unless you explicitly remove it.
"""

import sqlite3
import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path("data/psx_memory.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS investments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    company_name    TEXT,
    pkr_invested    REAL    NOT NULL,
    shares          INTEGER NOT NULL,
    entry_price     REAL    NOT NULL,
    entry_date      TEXT    NOT NULL,
    exit_price      REAL,
    exit_date       TEXT,
    status          TEXT    DEFAULT 'OPEN',   -- OPEN / CLOSED
    notes           TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS council_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    decision_date   TEXT    NOT NULL,
    final_verdict   TEXT    NOT NULL,         -- BUY / HOLD / SELL
    final_score     REAL,
    consensus       TEXT,
    confidence      TEXT,
    bull_verdict    TEXT,
    bear_verdict    TEXT,
    shariah_verdict TEXT,
    quant_verdict   TEXT,
    local_verdicts  TEXT,                     -- JSON of ollama model outputs
    chairman_notes  TEXT,                     -- Claude's final synthesis
    price_at_decision REAL,
    macro_sentiment TEXT,
    acted_on        INTEGER DEFAULT 0,        -- 1 if user actually invested
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS weekly_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    price_then      REAL,
    price_now       REAL,
    shares_held     INTEGER,
    value_then      REAL,
    value_now       REAL,
    pnl_pkr         REAL,
    pnl_pct         REAL,
    recommendation  TEXT,                     -- HOLD / DIVEST / ADD MORE
    narrative       TEXT,                     -- human-readable explanation
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS price_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    price_date      TEXT    NOT NULL,
    close_price     REAL    NOT NULL,
    created_at      TEXT    DEFAULT (datetime('now')),
    UNIQUE(symbol, price_date)
);

CREATE TABLE IF NOT EXISTS agent_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type      TEXT    NOT NULL,         -- ANALYSIS / COUNCIL / INVEST / DIVEST / WEEKLY_REVIEW
    symbol          TEXT,
    message         TEXT    NOT NULL,
    data_json       TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decision_reflections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     INTEGER NOT NULL,
    symbol          TEXT    NOT NULL,
    decision_date   TEXT    NOT NULL,
    verdict         TEXT    NOT NULL,
    price_at_decision REAL  NOT NULL,
    price_now       REAL    NOT NULL,
    price_change_pct REAL   NOT NULL,
    is_correct      INTEGER NOT NULL,
    reflection_notes TEXT   NOT NULL,
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pipeline_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date            TEXT NOT NULL,
    run_timestamp       TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    final_verdict       TEXT NOT NULL,
    final_score         REAL,
    vote_breakdown      TEXT,        -- JSON
    ml_signals          TEXT,        -- JSON
    council_result      TEXT,        -- JSON
    risk_matrix         TEXT,        -- JSON
    shariah_status      TEXT,
    entry_exit          TEXT,        -- JSON
    sentiment           TEXT,        -- JSON
    candlestick_patterns TEXT,       -- JSON
    challenge_result    TEXT,        -- JSON
    price_at_run        REAL,
    indicators          TEXT,        -- JSON
    data_source         TEXT,
    council_run         INTEGER DEFAULT 0,
    run_duration_s      REAL,
    recommendation_created_at TEXT DEFAULT (datetime('now')),
    recommendation_expiry_at  TEXT,
    target_hit          INTEGER DEFAULT 0,
    stop_hit            INTEGER DEFAULT 0,
    outcome_status      TEXT DEFAULT 'OPEN', -- OPEN / TARGET_HIT / STOP_HIT / EXPIRED / MANUALLY_CLOSED
    UNIQUE(run_date, symbol)
);

CREATE TABLE IF NOT EXISTS prediction_audit (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,
    prediction_date     TEXT NOT NULL,
    prediction          TEXT NOT NULL,
    actual_result       TEXT,
    confidence_score    REAL,
    anomaly_triggers_fired TEXT,      -- JSON
    boardroom_recommendation TEXT,
    final_pipeline_score REAL,
    audit_date          TEXT DEFAULT (date('now')),
    failure_reason      TEXT,
    was_correct         INTEGER
);

CREATE TABLE IF NOT EXISTS trading_journal (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_date        TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    signal_date         TEXT NOT NULL,
    signal_verdict      TEXT NOT NULL,
    signal_score        REAL,
    price_at_signal     REAL,
    price_at_evaluation REAL,
    actual_move_pct     REAL,
    was_correct         INTEGER,
    deciding_signal     TEXT,
    deciding_was_right  INTEGER,
    counter_signals     TEXT,
    challenge_result    TEXT,
    post_mortem         TEXT,
    pattern_detected    TEXT,
    UNIQUE(symbol, signal_date)
);

CREATE TABLE IF NOT EXISTS user_feedback (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,
    feedback_date       TEXT NOT NULL,
    system_verdict      TEXT NOT NULL,
    user_verdict        TEXT NOT NULL,
    actual_outcome      TEXT,
    actual_move_pct     REAL,
    price_at_signal     REAL,
    price_now           REAL,
    signals_at_time     TEXT,
    user_note           TEXT,
    sector              TEXT,
    was_news_driven     INTEGER DEFAULT 0,
    news_type           TEXT,
    pattern_type        TEXT,
    reviewed            INTEGER DEFAULT 0,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS calibration_proposals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_date       TEXT NOT NULL,
    signal_name         TEXT NOT NULL,
    sector_context      TEXT,
    current_weight      REAL,
    proposed_weight     REAL,
    evidence_count      INTEGER,
    supporting_ids      TEXT,
    reasoning           TEXT,
    status              TEXT DEFAULT 'PENDING',
    approved_at         TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sentiment_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,
    sentiment_date      TEXT NOT NULL,
    composite_score     REAL,
    sentiment_label     TEXT,
    details_json        TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, sentiment_date)
);

CREATE TABLE IF NOT EXISTS psx_announcements (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT,
    announcement_date   TEXT NOT NULL,
    announcement_type   TEXT,
    headline            TEXT NOT NULL,
    details             TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_investments_symbol    ON investments(symbol);
CREATE INDEX IF NOT EXISTS idx_decisions_symbol_date ON council_decisions(symbol, decision_date);
CREATE INDEX IF NOT EXISTS idx_snapshots_date        ON weekly_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_price_history         ON price_history(symbol, price_date);
CREATE INDEX IF NOT EXISTS idx_reflections_symbol   ON decision_reflections(symbol);
CREATE INDEX IF NOT EXISTS idx_pipeline_results_date ON pipeline_results(run_date, symbol);
CREATE INDEX IF NOT EXISTS idx_trading_journal       ON trading_journal(symbol, signal_date);
CREATE INDEX IF NOT EXISTS idx_prediction_audit      ON prediction_audit(symbol);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    logger.info(f"Database ready at {DB_PATH}")
    try:
        from memory.migrations import apply_migrations
        apply_migrations()
    except Exception as e:
        logger.error(f"Failed to apply database migrations: {e}")


# ---------------------------------------------------------------------------
# Investments
# ---------------------------------------------------------------------------

def add_investment(
    symbol: str,
    company_name: str,
    pkr_invested: float,
    shares: int,
    entry_price: float,
    entry_date: Optional[str] = None,
    notes: str = "",
) -> int:
    """Record a new investment. Returns the row id."""
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO investments
              (symbol, company_name, pkr_invested, shares, entry_price, entry_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (symbol.upper(), company_name, pkr_invested, shares,
              entry_price, entry_date or date.today().isoformat(), notes))
        row_id = cur.lastrowid
    _log_event("INVEST", symbol, f"Invested PKR {pkr_invested:,.0f} in {symbol} ({shares} shares @ {entry_price})")
    return row_id


def close_investment(investment_id: int, exit_price: float, exit_date: Optional[str] = None):
    """Mark an investment as closed (sold)."""
    with get_conn() as conn:
        conn.execute("""
            UPDATE investments
            SET exit_price = ?, exit_date = ?, status = 'CLOSED'
            WHERE id = ?
        """, (exit_price, exit_date or date.today().isoformat(), investment_id))
    _log_event("DIVEST", None, f"Closed investment #{investment_id} @ PKR {exit_price}")


def get_open_investments() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM investments WHERE status = 'OPEN'
            ORDER BY entry_date DESC
        """).fetchall()
    return [dict(r) for r in rows]


def get_all_investments() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM investments ORDER BY entry_date DESC").fetchall()
    return [dict(r) for r in rows]


def get_investment_summary(current_prices: dict[str, float]) -> dict:
    """
    Calculate overall portfolio P&L from memory.

    Returns dict with total_invested, current_value, total_pnl, positions list.
    """
    positions = get_open_investments()
    total_invested = 0.0
    total_value    = 0.0
    rows = []

    for pos in positions:
        sym         = pos["symbol"]
        cost        = pos["pkr_invested"]
        shares      = pos["shares"]
        entry       = pos["entry_price"]
        curr_price  = current_prices.get(sym)

        if curr_price:
            curr_val = curr_price * shares
            pnl      = curr_val - cost
            pnl_pct  = pnl / cost * 100 if cost else 0
        else:
            curr_val = cost
            pnl      = 0.0
            pnl_pct  = 0.0

        total_invested += cost
        total_value    += curr_val

        rows.append({
            **pos,
            "current_price": curr_price,
            "current_value": round(curr_val, 2),
            "pnl":           round(pnl, 2),
            "pnl_pct":       round(pnl_pct, 2),
        })

    closed = [i for i in get_all_investments() if i["status"] == "CLOSED"]
    realised_pnl = sum(
        (i["exit_price"] - i["entry_price"]) * i["shares"]
        for i in closed if i["exit_price"]
    )

    return {
        "positions":       rows,
        "total_invested":  round(total_invested, 2),
        "current_value":   round(total_value, 2),
        "unrealised_pnl":  round(total_value - total_invested, 2),
        "realised_pnl":    round(realised_pnl, 2),
        "total_pnl":       round(total_value - total_invested + realised_pnl, 2),
        "total_pnl_pct":   round((total_value - total_invested) / total_invested * 100, 2)
                           if total_invested > 0 else 0,
    }


# ---------------------------------------------------------------------------
# Council decisions
# ---------------------------------------------------------------------------

def save_council_decision(
    symbol: str,
    verdict: str,
    score: float,
    consensus: str,
    confidence: str,
    analyst_verdicts: dict,        # {"bull": "BUY", "bear": "HOLD", ...}
    local_verdicts: dict,          # {"qwen": {...}, "deepseek": {...}, ...}
    chairman_notes: str,
    price: float,
    macro_sentiment: str,
    consensus_strength: Optional[int] = None,
    was_filtered: bool = False,
) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO council_decisions
              (symbol, decision_date, final_verdict, final_score, consensus, confidence,
               bull_verdict, bear_verdict, shariah_verdict, quant_verdict,
               local_verdicts, chairman_notes, price_at_decision, macro_sentiment,
               consensus_strength, was_filtered)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol.upper(), date.today().isoformat(),
            verdict, score, consensus, confidence,
            analyst_verdicts.get("bull"),
            analyst_verdicts.get("bear"),
            analyst_verdicts.get("shariah"),
            analyst_verdicts.get("quant"),
            json.dumps(local_verdicts),
            chairman_notes, price, macro_sentiment,
            consensus_strength, 1 if was_filtered else 0,
        ))
        row_id = cur.lastrowid
    _log_event("COUNCIL", symbol, f"Council decided {verdict} (score {score}) for {symbol}")
    return row_id


def get_decision_history(symbol: Optional[str] = None, limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        if symbol:
            rows = conn.execute("""
                SELECT * FROM council_decisions WHERE symbol = ?
                ORDER BY decision_date DESC LIMIT ?
            """, (symbol.upper(), limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM council_decisions
                ORDER BY decision_date DESC LIMIT ?
            """, (limit,)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("local_verdicts"):
            try:
                d["local_verdicts"] = json.loads(d["local_verdicts"])
            except Exception:
                pass
        result.append(d)
    return result


def get_last_decision(symbol: str) -> Optional[dict]:
    rows = get_decision_history(symbol, limit=1)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Weekly snapshots
# ---------------------------------------------------------------------------

def save_weekly_snapshot(
    symbol: str,
    price_then: float,
    price_now: float,
    shares: int,
    recommendation: str,
    narrative: str,
):
    value_then = price_then * shares
    value_now  = price_now  * shares
    pnl_pkr    = value_now - value_then
    pnl_pct    = pnl_pkr / value_then * 100 if value_then else 0

    with get_conn() as conn:
        conn.execute("""
            INSERT INTO weekly_snapshots
              (snapshot_date, symbol, price_then, price_now, shares_held,
               value_then, value_now, pnl_pkr, pnl_pct, recommendation, narrative)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            date.today().isoformat(), symbol, price_then, price_now, shares,
            round(value_then, 2), round(value_now, 2),
            round(pnl_pkr, 2), round(pnl_pct, 2),
            recommendation, narrative,
        ))


def get_weekly_history(symbol: Optional[str] = None, weeks: int = 12) -> list[dict]:
    cutoff = (date.today() - timedelta(weeks=weeks)).isoformat()
    with get_conn() as conn:
        if symbol:
            rows = conn.execute("""
                SELECT * FROM weekly_snapshots
                WHERE symbol = ? AND snapshot_date >= ?
                ORDER BY snapshot_date DESC
            """, (symbol.upper(), cutoff)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM weekly_snapshots
                WHERE snapshot_date >= ?
                ORDER BY snapshot_date DESC
            """, (cutoff,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Price history
# ---------------------------------------------------------------------------

def record_price(symbol: str, price_date: str, close_price: float):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO price_history (symbol, price_date, close_price)
            VALUES (?, ?, ?)
        """, (symbol.upper(), price_date, close_price))


def get_price_history_db(symbol: str, days: int = 90) -> list[dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM price_history
            WHERE symbol = ? AND price_date >= ?
            ORDER BY price_date ASC
        """, (symbol.upper(), cutoff)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Agent log
# ---------------------------------------------------------------------------

def _log_event(event_type: str, symbol: Optional[str], message: str, data: dict = None):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO agent_log (event_type, symbol, message, data_json)
            VALUES (?, ?, ?, ?)
        """, (event_type, symbol, message, json.dumps(data) if data else None))


def get_agent_log(limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM agent_log ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Weekly performance review generator
# ---------------------------------------------------------------------------

def generate_weekly_review(current_prices: dict[str, float]) -> dict:
    """
    Build a weekly performance report comparing entry price to today.

    Returns a dict with per-position narratives and a portfolio summary.
    """
    positions    = get_open_investments()
    narratives   = []
    total_cost   = 0.0
    total_now    = 0.0
    winners      = []
    losers       = []

    for pos in positions:
        sym        = pos["symbol"]
        cost       = pos["pkr_invested"]
        shares     = pos["shares"]
        entry      = pos["entry_price"]
        entry_date = pos["entry_date"]
        curr       = current_prices.get(sym)

        if not curr:
            continue

        curr_val = curr * shares
        pnl      = curr_val - cost
        pnl_pct  = pnl / cost * 100 if cost else 0

        total_cost += cost
        total_now  += curr_val

        # How many weeks held
        try:
            weeks_held = (date.today() - date.fromisoformat(entry_date)).days // 7
        except Exception:
            weeks_held = 0

        if pnl_pct >= 5:
            rec = "CONSIDER PARTIAL DIVEST"
            signal = "📈 Strong gain"
        elif pnl_pct >= 2:
            rec = "HOLD"
            signal = "📈 Positive"
        elif pnl_pct >= -2:
            rec = "HOLD"
            signal = "➡️ Flat"
        elif pnl_pct >= -8:
            rec = "WATCH — approaching stop"
            signal = "📉 Under pressure"
        else:
            rec = "⚠️ REVIEW — stop loss territory"
            signal = "🔴 Significant loss"

        narrative = (
            f"{sym}: You invested PKR {cost:,.0f} ({weeks_held}w ago). "
            f"Now worth PKR {curr_val:,.2f} ({pnl_pct:+.1f}%). "
            f"{signal}. Recommendation: {rec}."
        )

        narratives.append({
            "symbol":     sym,
            "invested":   round(cost, 2),
            "now_value":  round(curr_val, 2),
            "pnl_pkr":    round(pnl, 2),
            "pnl_pct":    round(pnl_pct, 2),
            "weeks_held": weeks_held,
            "recommendation": rec,
            "narrative":  narrative,
            "signal":     signal,
        })

        save_weekly_snapshot(sym, entry, curr, shares, rec, narrative)

        if pnl_pct > 0:
            winners.append(sym)
        else:
            losers.append(sym)

    total_pnl     = total_now - total_cost
    total_pnl_pct = total_pnl / total_cost * 100 if total_cost > 0 else 0

    portfolio_narrative = (
        f"Portfolio summary: You have PKR {total_cost:,.0f} invested across "
        f"{len(positions)} positions. Current value: PKR {total_now:,.2f} "
        f"({total_pnl_pct:+.1f}% overall). "
        f"Winners this week: {', '.join(winners) if winners else 'none'}. "
        f"Under pressure: {', '.join(losers) if losers else 'none'}."
    )

    _log_event("WEEKLY_REVIEW", None, portfolio_narrative)

    return {
        "date":                date.today().isoformat(),
        "positions":           narratives,
        "total_invested":      round(total_cost, 2),
        "total_current_value": round(total_now,  2),
        "total_pnl_pkr":       round(total_pnl,  2),
        "total_pnl_pct":       round(total_pnl_pct, 2),
        "portfolio_narrative": portfolio_narrative,
        "winners":             winners,
        "losers":              losers,
    }


# ---------------------------------------------------------------------------
# Decision Reflections & Self-Learning
# ---------------------------------------------------------------------------

def save_reflection(
    decision_id: int,
    symbol: str,
    decision_date: str,
    verdict: str,
    price_at_decision: float,
    price_now: float,
    price_change_pct: float,
    is_correct: int,
    reflection_notes: str,
) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO decision_reflections
              (decision_id, symbol, decision_date, verdict,
               price_at_decision, price_now, price_change_pct, is_correct, reflection_notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            decision_id, symbol.upper(), decision_date, verdict,
            price_at_decision, price_now, price_change_pct, is_correct, reflection_notes
        ))
        row_id = cur.lastrowid
    _log_event("ANALYSIS", symbol, f"AI Reflection logged: {'HIT' if is_correct else 'MISS'} for {symbol} ({verdict})")
    return row_id


def get_reflections(symbol: Optional[str] = None, limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        if symbol:
            rows = conn.execute("""
                SELECT * FROM decision_reflections WHERE symbol = ?
                ORDER BY decision_date DESC LIMIT ?
            """, (symbol.upper(), limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM decision_reflections
                ORDER BY decision_date DESC LIMIT ?
            """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def calculate_tiered_accuracy(lookback_days: int = 30) -> dict:
    """
    Overhauls the accuracy tracking by calculating:
    - directional_accuracy_pct: overall Hit Rate
    - magnitude_accuracy_pct: BUY signals that gained >2%
    - false_signal_rate_pct: BUY signals that fell >5%
    - abstention_rate_pct: % of signals filtered or decided as HOLD
    - expected_value: profit/loss expectation per signal
    - by_analyst_weights: breakdown of accuracy by individual analyst
    """
    cutoff_date = (date.today() - timedelta(days=lookback_days)).isoformat()
    
    with get_conn() as conn:
        # 1. Reflections
        reflections = conn.execute("""
            SELECT verdict, price_change_pct, is_correct
            FROM decision_reflections
            WHERE decision_date >= ?
        """, (cutoff_date,)).fetchall()
        
        total_refs = len(reflections)
        correct_refs = sum(1 for r in reflections if r["is_correct"] == 1)
        directional_accuracy = (correct_refs / total_refs * 100) if total_refs > 0 else 0.0
        
        # 2. BUY signals magnitude
        buy_signals = [r for r in reflections if r["verdict"] == "BUY"]
        total_buys = len(buy_signals)
        magnitude_correct = sum(1 for r in buy_signals if r["price_change_pct"] >= 2.0)
        magnitude_accuracy = (magnitude_correct / total_buys * 100) if total_buys > 0 else 0.0
        
        # 3. False BUY signal rate
        false_buys = sum(1 for r in buy_signals if r["price_change_pct"] <= -5.0)
        false_signal_rate = (false_buys / total_buys * 100) if total_buys > 0 else 0.0
        
        # 4. Abstention rate
        decisions = conn.execute("""
            SELECT final_verdict, was_filtered
            FROM council_decisions
            WHERE decision_date >= ?
        """, (cutoff_date,)).fetchall()
        
        total_decisions = len(decisions)
        filtered_decisions = sum(1 for d in decisions if d["was_filtered"] == 1 or d["final_verdict"] == "HOLD")
        abstention_rate = (filtered_decisions / total_decisions * 100) if total_decisions > 0 else 0.0
        
        # 5. Expected value
        gains = [r["price_change_pct"] for r in reflections if r["price_change_pct"] > 0]
        losses = [abs(r["price_change_pct"]) for r in reflections if r["price_change_pct"] < 0]
        
        avg_gain = sum(gains) / len(gains) if gains else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        
        win_rate = correct_refs / total_refs if total_refs > 0 else 0.0
        loss_rate = 1.0 - win_rate
        
        expected_value = (win_rate * avg_gain) - (loss_rate * avg_loss)
        
        # 6. Individual Analyst Accuracy
        analysts_perf = conn.execute("""
            SELECT analyst_role, was_correct
            FROM analyst_prediction_log
            WHERE evaluated_at IS NOT NULL AND decision_date >= ?
        """, (cutoff_date,)).fetchall()
        
        by_analyst = {}
        for row in analysts_perf:
            role = row["analyst_role"]
            is_ok = row["was_correct"]
            if role not in by_analyst:
                by_analyst[role] = {"correct": 0, "total": 0}
            by_analyst[role]["total"] += 1
            if is_ok == 1:
                by_analyst[role]["correct"] += 1
                
        by_analyst_weights = {}
        for role, stats in by_analyst.items():
            by_analyst_weights[role] = round((stats["correct"] / stats["total"] * 100), 1) if stats["total"] > 0 else 0.0
            
    return {
        "directional_accuracy_pct": round(directional_accuracy, 1),
        "magnitude_accuracy_pct": round(magnitude_accuracy, 1),
        "false_signal_rate_pct": round(false_signal_rate, 1),
        "abstention_rate_pct": round(abstention_rate, 1),
        "expected_value": round(expected_value, 2),
        "by_analyst_weights": by_analyst_weights,
        "total_reflections": total_refs
    }


# ---------------------------------------------------------------------------
# Signal Quality Stats (for Prediction Quality Tracker UI)
# ---------------------------------------------------------------------------

def get_signal_quality_stats(days: int = 30) -> dict:
    """
    Aggregate signal quality metrics over the last `days` days.

    Returns dict with:
      - total_signals: total council decisions
      - buy_count / hold_count / sell_count: breakdown
      - directional_hit_rate: % of reflections that were correct
      - avg_buy_gain_pct: average price change on BUY signals
      - avg_sell_loss_pct: average price change on SELL signals
      - current_streak: positive = consecutive hits, negative = consecutive misses
      - total_reflections: number of evaluated signals
    """
    cutoff_date = (date.today() - timedelta(days=days)).isoformat()

    with get_conn() as conn:
        # Signal counts
        decisions = conn.execute("""
            SELECT final_verdict FROM council_decisions
            WHERE decision_date >= ?
        """, (cutoff_date,)).fetchall()

        total_signals = len(decisions)
        buy_count = sum(1 for d in decisions if d["final_verdict"] == "BUY")
        hold_count = sum(1 for d in decisions if d["final_verdict"] == "HOLD")
        sell_count = sum(1 for d in decisions if d["final_verdict"] == "SELL")

        # Reflection accuracy
        reflections = conn.execute("""
            SELECT verdict, price_change_pct, is_correct
            FROM decision_reflections
            WHERE decision_date >= ?
            ORDER BY decision_date ASC
        """, (cutoff_date,)).fetchall()

        total_refs = len(reflections)
        correct_refs = sum(1 for r in reflections if r["is_correct"] == 1)
        hit_rate = (correct_refs / total_refs * 100) if total_refs > 0 else 0.0

        # Average gains/losses by verdict
        buy_changes = [r["price_change_pct"] for r in reflections if r["verdict"] == "BUY" and r["price_change_pct"] is not None]
        sell_changes = [r["price_change_pct"] for r in reflections if r["verdict"] == "SELL" and r["price_change_pct"] is not None]

        avg_buy_gain = sum(buy_changes) / len(buy_changes) if buy_changes else 0.0
        avg_sell_loss = sum(sell_changes) / len(sell_changes) if sell_changes else 0.0

        # Current streak (positive = hits, negative = misses)
        streak = 0
        if reflections:
            last_correct = reflections[-1]["is_correct"]
            for r in reversed(reflections):
                if r["is_correct"] == last_correct:
                    streak += 1
                else:
                    break
            if not last_correct:
                streak = -streak

    return {
        "total_signals": total_signals,
        "buy_count": buy_count,
        "hold_count": hold_count,
        "sell_count": sell_count,
        "directional_hit_rate": round(hit_rate, 1),
        "avg_buy_gain_pct": round(avg_buy_gain, 2),
        "avg_sell_loss_pct": round(avg_sell_loss, 2),
        "current_streak": streak,
        "total_reflections": total_refs,
        "lookback_days": days,
    }


# ---------------------------------------------------------------------------
# Pipeline Results Helpers
# ---------------------------------------------------------------------------

def save_pipeline_result(res: dict):
    """Save a single stock pipeline result to the database."""
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO pipeline_results (
                run_date, run_timestamp, symbol, final_verdict, final_score,
                vote_breakdown, ml_signals, council_result, risk_matrix,
                shariah_status, entry_exit, sentiment, candlestick_patterns,
                challenge_result, price_at_run, indicators, data_source,
                council_run, run_duration_s, recommendation_expiry_at,
                target_hit, stop_hit, outcome_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            res["run_date"], res["run_timestamp"], res["symbol"].upper(),
            res["final_verdict"], res.get("final_score"),
            json.dumps(res.get("vote_breakdown")),
            json.dumps(res.get("ml_signals")),
            json.dumps(res.get("council_result")),
            json.dumps(res.get("risk_matrix")),
            res.get("shariah_status"),
            json.dumps(res.get("entry_exit")),
            json.dumps(res.get("sentiment")),
            json.dumps(res.get("candlestick_patterns")),
            json.dumps(res.get("challenge_result")),
            res.get("price_at_run"),
            json.dumps(res.get("indicators")),
            res.get("data_source"),
            res.get("council_run", 0),
            res.get("run_duration_s", 0.0),
            res.get("recommendation_expiry_at"),
            res.get("target_hit", 0),
            res.get("stop_hit", 0),
            res.get("outcome_status", "OPEN")
        ))


def get_latest_pipeline_results() -> dict[str, dict]:
    """Retrieve the most recent pipeline result for every symbol."""
    with get_conn() as conn:
        # Find the latest run_date
        latest_date_row = conn.execute("SELECT MAX(run_date) as max_d FROM pipeline_results").fetchone()
        latest_date = latest_date_row["max_d"] if latest_date_row else None
        
        if not latest_date:
            return {}
            
        rows = conn.execute("""
            SELECT * FROM pipeline_results WHERE run_date = ?
        """, (latest_date,)).fetchall()
        
    results = {}
    for r in rows:
        d = dict(r)
        # Parse JSON fields
        for field in ["vote_breakdown", "ml_signals", "council_result", "risk_matrix",
                      "entry_exit", "sentiment", "candlestick_patterns", "challenge_result",
                      "indicators"]:
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except Exception:
                    d[field] = {}
        results[d["symbol"]] = d
    return results


def get_pipeline_run_summary() -> dict:
    """Get metadata summary of the latest pipeline execution."""
    with get_conn() as conn:
        latest_date_row = conn.execute("SELECT MAX(run_date) as max_d FROM pipeline_results").fetchone()
        latest_date = latest_date_row["max_d"] if latest_date_row else None
        
        if not latest_date:
            return {"date": "None", "total_screened": 0, "buy": 0, "hold": 0, "sell": 0, "wait": 0, "duration": 0}
            
        summary = conn.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN final_verdict = 'BUY' THEN 1 ELSE 0 END) as buys,
                SUM(CASE WHEN final_verdict = 'HOLD' THEN 1 ELSE 0 END) as holds,
                SUM(CASE WHEN final_verdict = 'SELL' THEN 1 ELSE 0 END) as sells,
                SUM(CASE WHEN final_verdict = 'WAIT' THEN 1 ELSE 0 END) as waits,
                MAX(run_duration_s) as max_dur,
                MAX(run_timestamp) as ts
            FROM pipeline_results
            WHERE run_date = ?
        """, (latest_date,)).fetchone()
        
    return {
        "date": latest_date,
        "timestamp": summary["ts"],
        "total_screened": summary["total"],
        "buy": summary["buys"],
        "hold": summary["holds"],
        "sell": summary["sells"],
        "wait": summary["waits"],
        "duration": summary["max_dur"]
    }


# Auto-init on import
init_db()


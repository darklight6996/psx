"""
advisor_memory.py — Persistent memory layer for the PSX V4 AI Advisor.

Stores every conversation turn, structured recommendations, outcomes, and
self-generated lessons. Completely independent of V3 — only depends on sqlite3.

DB tables created here:
  - advisor_conversations : full turn-by-turn log with outcome tracking
  - advisor_lessons        : distilled lessons indexed by symbol and topic

The evaluate_advisor_conversations() function is called on app startup
(same pattern as V3's evaluate_predictions) and automatically marks outcomes
and generates lessons for conversations older than 5 days.
"""

import sqlite3
import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("advisor_memory")

DB_PATH = Path("data/psx_memory.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

ADVISOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS advisor_conversations (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              TEXT    NOT NULL,
    turn_index              INTEGER NOT NULL,
    conversation_date       TEXT    NOT NULL,
    user_message            TEXT    NOT NULL,
    advisor_response        TEXT    NOT NULL,
    symbols_discussed       TEXT    DEFAULT '[]',   -- JSON list of tickers
    strategy_mode           TEXT    DEFAULT 'swing', -- day / swing / longterm
    action_recommended      TEXT,                   -- BUY/HOLD/SELL/WAIT/DISCUSS/null
    structured_package      TEXT    DEFAULT '{}',   -- JSON recommendation package
    specialists_consulted   TEXT    DEFAULT '[]',   -- JSON list
    tools_invoked           TEXT    DEFAULT '[]',   -- JSON list
    price_at_recommendation REAL,                   -- primary symbol price at time
    primary_symbol          TEXT,
    outcome_price           REAL,
    outcome_date            TEXT,
    outcome_correct         INTEGER,                -- 1/0/NULL
    lesson_learned          TEXT,
    created_at              TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS advisor_lessons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT,                           -- NULL means general/market lesson
    topic           TEXT    NOT NULL,               -- 'momentum', 'shariah', 'macro', etc.
    lesson          TEXT    NOT NULL,
    conversation_id INTEGER,
    lesson_date     TEXT    NOT NULL,
    relevance_score REAL    DEFAULT 1.0,            -- decays over time, boost on reuse
    times_retrieved INTEGER DEFAULT 0,
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_adv_conv_session   ON advisor_conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_adv_conv_date      ON advisor_conversations(conversation_date);
CREATE INDEX IF NOT EXISTS idx_adv_conv_symbol    ON advisor_conversations(primary_symbol);
CREATE INDEX IF NOT EXISTS idx_adv_lessons_symbol ON advisor_lessons(symbol);
CREATE INDEX IF NOT EXISTS idx_adv_lessons_topic  ON advisor_lessons(topic);
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_advisor_db():
    """Create advisor tables if they don't exist. Safe to call on every startup."""
    with _get_conn() as conn:
        conn.executescript(ADVISOR_SCHEMA)
    logger.info("Advisor memory tables ready.")


# ---------------------------------------------------------------------------
# Save a conversation turn
# ---------------------------------------------------------------------------

def save_conversation_turn(
    session_id: str,
    turn_index: int,
    user_message: str,
    advisor_response: str,
    symbols_discussed: list[str] = None,
    strategy_mode: str = "swing",
    action_recommended: Optional[str] = None,
    structured_package: dict = None,
    specialists_consulted: list[str] = None,
    tools_invoked: list[str] = None,
    price_at_recommendation: Optional[float] = None,
    primary_symbol: Optional[str] = None,
) -> int:
    """
    Persist one conversation turn. Returns the row id.
    Call this after every advisor response.
    """
    today = date.today().isoformat()
    with _get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO advisor_conversations (
                session_id, turn_index, conversation_date,
                user_message, advisor_response,
                symbols_discussed, strategy_mode,
                action_recommended, structured_package,
                specialists_consulted, tools_invoked,
                price_at_recommendation, primary_symbol
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id, turn_index, today,
            user_message, advisor_response,
            json.dumps(symbols_discussed or []),
            strategy_mode,
            action_recommended,
            json.dumps(structured_package or {}),
            json.dumps(specialists_consulted or []),
            json.dumps(tools_invoked or []),
            price_at_recommendation,
            primary_symbol.upper() if primary_symbol else None,
        ))
        return cur.lastrowid


# ---------------------------------------------------------------------------
# Retrieve conversation history for a session
# ---------------------------------------------------------------------------

def get_session_history(session_id: str, max_turns: int = 10) -> list[dict]:
    """
    Return the last N turns for a session, ordered oldest-first.
    Used to build the conversation context for the next Ollama call.
    """
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT user_message, advisor_response, action_recommended,
                   structured_package, symbols_discussed, turn_index
            FROM advisor_conversations
            WHERE session_id = ?
            ORDER BY turn_index DESC
            LIMIT ?
        """, (session_id, max_turns)).fetchall()
    return [dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Retrieve relevant lessons for a symbol / topic
# ---------------------------------------------------------------------------

def get_relevant_lessons(
    symbol: Optional[str] = None,
    topic: Optional[str] = None,
    limit: int = 3,
) -> list[dict]:
    """
    Retrieve the most relevant past lessons to inject into the advisor's
    system prompt. Bumps relevance_score + times_retrieved on retrieval.

    Priority order:
      1. Symbol-specific lessons
      2. Topic-specific lessons
      3. General lessons (symbol IS NULL)
    """
    with _get_conn() as conn:
        if symbol and topic:
            rows = conn.execute("""
                SELECT * FROM advisor_lessons
                WHERE (symbol = ? OR symbol IS NULL) AND topic = ?
                ORDER BY relevance_score DESC, lesson_date DESC
                LIMIT ?
            """, (symbol.upper(), topic, limit)).fetchall()
        elif symbol:
            rows = conn.execute("""
                SELECT * FROM advisor_lessons
                WHERE symbol = ? OR symbol IS NULL
                ORDER BY relevance_score DESC, lesson_date DESC
                LIMIT ?
            """, (symbol.upper(), limit)).fetchall()
        elif topic:
            rows = conn.execute("""
                SELECT * FROM advisor_lessons
                WHERE topic = ? OR symbol IS NULL
                ORDER BY relevance_score DESC, lesson_date DESC
                LIMIT ?
            """, (topic, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM advisor_lessons
                ORDER BY relevance_score DESC, lesson_date DESC
                LIMIT ?
            """, (limit,)).fetchall()

        results = [dict(r) for r in rows]

        # Bump retrieval count
        for r in results:
            conn.execute("""
                UPDATE advisor_lessons
                SET times_retrieved = times_retrieved + 1,
                    relevance_score = MIN(relevance_score * 1.05, 2.0)
                WHERE id = ?
            """, (r["id"],))

    return results


def format_lessons_for_prompt(lessons: list[dict]) -> str:
    """Format lessons into a concise block for system prompt injection."""
    if not lessons:
        return ""
    lines = ["LESSONS FROM PAST CONVERSATIONS:"]
    for l in lessons:
        sym = l.get("symbol") or "General"
        dt = (l.get("lesson_date") or "")[:10]
        lines.append(f"- {sym} ({dt}): {l['lesson']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Save a lesson
# ---------------------------------------------------------------------------

def save_lesson(
    lesson: str,
    symbol: Optional[str] = None,
    topic: str = "general",
    conversation_id: Optional[int] = None,
) -> int:
    today = date.today().isoformat()
    with _get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO advisor_lessons (symbol, topic, lesson, conversation_id, lesson_date)
            VALUES (?, ?, ?, ?, ?)
        """, (
            symbol.upper() if symbol else None,
            topic, lesson, conversation_id, today
        ))
        return cur.lastrowid


# ---------------------------------------------------------------------------
# Outcome evaluation (called on startup, same pattern as evaluate_predictions)
# ---------------------------------------------------------------------------

def evaluate_advisor_conversations(
    price_getter=None,
    lesson_writer=None,
    lookback_days: int = 5,
) -> dict:
    """
    Find conversations older than lookback_days with a concrete action
    (BUY/HOLD/SELL/WAIT) that haven't been evaluated yet.

    For each:
      1. Fetch current price via price_getter(symbol) -> float
      2. Mark outcome_correct (1/0)
      3. Call lesson_writer(symbol, action, price_then, price_now) -> str
         to generate a one-sentence lesson via Ollama
      4. Store lesson in advisor_lessons

    Args:
        price_getter:  callable(symbol: str) -> float | None
        lesson_writer: callable(symbol, action, price_then, price_now, 
                                advisor_response) -> str | None
        lookback_days: minimum age of conversation before evaluating

    Returns summary dict.
    """
    cutoff_date = (date.today() - timedelta(days=lookback_days)).isoformat()
    today_str = date.today().isoformat()

    with _get_conn() as conn:
        pending = conn.execute("""
            SELECT id, primary_symbol, action_recommended,
                   price_at_recommendation, advisor_response, conversation_date,
                   structured_package
            FROM advisor_conversations
            WHERE action_recommended IN ('BUY', 'SELL', 'HOLD', 'WAIT')
              AND outcome_correct IS NULL
              AND price_at_recommendation IS NOT NULL
              AND primary_symbol IS NOT NULL
              AND conversation_date <= ?
        """, (cutoff_date,)).fetchall()

    evaluated = 0
    lessons_written = 0

    for row in pending:
        row = dict(row)
        symbol = row["primary_symbol"]
        action = row["action_recommended"]
        price_then = row["price_at_recommendation"]

        # Get current price
        current_price = None
        if price_getter:
            try:
                current_price = price_getter(symbol)
            except Exception:
                pass

        if current_price is None or price_then is None or price_then <= 0:
            continue

        move_pct = ((current_price - price_then) / price_then) * 100

        # Determine correctness
        if action == "BUY":
            correct = 1 if move_pct > 1.0 else 0
        elif action == "SELL":
            correct = 1 if move_pct < -1.0 else 0
        elif action == "WAIT":
            # WAIT is correct if the stock didn't make a big move the advisor missed
            correct = 1 if abs(move_pct) < 5.0 else 0
        else:  # HOLD
            correct = 1 if abs(move_pct) < 3.0 else 0

        # Generate lesson
        lesson_text = None
        if lesson_writer:
            try:
                lesson_text = lesson_writer(
                    symbol=symbol,
                    action=action,
                    price_then=price_then,
                    price_now=current_price,
                    move_pct=move_pct,
                    was_correct=bool(correct),
                    advisor_response=row["advisor_response"],
                )
            except Exception as e:
                logger.warning(f"Lesson writer failed for {symbol}: {e}")

        if not lesson_text:
            if correct:
                lesson_text = (
                    f"{action} on {symbol} was correct. "
                    f"Stock moved {move_pct:+.1f}% over {lookback_days} days."
                )
            else:
                lesson_text = (
                    f"{action} on {symbol} was wrong. "
                    f"Stock moved {move_pct:+.1f}% — expected "
                    f"{'up' if action == 'BUY' else 'down' if action == 'SELL' else 'flat'}."
                )

        # Infer topic from structured package
        topic = "general"
        try:
            pkg = json.loads(row.get("structured_package") or "{}")
            strategy = pkg.get("strategy", "").lower()
            if strategy:
                topic = strategy
        except Exception:
            pass

        with _get_conn() as conn:
            conn.execute("""
                UPDATE advisor_conversations
                SET outcome_price = ?, outcome_date = ?,
                    outcome_correct = ?, lesson_learned = ?
                WHERE id = ?
            """, (current_price, today_str, correct, lesson_text, row["id"]))

        # Save lesson to lessons table
        save_lesson(
            lesson=lesson_text,
            symbol=symbol,
            topic=topic,
            conversation_id=row["id"],
        )

        evaluated += 1
        if lesson_text:
            lessons_written += 1
        logger.info(
            f"Evaluated advisor conversation for {symbol}: "
            f"{action} {'✓' if correct else '✗'} ({move_pct:+.1f}%)"
        )

    return {
        "evaluated": evaluated,
        "lessons_written": lessons_written,
        "cutoff_date": cutoff_date,
    }


# ---------------------------------------------------------------------------
# Stats helpers for the UI
# ---------------------------------------------------------------------------

def get_advisor_accuracy_stats(lookback_days: int = 30) -> dict:
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT action_recommended, outcome_correct
            FROM advisor_conversations
            WHERE outcome_correct IS NOT NULL
              AND conversation_date >= ?
              AND action_recommended IN ('BUY', 'SELL', 'WAIT', 'HOLD')
        """, (cutoff,)).fetchall()

    total = len(rows)
    if total == 0:
        return {"total": 0, "hit_rate": 0.0, "by_action": {}}

    correct = sum(1 for r in rows if r["outcome_correct"] == 1)
    by_action: dict = {}
    for r in rows:
        a = r["action_recommended"]
        by_action.setdefault(a, {"total": 0, "correct": 0})
        by_action[a]["total"] += 1
        if r["outcome_correct"] == 1:
            by_action[a]["correct"] += 1

    return {
        "total": total,
        "hit_rate": round(correct / total * 100, 1),
        "by_action": {
            a: {
                **v,
                "hit_rate": round(v["correct"] / v["total"] * 100, 1)
            }
            for a, v in by_action.items()
        },
        "lookback_days": lookback_days,
    }


def get_recent_conversations(limit: int = 20) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT session_id, conversation_date, primary_symbol,
                   action_recommended, outcome_correct,
                   LEFT(user_message, 80) as preview
            FROM advisor_conversations
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# Auto-init on import
init_advisor_db()

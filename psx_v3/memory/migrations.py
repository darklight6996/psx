"""
memory/migrations.py — Safely applies DB schema updates for PSX accuracy upgrades.
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
DB_PATH = Path("data/psx_memory.db")

def apply_migrations():
    """
    Safely applies migrations to the SQLite database.
    - Adds consensus_strength (INTEGER) and was_filtered (INTEGER) columns to council_decisions.
    - Creates analyst_weights table with 6 pre-populated analyst roles.
    - Creates analyst_prediction_log table.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        # 1. Add consensus_strength to council_decisions
        try:
            conn.execute("ALTER TABLE council_decisions ADD COLUMN consensus_strength INTEGER DEFAULT NULL")
            conn.commit()
            logger.info("Migration: Added consensus_strength to council_decisions")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                pass
            else:
                logger.error(f"Failed to add consensus_strength: {e}")

        # 2. Add was_filtered to council_decisions
        try:
            conn.execute("ALTER TABLE council_decisions ADD COLUMN was_filtered INTEGER DEFAULT 0")
            conn.commit()
            logger.info("Migration: Added was_filtered to council_decisions")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                pass
            else:
                logger.error(f"Failed to add was_filtered: {e}")

        # 3. Create analyst_weights table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analyst_weights (
                role               TEXT PRIMARY KEY,
                weight             REAL    DEFAULT 1.0,
                accuracy           REAL    DEFAULT 0.0,
                total_predictions  INTEGER DEFAULT 0,
                correct_predictions INTEGER DEFAULT 0,
                current_streak     INTEGER DEFAULT 0,
                updated_at         TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

        # Prepopulate the 6 analysts if empty
        cur = conn.execute("SELECT COUNT(*) FROM analyst_weights")
        count = cur.fetchone()[0]
        if count == 0:
            analysts = [
                "bull_analyst",
                "bear_analyst",
                "shariah_scholar",
                "quant_analyst",
                "macro_analyst",
                "risk_analyst"
            ]
            for role in analysts:
                conn.execute("""
                    INSERT INTO analyst_weights (role, weight, accuracy, total_predictions, correct_predictions, current_streak)
                    VALUES (?, 1.0, 0.0, 0, 0, 0)
                """, (role,))
            conn.commit()
            logger.info("Migration: Prepopulated analyst_weights table")

        # 4. Create analyst_prediction_log table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analyst_prediction_log (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol             TEXT    NOT NULL,
                decision_date      TEXT    NOT NULL,
                analyst_role       TEXT    NOT NULL,
                verdict            TEXT    NOT NULL,         -- BUY / HOLD / SELL
                price_at_decision  REAL    NOT NULL,
                evaluated_at       TEXT,
                price_at_evaluation REAL,
                was_correct        INTEGER DEFAULT NULL,     -- 1 = correct, 0 = wrong, NULL = pending
                created_at         TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        logger.info("Migration: Created analyst_prediction_log table")

    except Exception as e:
        logger.exception(f"Migration error: {e}")
    finally:
        conn.close()

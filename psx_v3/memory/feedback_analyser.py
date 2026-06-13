"""
memory/feedback_analyser.py — Analyzes user feedback and generates calibration proposals.

Includes manual-approval guardrails — proposals are queued in the DB, and must be approved
before affecting scoring_engine or weights.
"""

import json
import logging
from datetime import datetime
from memory.db import get_conn

logger = logging.getLogger(__name__)


def log_user_feedback(
    symbol: str,
    system_verdict: str,
    user_verdict: str,
    user_note: str = "",
    sector: str = "",
    was_news_driven: bool = False,
    news_type: str = "",
    pattern_type: str = "",
    signals_at_time: dict = None,
    price_at_signal: float = 0.0,
    price_now: float = 0.0,
) -> int:
    """Log user feedback / corrections to the DB."""
    today_str = datetime.now().date().isoformat()
    signals_json = json.dumps(signals_at_time) if signals_at_time else "{}"
    
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO user_feedback (
                symbol, feedback_date, system_verdict, user_verdict, 
                user_note, sector, was_news_driven, news_type, 
                pattern_type, signals_at_time, price_at_signal, price_now
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol.upper(), today_str, system_verdict, user_verdict,
            user_note, sector.lower(), 1 if was_news_driven else 0,
            news_type, pattern_type, signals_json, price_at_signal, price_now
        ))
        conn.commit()
        return cursor.lastrowid


def analyze_feedback_and_propose() -> list[dict]:
    """
    Scans unreviewed user feedback to identify recurring error patterns.
    If 3 or more unreviewed errors point to the same indicator or sector,
    generates a calibration proposal.
    
    Returns a list of proposed calibration dicts that were inserted.
    """
    proposals_created = []
    
    with get_conn() as conn:
        # Fetch unreviewed feedback
        feedbacks = conn.execute("""
            SELECT * FROM user_feedback WHERE reviewed = 0
        """).fetchall()
        
        if not feedbacks:
            return []
            
        # Group feedback by sector & pattern_type
        sector_errors = {}
        pattern_errors = {}
        
        for fb in feedbacks:
            sec = fb["sector"]
            pat = fb["pattern_type"]
            fb_id = fb["id"]
            
            if sec:
                sector_errors.setdefault(sec, []).append(fb_id)
            if pat:
                pattern_errors.setdefault(pat, []).append(fb_id)
                
        today_str = datetime.now().date().isoformat()
        
        # Check sectors for 3+ errors
        for sector, ids in sector_errors.items():
            if len(ids) >= 3:
                # Propose a sector weight reduction
                reason = f"System consistently incorrect on {sector} sector ({len(ids)} user-reported errors)."
                # Check if proposal already exists
                exists = conn.execute("""
                    SELECT id FROM calibration_proposals 
                    WHERE signal_name = ? AND sector_context = ? AND status = 'PENDING'
                """, ("sector_multiplier", sector)).fetchone()
                
                if not exists:
                    conn.execute("""
                        INSERT INTO calibration_proposals (
                            proposal_date, signal_name, sector_context, 
                            current_weight, proposed_weight, evidence_count, 
                            supporting_ids, reasoning
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        today_str, "sector_multiplier", sector,
                        1.0, 0.8, len(ids), json.dumps(ids), reason
                    ))
                    proposals_created.append({
                        "type": "sector",
                        "context": sector,
                        "reasoning": reason
                    })
                    
        # Check patterns / indicators for 3+ errors
        for pat, ids in pattern_errors.items():
            if len(ids) >= 3:
                reason = f"System consistently incorrect on pattern '{pat}' ({len(ids)} user-reported errors)."
                exists = conn.execute("""
                    SELECT id FROM calibration_proposals 
                    WHERE signal_name = ? AND status = 'PENDING'
                """, (pat,)).fetchone()
                
                if not exists:
                    conn.execute("""
                        INSERT INTO calibration_proposals (
                            proposal_date, signal_name, sector_context, 
                            current_weight, proposed_weight, evidence_count, 
                            supporting_ids, reasoning
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        today_str, pat, "global",
                        1.0, 0.7, len(ids), json.dumps(ids), reason
                    ))
                    proposals_created.append({
                        "type": "pattern",
                        "context": pat,
                        "reasoning": reason
                    })
                    
        # Mark reviewed feedback
        all_ids = [fb["id"] for fb in feedbacks]
        if all_ids:
            placeholders = ",".join("?" for _ in all_ids)
            conn.execute(f"""
                UPDATE user_feedback SET reviewed = 1 WHERE id IN ({placeholders})
            """, all_ids)
            
        conn.commit()
        
    return proposals_created


def approve_proposal(proposal_id: int):
    """Approve a calibration proposal."""
    now_str = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute("""
            UPDATE calibration_proposals
            SET status = 'APPROVED', approved_at = ?
            WHERE id = ?
        """, (now_str, proposal_id))
        conn.commit()
    logger.info(f"Approved calibration proposal {proposal_id}")


def reject_proposal(proposal_id: int):
    """Reject a calibration proposal."""
    with get_conn() as conn:
        conn.execute("""
            UPDATE calibration_proposals
            SET status = 'REJECTED'
            WHERE id = ?
        """, (proposal_id,))
        conn.commit()
    logger.info(f"Rejected calibration proposal {proposal_id}")


def get_approved_calibrations() -> dict:
    """
    Returns active (approved) calibrations as a dictionary.
    Includes sector_multipliers and indicator weight adjustments.
    """
    calibrations = {
        "sector_multipliers": {},
        "indicator_weights": {}
    }
    
    with get_conn() as conn:
        approved = conn.execute("""
            SELECT signal_name, sector_context, proposed_weight 
            FROM calibration_proposals 
            WHERE status = 'APPROVED'
        """).fetchall()
        
        for row in approved:
            sig = row["signal_name"]
            sec = row["sector_context"]
            w = row["proposed_weight"]
            
            if sig == "sector_multiplier":
                calibrations["sector_multipliers"][sec] = w
            else:
                calibrations["indicator_weights"][sig] = w
                
    return calibrations

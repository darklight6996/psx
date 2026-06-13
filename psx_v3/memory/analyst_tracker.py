"""
memory/analyst_tracker.py — Handles logging, evaluation, and weight updates for the local AI analysts.
"""

import logging
from datetime import datetime, date, timedelta
from memory.db import get_conn

logger = logging.getLogger(__name__)

def log_analyst_predictions(symbol: str, price: float, analyst_results: dict, decision_date: str = None):
    """
    Log the predictions of each analyst to the analyst_prediction_log table.
    """
    if not price:
        logger.warning(f"Cannot log analyst predictions for {symbol}: Price is invalid ({price})")
        return

    today_str = decision_date or date.today().isoformat()
    
    with get_conn() as conn:
        for role, res in analyst_results.items():
            verdict = res.get("verdict")
            if not verdict:
                continue
            
            # Check if prediction already logged for this symbol, date, and analyst to prevent duplicates
            try:
                exists = conn.execute("""
                    SELECT id FROM analyst_prediction_log
                    WHERE symbol = ? AND decision_date = ? AND analyst_role = ?
                """, (symbol.upper(), today_str, role)).fetchone()
                
                if exists:
                    # Update existing pending prediction
                    conn.execute("""
                        UPDATE analyst_prediction_log
                        SET price_at_decision = ?, verdict = ?, was_correct = NULL, evaluated_at = NULL, price_at_evaluation = NULL
                        WHERE id = ?
                    """, (price, verdict, exists["id"]))
                else:
                    # Insert a pending prediction log
                    conn.execute("""
                        INSERT INTO analyst_prediction_log (symbol, decision_date, analyst_role, verdict, price_at_decision)
                        VALUES (?, ?, ?, ?, ?)
                    """, (symbol.upper(), today_str, role, verdict, price))
            except Exception as e:
                logger.error(f"Error logging analyst prediction for {role} on {symbol}: {e}")
        conn.commit()
    logger.info(f"Logged analyst predictions for {symbol} on {today_str}")


def evaluate_analyst_predictions(current_prices: dict[str, float]):
    """
    Weekly evaluation of pending analyst predictions.
    Looks up pending predictions > 5 days old, and marks them correct/wrong based on price movement.
    - BUY correct if price went up > 1%
    - SELL correct if price went down > 1% (i.e. change < -1%)
    - HOLD correct if price movement is within ±2%
    """
    cutoff_date = (date.today() - timedelta(days=5)).isoformat()
    
    with get_conn() as conn:
        # Fetch pending predictions older than 5 days
        pending = conn.execute("""
            SELECT id, symbol, decision_date, analyst_role, verdict, price_at_decision
            FROM analyst_prediction_log
            WHERE was_correct IS NULL AND decision_date <= ?
        """, (cutoff_date,)).fetchall()
        
        if not pending:
            logger.info("No pending analyst predictions older than 5 days to evaluate.")
            return
            
        evaluated_count = 0
        today_str = date.today().isoformat()
        
        for pred in pending:
            pred_id = pred["id"]
            symbol = pred["symbol"]
            verdict = pred["verdict"]
            price_at_decision = pred["price_at_decision"]
            role = pred["analyst_role"]
            
            price_now = current_prices.get(symbol.upper())
            if not price_now:
                # Try to fetch last recorded price or wait
                continue
                
            if price_at_decision <= 0:
                continue
                
            change_pct = ((price_now - price_at_decision) / price_at_decision) * 100
            
            was_correct = 0
            if verdict == "BUY":
                if change_pct > 1.0:
                    was_correct = 1
            elif verdict == "SELL":
                if change_pct < -1.0:
                    was_correct = 1
            elif verdict == "HOLD":
                if -2.0 <= change_pct <= 2.0:
                    was_correct = 1
            
            conn.execute("""
                UPDATE analyst_prediction_log
                SET evaluated_at = ?, price_at_evaluation = ?, was_correct = ?
                WHERE id = ?
            """, (today_str, price_now, was_correct, pred_id))
            evaluated_count += 1
            
        conn.commit()
        logger.info(f"Evaluated {evaluated_count} pending analyst predictions.")
        
        # After evaluating, update all weights
        if evaluated_count > 0:
            update_analyst_weights()


def update_analyst_weights():
    """
    Recalculates weights for all analysts based on their last 20 evaluated predictions.
    - weight = 0.3 + (accuracy * 1.7)
    - weight clamped to [0.3, 2.0]
    - Streak bonus/penalty: ±0.1 for 3+ consecutive hits/misses
    """
    analyst_roles = [
        "bull_analyst",
        "bear_analyst",
        "shariah_scholar",
        "quant_analyst",
        "macro_analyst",
        "risk_analyst"
    ]
    
    today_str = datetime.now().isoformat()
    
    with get_conn() as conn:
        for role in analyst_roles:
            # Get last 20 predictions for this role
            history = conn.execute("""
                SELECT was_correct
                FROM analyst_prediction_log
                WHERE analyst_role = ? AND was_correct IS NOT NULL
                ORDER BY decision_date DESC, id DESC
                LIMIT 20
            """, (role,)).fetchall()
            
            total = len(history)
            if total == 0:
                # Default values if no history
                conn.execute("""
                    UPDATE analyst_weights
                    SET weight = 1.0, accuracy = 0.0, total_predictions = 0,
                        correct_predictions = 0, current_streak = 0, updated_at = ?
                    WHERE role = ?
                """, (today_str, role))
                continue
                
            correct = sum(1 for h in history if h["was_correct"] == 1)
            accuracy = correct / total
            
            # Calculate streak
            streak = 0
            first_val = history[0]["was_correct"]
            for h in history:
                if h["was_correct"] == first_val:
                    streak += 1 if first_val == 1 else -1
                else:
                    break
            
            # Base weight calculation
            weight = 0.3 + (accuracy * 1.7)
            
            # Streak adjustments
            if streak >= 3:
                weight += 0.1
            elif streak <= -3:
                weight -= 0.1
                
            # Clamp weight between 0.3 and 2.0
            weight = max(0.3, min(2.0, weight))
            
            # Update DB
            conn.execute("""
                UPDATE analyst_weights
                SET weight = ?, accuracy = ?, total_predictions = ?, 
                    correct_predictions = ?, current_streak = ?, updated_at = ?
                WHERE role = ?
            """, (round(weight, 2), round(accuracy * 100, 2), total, correct, streak, today_str, role))
            
        conn.commit()
    logger.info("Recalculated and updated analyst weights in database.")


def get_analyst_weights() -> dict[str, float]:
    """
    Returns a dictionary of analyst roles mapped to their current weight.
    TEMPORARILY DISABLED: Returns 1.0 for all roles to stabilize decision weights.
    """
    default_roles = [
        "bull_analyst", "bear_analyst", "shariah_scholar", 
        "quant_analyst", "macro_analyst", "risk_analyst"
    ]
    return {role: 1.0 for role in default_roles}



def get_analyst_leaderboard() -> list[dict]:
    """
    Returns full details for all analysts to show on the leaderboard.
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT role, weight, accuracy, total_predictions, correct_predictions, current_streak
            FROM analyst_weights
            ORDER BY weight DESC, accuracy DESC
        """).fetchall()
    return [dict(r) for r in rows]

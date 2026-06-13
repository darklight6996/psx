"""
portfolio.py — Local JSON-based portfolio memory.

Stores positions, trade history, and daily prediction snapshots.
All data lives in data/portfolio.json and data/memory_store.json.
"""

import json
import math
import logging
import requests
import pandas as pd
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR      = Path("data")
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"
MEMORY_FILE    = DATA_DIR / "memory_store.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- AI Prediction Evaluation Constants ---
EVALUATION_HORIZON_DAYS = 5
BUY_HIT_THRESHOLD_PCT = 1.5
SELL_HIT_THRESHOLD_PCT = -1.5
HOLD_STABILITY_THRESHOLD_PCT = 4.0
HOLD_BENCHMARK_LAG_LIMIT_PCT = -2.0


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Corrupt JSON at {path}, starting fresh")
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Portfolio CRUD
# ---------------------------------------------------------------------------

def load_portfolio() -> dict:
    """
    Load portfolio from disk.
    Structure:
    {
      "positions": { "SYS": { "ticker": "SYS", "entry_price": 1250.0, "shares": 100, "date": "2024-01-15", "notes": "" }, ... },
      "total_capital": 500000,
      "currency": "PKR"
    }
    """
    data = _load_json(PORTFOLIO_FILE)
    if "positions" not in data:
        data = {"positions": {}, "total_capital": 500000, "currency": "PKR"}
    return data


def save_portfolio(portfolio: dict) -> None:
    _save_json(PORTFOLIO_FILE, portfolio)


def add_position(
    ticker: str,
    entry_price: float,
    shares: int,
    date_str: Optional[str] = None,
    notes: str = "",
) -> dict:
    """Add or update a position in the portfolio."""
    portfolio = load_portfolio()
    sym = ticker.upper()
    portfolio["positions"][sym] = {
        "ticker":      sym,
        "entry_price": round(entry_price, 2),
        "shares":      int(shares),
        "cost_basis":  round(entry_price * shares, 2),
        "date":        date_str or date.today().isoformat(),
        "notes":       notes,
        "added_at":    datetime.now().isoformat(),
    }
    save_portfolio(portfolio)
    logger.info(f"Added position: {sym} x{shares} @ PKR {entry_price}")
    return portfolio["positions"][sym]


def remove_position(ticker: str) -> bool:
    """Remove a position from the portfolio. Returns True if removed."""
    portfolio = load_portfolio()
    sym = ticker.upper()
    if sym in portfolio["positions"]:
        del portfolio["positions"][sym]
        save_portfolio(portfolio)
        logger.info(f"Removed position: {sym}")
        return True
    return False


def update_capital(total_capital: float) -> None:
    portfolio = load_portfolio()
    portfolio["total_capital"] = total_capital
    save_portfolio(portfolio)


def get_positions() -> dict:
    return load_portfolio().get("positions", {})


def get_total_capital() -> float:
    return load_portfolio().get("total_capital", 500000)


def portfolio_summary(current_prices: dict[str, float]) -> dict:
    """
    Compute current portfolio value and P&L.

    Args:
        current_prices: { "SYS": 1320.5, ... }

    Returns:
        Summary dict with total_invested, current_value, total_pnl, positions list
    """
    positions = get_positions()
    total_capital = get_total_capital()
    rows = []
    total_invested  = 0.0
    current_value   = 0.0

    for sym, pos in positions.items():
        cost    = pos["cost_basis"]
        shares  = pos["shares"]
        entry   = pos["entry_price"]
        price   = current_prices.get(sym)

        if price:
            curr_val = price * shares
            pnl      = curr_val - cost
            pnl_pct  = (pnl / cost * 100) if cost else 0
        else:
            curr_val = cost
            pnl      = 0.0
            pnl_pct  = 0.0

        rows.append({
            "ticker":        sym,
            "entry_price":   entry,
            "current_price": price,
            "shares":        shares,
            "cost_basis":    round(cost, 2),
            "current_value": round(curr_val, 2),
            "pnl":           round(pnl, 2),
            "pnl_pct":       round(pnl_pct, 2),
            "date":          pos.get("date"),
        })
        total_invested += cost
        current_value  += curr_val

    total_pnl     = current_value - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0
    cash_remaining = total_capital - total_invested

    return {
        "positions":       rows,
        "total_capital":   total_capital,
        "total_invested":  round(total_invested, 2),
        "current_value":   round(current_value, 2),
        "cash_remaining":  round(cash_remaining, 2),
        "total_pnl":       round(total_pnl, 2),
        "total_pnl_pct":   round(total_pnl_pct, 2),
        "num_positions":   len(rows),
    }


# ---------------------------------------------------------------------------
# Memory store (daily predictions log)
# ---------------------------------------------------------------------------

def load_memory() -> dict:
    """
    Structure:
    {
      "daily_snapshots": {
        "2024-01-15": { "SYS": { "rating": "BUY", "score": 72.1, "price": 1250 }, ... },
        ...
      },
      "prediction_accuracy": { "hits": 12, "misses": 5, "total": 17 }
    }
    """
    data = _load_json(MEMORY_FILE)
    if "daily_snapshots" not in data:
        data = {
            "daily_snapshots": {},
            "prediction_accuracy": {"hits": 0, "misses": 0, "total": 0},
        }
    return data


def save_daily_snapshot(snapshots: dict[str, dict]) -> None:
    """
    Save today's predictions.

    Args:
        snapshots: { "SYS": { "rating": "BUY", "score": 72.1, "price": 1250.0 }, ... }
    """
    memory = load_memory()
    today  = date.today().isoformat()
    memory["daily_snapshots"][today] = {
        sym: {**data, "saved_at": datetime.now().isoformat()}
        for sym, data in snapshots.items()
    }
    _save_json(MEMORY_FILE, memory)
    logger.info(f"Saved daily snapshot for {today}: {len(snapshots)} stocks")


def get_yesterday_snapshot() -> dict:
    """Return the most recent previous day's snapshot."""
    memory = load_memory()
    snapshots = memory.get("daily_snapshots", {})
    today = date.today().isoformat()
    past_dates = sorted(k for k in snapshots.keys() if k < today)
    if past_dates:
        return snapshots[past_dates[-1]]
    return {}


def fetch_kse100_history() -> dict[str, float]:
    """Fetch historical KSE-100 closing prices from the PSX portal timeseries endpoint."""
    url = "https://dps.psx.com.pk/timeseries/eod/KSE100"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    history = {}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            for pt in data:
                if len(pt) >= 2:
                    ts, close = pt[0], pt[1]
                    # Convert Unix timestamp to YYYY-MM-DD
                    date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                    history[date_str] = float(close)
    except Exception as e:
        logger.warning(f"Failed to fetch KSE-100 history from PSX: {e}")
    return history


def evaluate_predictions(current_prices: dict[str, float]) -> dict:
    """
    Overhauls prediction evaluation:
    1. Tracks rolling predictions over a 5-day horizon.
    2. Uses KSE-100 relative logic for HOLD predictions.
    3. Keeps detailed metrics for BUY, SELL, and HOLD separately.
    4. Generates self-learning reflections using local Ollama.
    """
    memory = load_memory()
    
    # Initialize tiered metrics in memory store
    acc = memory.get("prediction_accuracy", {})
    acc["total"] = acc.get("total", 0)
    acc["hits"] = acc.get("hits", 0)
    acc["misses"] = acc.get("misses", 0)
    acc["buy_hits"] = acc.get("buy_hits", 0)
    acc["buy_misses"] = acc.get("buy_misses", 0)
    acc["sell_hits"] = acc.get("sell_hits", 0)
    acc["sell_misses"] = acc.get("sell_misses", 0)
    acc["hold_hits"] = acc.get("hold_hits", 0)
    acc["hold_misses"] = acc.get("hold_misses", 0)
    acc["high_conv_hits"] = acc.get("high_conv_hits", 0)
    acc["high_conv_misses"] = acc.get("high_conv_misses", 0)

    evaluated_dates = memory.setdefault("evaluated_dates", [])
    snapshots = memory.get("daily_snapshots", {})
    today_str = date.today().isoformat()

    # Load KSE-100 index history
    kse_history = fetch_kse100_history()

    from memory.db import save_reflection, get_conn
    from council.ollama_council import get_available_models, ollama_chat

    # Fetch available models for reflection
    available_models = get_available_models()
    reflection_model = None
    if available_models:
        for preferred in ["qwen2.5:7b", "qwen2.5:14b", "llama3.2", "deepseek", "mistral"]:
            matched = next((m for m in available_models if preferred in m), None)
            if matched:
                reflection_model = matched
                break
        if not reflection_model:
            reflection_model = available_models[0]

    details = []
    
    # Find eligible past snapshots (not evaluated, and not today)
    past_dates = sorted([k for k in snapshots.keys() if k < today_str and k not in evaluated_dates])
    
    for snapshot_date in past_dates:
        snapshot = snapshots[snapshot_date]
        
        # Check date age to skip staleness blocks
        snapshot_dt = datetime.strptime(snapshot_date, "%Y-%m-%d")
        age_days = (datetime.today() - snapshot_dt).days
        is_stale = age_days > 15
        
        all_resolved = True
        snapshot_details = []

        # Lazy import of fetch_ohlcv to avoid circular dependency
        from core.data_engine import fetch_ohlcv

        # Keep track of failed fetches in this run of evaluate_predictions to avoid redundant yfinance API calls
        failed_fetches = set()

        for sym, pred in list(snapshot.items()):
            if sym in ("_meta", "saved_at") or not isinstance(pred, dict):
                continue
                
            # Skip if this specific prediction has already been evaluated
            if pred.get("evaluated"):
                continue

            prev_price = pred.get("price")
            rating     = pred.get("rating")
            if not prev_price or not rating:
                continue

            if sym in failed_fetches:
                all_resolved = False
                continue

            # Fetch daily data for symbol from cache
            closes_df = fetch_ohlcv(sym, period="1y", interval="1d")
            if closes_df is None or closes_df.empty:
                failed_fetches.add(sym)
                # Delisted/stale or no data - if stale, we permanently exclude it to avoid blocking the date
                if is_stale:
                    pred["evaluated"] = True
                    pred["is_correct"] = 0
                    pred["evaluated_at"] = today_str
                    continue
                all_resolved = False
                continue

            # Clean and match dates
            closes_df.index = pd.to_datetime(closes_df.index).strftime("%Y-%m-%d")
            matching_dates = [dt for dt in closes_df.index if dt >= snapshot_date]
            if not matching_dates:
                if is_stale:
                    pred["evaluated"] = True
                    pred["is_correct"] = 0
                    pred["evaluated_at"] = today_str
                    continue
                all_resolved = False
                continue
                
            d_matched = matching_dates[0]
            closes_list = list(closes_df.index)
            idx = closes_list.index(d_matched)

            # Check if 5 trading days have elapsed
            if len(closes_df) > idx + EVALUATION_HORIZON_DAYS:
                base_price = float(closes_df["Close"].iloc[idx])
                target_price = float(closes_df["Close"].iloc[idx + EVALUATION_HORIZON_DAYS])
                target_date = closes_df.index[idx + EVALUATION_HORIZON_DAYS]
                stock_change = (target_price - base_price) / base_price * 100

                # Benchmark relative logic
                bench_base = kse_history.get(d_matched)
                bench_target = kse_history.get(target_date)
                
                # If benchmark missing on that day, search nearest dates
                if not bench_base:
                    near_b = [kse_history[k] for k in sorted(kse_history.keys()) if k >= d_matched]
                    bench_base = near_b[0] if near_b else None
                if not bench_target:
                    near_t = [kse_history[k] for k in sorted(kse_history.keys()) if k >= target_date]
                    bench_target = near_t[0] if near_t else None

                bench_change = 0.0
                if bench_base and bench_target:
                    bench_change = (bench_target - bench_base) / bench_base * 100

                # ── Rating HIT Evaluation ──
                hit = False
                if rating == "BUY":
                    hit = stock_change >= BUY_HIT_THRESHOLD_PCT
                elif rating == "SELL":
                    hit = stock_change <= SELL_HIT_THRESHOLD_PCT
                elif rating == "HOLD":
                    # HOLD is correct if stock remained relatively stable (absolute)
                    is_stable = abs(stock_change) < HOLD_STABILITY_THRESHOLD_PCT
                    # Or relative to index:
                    is_up_market = bench_change > 0
                    if is_up_market:
                        # In up market: stock didn't underperform index by more than 2%
                        hold_hit = (stock_change - bench_change) >= HOLD_BENCHMARK_LAG_LIMIT_PCT
                    else:
                        # In down market: stock lost < 2% or outperformed benchmark
                        hold_hit = stock_change > -2.0 or stock_change >= bench_change
                    
                    hit = is_stable or hold_hit

                is_correct = 1 if hit else 0

                # Update memory store counts
                acc["total"] += 1
                if hit:
                    acc["hits"] += 1
                else:
                    acc["misses"] += 1

                if rating == "BUY":
                    if hit:
                        acc["buy_hits"] += 1
                    else:
                        acc["buy_misses"] += 1
                elif rating == "SELL":
                    if hit:
                        acc["sell_hits"] += 1
                    else:
                        acc["sell_misses"] += 1
                elif rating == "HOLD":
                    if hit:
                        acc["hold_hits"] += 1
                    else:
                        acc["hold_misses"] += 1

                # Mark prediction as evaluated in snapshot data to prevent repeat evaluations
                pred["evaluated"] = True
                pred["is_correct"] = is_correct
                pred["evaluated_at"] = today_str
                pred["price_at_evaluation"] = target_price

                # High conviction BUY tracking
                score = pred.get("score")
                if score and score >= 75 and rating == "BUY":
                    if hit:
                        acc["high_conv_hits"] += 1
                    else:
                        acc["high_conv_misses"] += 1

                # Database Reflection logging
                dec_id = 0
                dec_date = snapshot_date
                chairman_notes = "No matching decision found in DB."
                try:
                    with get_conn() as conn:
                        dec = conn.execute(
                            "SELECT id, chairman_notes FROM council_decisions WHERE symbol = ? AND decision_date = ?",
                            (sym, snapshot_date)
                        ).fetchone()
                        if dec:
                            dec_id = dec["id"]
                            chairman_notes = dec["chairman_notes"] or "No notes available."
                except Exception as e:
                    logger.warning(f"Could not search DB for decision for reflection: {e}")

                # Check if reflection already recorded
                already_reflected = False
                if dec_id > 0:
                    try:
                        with get_conn() as conn:
                            already_reflected = conn.execute(
                                "SELECT 1 FROM decision_reflections WHERE decision_id = ?", (dec_id,)
                            ).fetchone() is not None
                    except Exception:
                        pass

                if not already_reflected:
                    reflection_text = ""
                    if reflection_model:
                        system_prompt = "You are the Self-Reflection Analyst for the PSX Advisory Agent. Write a highly professional, brief critique (3-4 lines) analyzing why a prediction was correct or incorrect and what lessons we can learn."
                        user_prompt = f"""
Analyze this 5-day prediction outcome for {sym}:
- Verdict was {rating} (made on {dec_date} at price {prev_price:.2f})
- Price now (5-days later): {target_price:.2f} ({stock_change:+.2f}%)
- Benchmark (KSE-100) change: {bench_change:+.2f}%
- Result: {"HIT (CORRECT)" if hit else "MISS (INCORRECT)"}

Previous Chairman rationale:
"{chairman_notes}"

Write a concise 3-4 sentence self-reflection. Critique what technical, momentum, or risk factors we analyzed correctly or missed, and what the concrete 'lesson learned' is for the future.
"""
                        try:
                            reflection_text = ollama_chat(reflection_model, system_prompt, user_prompt, timeout=30)
                        except Exception as e:
                            logger.warning(f"Ollama reflection failed: {e}")

                    if not reflection_text:
                        if hit:
                            reflection_text = f"Successful prediction on {sym}. The stock's momentum and technical score correctly anticipated the {stock_change:+.2f}% move over 5 days."
                        else:
                            reflection_text = f"Missed prediction on {sym}. The rating {rating} did not align with the subsequent {stock_change:+.2f}% move over 5 days. Need to check for short-term overbought signals or macro headwinds."

                    try:
                        save_reflection(
                            decision_id=dec_id,
                            symbol=sym,
                            decision_date=dec_date,
                            verdict=rating,
                            price_at_decision=prev_price,
                            price_now=target_price,
                            price_change_pct=stock_change,
                            is_correct=is_correct,
                            reflection_notes=reflection_text
                        )
                    except Exception as e:
                        logger.error(f"Failed to save reflection to DB: {e}")

                snapshot_details.append({
                    "symbol":     sym,
                    "rating":     rating,
                    "prev_price": round(prev_price, 2),
                    "curr_price": round(target_price, 2),
                    "pct_change": round(stock_change, 2),
                    "hit":        hit,
                })
            else:
                # Not enough trading days yet, skip this stock for now
                all_resolved = False

        if all_resolved:
            evaluated_dates.append(snapshot_date)
            details.extend(snapshot_details)
            logger.info(f"Successfully evaluated all predictions for snapshot date: {snapshot_date}")
        elif is_stale:
            # Older than 15 days, permanently mark evaluated to avoid blocking the queue
            evaluated_dates.append(snapshot_date)
            details.extend(snapshot_details)
            logger.info(f"Stale snapshot date permanently marked as evaluated: {snapshot_date}")

    memory["prediction_accuracy"] = acc
    _save_json(MEMORY_FILE, memory)

    hit_rate = acc["hits"] / acc["total"] * 100 if acc["total"] > 0 else 0.0

    return {
        "details":       details,
        "total_checked": acc["total"],
        "hits":          acc["hits"],
        "misses":        acc["misses"],
        "hit_rate_pct":  round(hit_rate, 1),
        "confusion_matrix": {
            "buy_hits": acc.get("buy_hits", 0),
            "buy_misses": acc.get("buy_misses", 0),
            "sell_hits": acc.get("sell_hits", 0),
            "sell_misses": acc.get("sell_misses", 0),
            "hold_hits": acc.get("hold_hits", 0),
            "hold_misses": acc.get("hold_misses", 0),
        }
    }


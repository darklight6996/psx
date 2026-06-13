"""
backtester.py — Historical strategy backtesting for PSX HQM momentum strategy.

⚠️  SURVIVORSHIP BIAS WARNING:
    This backtester uses currently available yfinance data, which only contains
    stocks that STILL EXIST. Stocks that went bankrupt or were delisted between
    your test period and today are NOT included. This inflates backtest performance.
    Always interpret results with this caveat in mind.
    For a truly unbiased backtest, you need a point-in-time database of historical
    PSX constituents — not available free via yfinance.

Usage:
    from backtester import run_backtest
    results = run_backtest(["SYS", "ENGRO", "LUCK"], start="2019-01-01", end="2024-01-01")
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from core.data_engine import fetch_ohlcv
from core.hqm_engine import compute_returns, compute_hqm_universe

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Simple momentum backtest
# ---------------------------------------------------------------------------

def run_backtest(
    symbols: list[str],
    start_date: str = "2019-01-01",
    end_date:   str = "2024-01-01",
    rebalance_days: int = 30,
    top_n: int = 5,
    stop_loss_pct: float = 0.10,
    initial_capital: float = 500_000,
) -> dict:
    """
    Run a simplified HQM momentum backtest.

    Strategy:
    - Every `rebalance_days`, score all stocks by 1M/3M/6M/12M momentum.
    - Buy equal-weight top N stocks.
    - Apply a 10% trailing stop loss per position.
    - Compare against PSX KSE100 (^KSE) benchmark.

    Args:
        symbols:         list of PSX tickers to test (no .KA suffix)
        start_date:      ISO date string
        end_date:        ISO date string
        rebalance_days:  how often to rebalance
        top_n:           number of stocks to hold per period
        stop_loss_pct:   trailing stop per position
        initial_capital: starting PKR

    Returns:
        dict with performance metrics and trade log
    """
    logger.info(f"Starting backtest: {len(symbols)} symbols, {start_date} → {end_date}")

    start_dt = pd.Timestamp(start_date)
    end_dt   = pd.Timestamp(end_date)

    # ── Fetch all daily data ─────────────────────────────────────────────────
    all_prices: dict[str, pd.Series] = {}
    for sym in symbols:
        df = fetch_ohlcv(sym, period="max", interval="1d")
        if df is not None and not df.empty:
            closes = df["Close"]
            closes.index = pd.to_datetime(closes.index).tz_localize(None)
            mask  = (closes.index >= start_dt) & (closes.index <= end_dt)
            sliced = closes[mask]
            if len(sliced) > 60:
                all_prices[sym] = sliced

    if not all_prices:
        return {"error": "No price data available for backtest period"}

    # Create aligned price matrix
    price_matrix = pd.DataFrame(all_prices).ffill().dropna(how="all")
    trading_days = price_matrix.index.tolist()

    if len(trading_days) < 60:
        return {"error": "Insufficient trading days in backtest period"}

    # ── Benchmark (KSE100) ───────────────────────────────────────────────────
    benchmark_prices = None
    try:
        bdf = fetch_ohlcv("^KSE", period="max", interval="1d")
        if bdf is not None:
            bc = bdf["Close"]
            bc.index = pd.to_datetime(bc.index).tz_localize(None)
            benchmark_prices = bc[(bc.index >= start_dt) & (bc.index <= end_dt)]
    except Exception:
        pass

    # ── Simulation ───────────────────────────────────────────────────────────
    capital       = initial_capital
    portfolio     = {}    # { sym: { "shares": int, "entry": float, "high_water": float } }
    trade_log     = []
    equity_curve  = []
    next_rebalance = trading_days[63]   # first rebalance after 3 months warm-up

    for i, day in enumerate(trading_days):
        day_prices = price_matrix.loc[day].dropna()

        # Check trailing stops
        exits = []
        for sym, pos in list(portfolio.items()):
            if sym not in day_prices.index:
                continue
            price = day_prices[sym]
            # Update high water mark
            pos["high_water"] = max(pos["high_water"], price)
            stop_price = pos["high_water"] * (1 - stop_loss_pct)

            if price <= stop_price:
                proceeds = pos["shares"] * price
                capital += proceeds
                pnl = proceeds - pos["shares"] * pos["entry"]
                trade_log.append({
                    "date": day.date(), "action": "STOP_EXIT", "symbol": sym,
                    "price": round(price, 2), "shares": pos["shares"],
                    "pnl":   round(pnl, 2), "reason": "Trailing stop hit",
                })
                exits.append(sym)

        for sym in exits:
            del portfolio[sym]

        # Rebalance
        if day >= next_rebalance and i >= 63:
            # Compute returns for all available stocks
            returns_records = []
            for sym in price_matrix.columns:
                window = price_matrix[sym].iloc[max(0, i-252):i+1].dropna()
                if len(window) >= 22:
                    rets = compute_returns(window)
                    returns_records.append({"symbol": sym, **rets})

            if returns_records:
                ret_df = pd.DataFrame(returns_records).set_index("symbol")
                scored = compute_hqm_universe(ret_df)
                scored = scored.dropna(subset=["hqm_score"])
                top_picks = scored.nlargest(top_n, "hqm_score").index.tolist()

                # Exit positions not in new top picks
                for sym in list(portfolio.keys()):
                    if sym not in top_picks and sym in day_prices.index:
                        price    = day_prices[sym]
                        proceeds = portfolio[sym]["shares"] * price
                        capital  += proceeds
                        pnl = proceeds - portfolio[sym]["shares"] * portfolio[sym]["entry"]
                        trade_log.append({
                            "date": day.date(), "action": "REBALANCE_EXIT", "symbol": sym,
                            "price": round(price, 2), "shares": portfolio[sym]["shares"],
                            "pnl":   round(pnl, 2), "reason": "Dropped from top N",
                        })
                        del portfolio[sym]

                # Enter new picks
                budget_per_stock = capital / max(top_n - len(portfolio), 1)
                for sym in top_picks:
                    if sym in portfolio:
                        continue
                    if sym not in day_prices.index:
                        continue
                    price  = day_prices[sym]
                    shares = int(budget_per_stock // price)
                    if shares > 0:
                        cost = shares * price
                        capital -= cost
                        portfolio[sym] = {
                            "shares":      shares,
                            "entry":       price,
                            "high_water":  price,
                        }
                        trade_log.append({
                            "date": day.date(), "action": "BUY", "symbol": sym,
                            "price": round(price, 2), "shares": shares,
                            "pnl":   None, "reason": f"Top-{top_n} HQM pick",
                        })

            next_rebalance = day + pd.Timedelta(days=rebalance_days)

        # Mark-to-market equity
        portfolio_value = capital
        for sym, pos in portfolio.items():
            if sym in day_prices.index:
                portfolio_value += pos["shares"] * day_prices[sym]

        equity_curve.append({"date": day.date(), "equity": round(portfolio_value, 2)})

    # ── Final liquidation ─────────────────────────────────────────────────────
    last_prices = price_matrix.iloc[-1]
    for sym, pos in portfolio.items():
        if sym in last_prices.index:
            price    = last_prices[sym]
            proceeds = pos["shares"] * price
            capital += proceeds
            trade_log.append({
                "date": trading_days[-1].date(), "action": "FINAL_EXIT", "symbol": sym,
                "price": round(price, 2), "shares": pos["shares"],
                "pnl":   round(proceeds - pos["shares"] * pos["entry"], 2),
                "reason": "End of backtest",
            })

    # ── Performance metrics ──────────────────────────────────────────────────
    eq_series     = pd.DataFrame(equity_curve).set_index("date")["equity"]
    total_return  = (capital - initial_capital) / initial_capital * 100
    trading_years = (end_dt - start_dt).days / 365.25

    # CAGR
    cagr = ((capital / initial_capital) ** (1 / trading_years) - 1) * 100 if trading_years > 0 else 0

    # Max drawdown
    rolling_max = eq_series.cummax()
    drawdowns    = (eq_series - rolling_max) / rolling_max * 100
    max_drawdown = float(drawdowns.min())

    # Sharpe (simplified: using daily returns vs 0 risk-free for simplicity)
    daily_rets   = eq_series.pct_change().dropna()
    sharpe       = (daily_rets.mean() / daily_rets.std() * np.sqrt(252)) if daily_rets.std() > 0 else 0

    # Benchmark comparison
    bench_return = None
    if benchmark_prices is not None and not benchmark_prices.empty:
        b_start = float(benchmark_prices.iloc[0])
        b_end   = float(benchmark_prices.iloc[-1])
        bench_return = (b_end - b_start) / b_start * 100

    buys  = sum(1 for t in trade_log if t["action"] == "BUY")
    wins  = sum(1 for t in trade_log if t["pnl"] and t["pnl"] > 0)
    total_trades = sum(1 for t in trade_log if t["action"] != "BUY")
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0

    return {
        "summary": {
            "initial_capital":   initial_capital,
            "final_capital":     round(capital, 2),
            "total_return_pct":  round(total_return, 2),
            "cagr_pct":          round(cagr, 2),
            "max_drawdown_pct":  round(max_drawdown, 2),
            "sharpe_ratio":      round(sharpe, 3),
            "win_rate_pct":      round(win_rate, 2),
            "total_trades":      total_trades,
            "benchmark_return":  round(bench_return, 2) if bench_return else None,
            "start_date":        start_date,
            "end_date":          end_date,
            "symbols_tested":    len(all_prices),
        },
        "equity_curve": equity_curve,
        "trade_log":    trade_log,
        "survivorship_bias_warning": (
            "⚠️ SURVIVORSHIP BIAS: This backtest only includes stocks that currently exist on yfinance. "
            "Companies that failed, were delisted, or merged are NOT included. "
            "Real-world performance would be lower. Never rely solely on this backtest."
        ),
    }

# Personal Investment Advisor — Guide

## Overview

The PSX Advisory Agent now has **two separate signal layers**:

| Layer | Question it answers | Who it's for |
|-------|---------------------|--------------|
| **Market Signal** | "Is this stock a good buy right now?" | Everyone — same for all users |
| **Personal Signal** | "Given YOUR position, what should YOU do?" | Only you — based on your actual holdings |

These are **genuinely different decisions**. A stock being a market BUY is irrelevant if you already hold a full position at a lower price — your decision is about managing what you already own, not whether the stock is worth buying.

---

## The Four Scenarios

### Scenario A — No Position, Market Says BUY

**Personal Verdict:** `CONSIDER_BUYING` 🔵

The system suggests:
- How many shares to buy (based on 5% of your total capital)
- Entry timing (GOOD or WAIT_FOR_PULLBACK based on today's ATR move)
- Stop loss (entry − 2×ATR)
- Target 1 (entry + 2×ATR) and Target 2 (entry + 4×ATR)

### Scenario B — Position Held, In Profit

**Personal Verdicts:**

| Verdict | Icon | Trigger |
|---------|------|---------|
| `HOLD_AND_TRAIL` | 🟢 | Profit but no target hit yet — trail stop |
| `TAKE_PARTIAL_PROFIT` | 💛 | Price reached Target 1 (entry + 2×ATR) |
| `TAKE_FULL_PROFIT` | 💰 | Price reached Target 2 (entry + 4×ATR) |
| `EXIT_TRAILING_STOP_HIT` | 🔴 | Price fell below trailing stop (highest − 1.5×ATR) |
| `EXIT_MARKET_TURNED` | 🔴 | Market signal changed to SELL while in profit |

**Key mechanics:**
- Trailing stop = highest price since entry − 1.5×ATR
- At Target 1: sell half, move stop to entry price, let rest run
- At Target 2: consider full exit or tight trailing stop

### Scenario C — Position Held, In Loss

**Personal Verdicts:**

| Verdict | Icon | Trigger |
|---------|------|---------|
| `HOLD_WITHIN_TOLERANCE` | 🟡 | Loss < 8%, market signal still BUY/HOLD |
| `WATCH_CAREFULLY` | ⚠️ | Loss between 8-15%, stop not yet hit |
| `CUT_LOSS` | 🚨 | ATR stop hit (entry − 2×ATR) or loss > 15% |
| `EXIT_DOUBLE_SIGNAL` | 🚨 | In loss AND market signal turned SELL |

**Key rules:**
- **Never average down** — the system explicitly warns against it
- Hard stop at entry − 2×ATR
- If market signal also turns SELL, that's double confirmation to exit

### Scenario D — No Position, Market Says HOLD/SELL

**Personal Verdict:** `MONITOR` 👁️

No action needed. The system suggests a watch price (3% pullback) for re-evaluation.

---

## How to Read the UI

### Predictions Tab — Rankings Table

Two columns side by side:
- **Market Signal**: 🟢 BUY / 🟡 HOLD / 🔴 SELL (same for everyone)
- **My Signal**: Your personal recommendation (🔵 Consider Buy / 💛 Take Half Profit / 🟢 Hold & Trail / 🚨 Cut Loss / etc.)

### Predictions Tab — Stock Detail

If you hold the stock, a blue "Your Position" card appears at the top showing:
- Average entry price, shares held, invested amount
- Current value and P&L (PKR and %)
- Weeks held
- Personal recommendation with full explanation
- Your trailing stop, Target 1, and Target 2 levels

If you don't hold the stock, a compact bar shows Market Signal vs Your Signal side by side.

### Dashboard Tab — Alerts

Urgent personal signals (CUT_LOSS, EXIT_TRAILING_STOP_HIT, EXIT_DOUBLE_SIGNAL) appear in a **red "🚨 Urgent" section** above all other alerts.

### Weekly Review Tab

- **Portfolio Personal Summary** at the top: positions needing attention, profit-taking opportunities, and watchlist BUY candidates
- Each position card shows the **personal verdict** (not just the generic recommendation)
- Target 1 and Target 2 levels shown per position

---

## Where the Data Comes From

- **Position data**: `investments` table in `data/psx_memory.db` — populated when you record an investment
- **Market signal**: `scoring_engine.py` → `pipeline.py` (deterministic rule-based scoring)
- **ATR values**: `horizon_engine.py` (14-period Average True Range)
- **Personal signal**: `core/personal_advisor.py` — combines the above three inputs

---

## Important Disclaimers

1. **The personal signal is not financial advice.** It is a mechanical framework for position management based on ATR-based thresholds.
2. **The system does not know your risk tolerance, financial situation, or investment goals.** It only knows what you bought and at what price.
3. **Always verify signals against your own judgment.** The personal signal is a tool, not a replacement for thinking.
4. **Past performance does not guarantee future results.** ATR-based targets are statistical estimates, not promises.
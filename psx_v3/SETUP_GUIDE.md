# PSX Advisory Agent v3 — Setup Guide
## Local AI Council + Persistent Memory Edition

---

## What's new in v3

- **Local AI Council via Ollama** — Free models (Qwen, DeepSeek, Gemma, Mistral) debate as 6 specialist analysts. Claude used ONLY as Chairman (optional — if no Claude key, a local model chairs too, making it 100% free).
- **Persistent SQLite memory** — Every investment, every board decision, every weekly P&L snapshot is stored forever in data/psx_memory.db
- **📅 My Money tab** — Tracks PKR invested, current value, weekly P&L narrative. Tells you "you put in 5000, it's now 6200, consider partial exit" each week.
- **Full investment lifecycle** — Record buys, track live value, close positions (sells), see realised vs unrealised P&L.

---

## Architecture

```
Yahoo Finance (free) ──► Price data, fundamentals, technicals
         │
         ▼
   Daily Analysis (HQM + Shariah + Technical)
         │
         ▼
   🏛️ AI Board Room
   ┌─────────────────────────────────────────────┐
   │  🐂 Bull     → Qwen2.5      (local, free)   │
   │  🐻 Bear     → DeepSeek-R1  (local, free)   │
   │  ☽ Shariah  → Gemma3       (local, free)   │
   │  📊 Quant   → Mistral      (local, free)   │
   │  🌍 Macro   → DeepSeek-R1  (local, free)   │
   │  ⚠️ Risk    → Qwen2.5      (local, free)   │
   │  ⚖️ Chairman→ Claude Sonnet (optional $0.003) │
   │             OR local model  (100% free)     │
   └─────────────────────────────────────────────┘
         │
         ▼
   Final Verdict → Saved to SQLite (permanent)
         │
         ▼
   📅 My Money — weekly P&L tracking
```

---

## STEP 1 — Install Python

### Windows
1. Go to https://python.org/downloads
2. Download Python 3.12.x
3. Run installer → CHECK "Add Python to PATH" ← CRITICAL
4. Verify: open Command Prompt → python --version

### Linux (Ubuntu/Debian)
    sudo apt update && sudo apt install python3.11 python3-pip -y

### Linux (Fedora)
    sudo dnf install python3.11 python3-pip -y

---

## STEP 2 — Install Ollama (the local AI engine)

### Windows
1. Go to https://ollama.com
2. Click "Download" → run the .exe installer
3. Ollama starts automatically as a background service

### Linux
    curl -fsSL https://ollama.com/install.sh | sh

Verify Ollama is running:
    curl http://localhost:11434/api/tags
(Should return JSON with a "models" list)

---

## STEP 3 — Pull AI models into Ollama

Open a terminal and run these commands. Each model downloads once and is cached.

MINIMUM (gets you started, ~8 GB):
    ollama pull qwen2.5:7b
    ollama pull mistral:7b

RECOMMENDED (better quality, ~25 GB total):
    ollama pull qwen2.5:14b
    ollama pull deepseek-r1:14b
    ollama pull gemma3:12b
    ollama pull mistral:7b

LIGHTWEIGHT (if low on disk, ~10 GB):
    ollama pull qwen2.5:7b
    ollama pull deepseek-r1:7b
    ollama pull gemma3:4b
    ollama pull llama3.2:3b

The agent automatically assigns the best available model to each analyst role.
If a preferred model isn't pulled, it falls back to whatever is available.

Model selection logic per role:
  Bull Analyst    → qwen2.5:14b > qwen2.5:7b > mistral:7b
  Bear Analyst    → deepseek-r1:14b > deepseek-r1:7b > mistral:7b
  Shariah Scholar → gemma3:12b > gemma3:4b > qwen2.5:7b
  Quant Analyst   → mistral:7b > qwen2.5:14b > deepseek-r1:7b
  Macro Analyst   → deepseek-r1:14b > qwen2.5:14b > gemma3:12b
  Risk Analyst    → qwen2.5:14b > gemma3:12b > mistral:7b
  Chairman        → Claude Sonnet (via API) OR best local fallback

---

## STEP 4 — Extract and configure

1. Extract psx_agent_v3.zip to a simple path:
   Windows: C:\psx_v3\
   Linux:   ~/psx_v3/

2. Set up config:
   Windows: copy .env.example .env  (then edit in Notepad)
   Linux:   cp .env.example .env && nano .env

3. In .env, you can optionally add:
   ANTHROPIC_API_KEY=sk-ant-...   (for Claude chairman — optional)
   NEWSAPI_KEY=...                (for macro news — optional)

   Both are optional. The agent works fully without either key.

---

## STEP 5 — Launch

### Windows
Double-click launch.bat
(It installs Python packages automatically on first run)

### Linux
    cd ~/psx_v3
    ./launch.sh

App opens at: http://localhost:8501

---

## Using the app

### Daily workflow
1. Click "🚀 Run Daily Analysis" in the sidebar
2. Review the Dashboard and Predictions tabs
3. Pick a stock → click "🏛️ Convene Board" in AI Board Room
4. If verdict is BUY, click "I invested PKR X" to record it
5. Come back weekly → the "📅 My Money" tab shows your P&L

### The 6 tabs explained

📊 Dashboard
  - Macro sentiment banner
  - Alert panel (sell signals, Shariah flags)
  - Candlestick charts with RSI, Bollinger, MACD, EMA
  - Portfolio value overview

📈 Predictions
  - All stocks ranked by composite score
  - Full per-stock deep dive
  - Position sizing calculator
  - Shariah criteria detail + purification calculator

🏛️ AI Board Room
  - Select a stock → "Convene Board"
  - 6 analysts debate using local Ollama models
  - Chairman synthesises final decision
  - Decision saved permanently to memory
  - Record investment directly from this tab

📅 My Money
  - Every PKR you invested, where, when
  - Current value (live prices)
  - Weekly P&L narrative: "You invested PKR 5000 in SYS 3 weeks ago. Now worth PKR 6200 (+24%). Consider partial exit."
  - Recommendation: HOLD / CONSIDER PARTIAL DIVEST / WATCH / REVIEW
  - Close positions when you sell
  - Full investment history

🧪 Backtester
  - Backtest HQM momentum strategy historically
  - Equity curve, Sharpe ratio, max drawdown
  - SURVIVORSHIP BIAS WARNING always shown

💼 Portfolio
  - Simple position tracker
  - Capital management

---

## Understanding the weekly review

Every time you open the "📅 My Money" tab, the app:
1. Fetches current live prices for all your positions
2. Compares against your entry price
3. Generates a narrative for each position
4. Gives a recommendation based on % move:
   - > +5%: Consider partial exit (lock in gains)
   - +2% to +5%: HOLD (running well)
   - -2% to +2%: HOLD (flat, no action needed)
   - -8% to -2%: WATCH (approaching stop loss territory)
   - < -8%: REVIEW (stop loss territory, consider exiting)
5. Saves a weekly snapshot to the database

The memory persists indefinitely. Every session adds to the history.

---

## Cost breakdown

Component           | Cost
Quantitative analysis | FREE (Yahoo Finance)
Ollama models         | FREE (runs locally)
AI Board Room (6 analysts) | FREE (local models)
Chairman (Claude)     | ~$0.003 per session (OPTIONAL)
NewsAPI macro        | FREE (100/day limit)
Total per day        | $0.00 to ~$0.03 depending on usage

---

## Troubleshooting

Problem                          | Solution
Ollama not running               | Start Ollama service; check http://localhost:11434
No models available              | Run: ollama pull qwen2.5:7b
Board takes too long             | Use smaller models: ollama pull llama3.2:3b
Python not found (Windows)       | Reinstall with "Add to PATH" checked
Port 8501 in use                 | streamlit run app.py --server.port 8502
Data/psx_memory.db corrupt       | Delete it; it will be recreated (loses history)
Slow first analysis run          | Normal — downloading 2yr price data per stock

---

## File structure

psx_v3/
├── app.py                     ← Main Streamlit app
├── agent.py                   ← Daily analysis orchestrator
├── requirements.txt
├── launch.bat                 ← Windows one-click launcher
├── launch.sh                  ← Linux one-click launcher
├── .env.example               ← Config template
├── core/                      ← Data, indicators, HQM, Shariah
├── council/
│   └── ollama_council.py      ← Local AI board room
├── memory/
│   └── db.py                  ← SQLite persistent memory
├── ui/
│   ├── dashboard_tab.py
│   ├── predictions_tab.py
│   ├── council_tab.py         ← Board room UI
│   ├── weekly_review_tab.py   ← My Money UI
│   ├── backtest_tab.py
│   └── portfolio_tab.py
└── data/                      ← Created automatically
    ├── psx_memory.db          ← ALL your data (investments, decisions, P&L)
    ├── portfolio.json
    └── cache/                 ← Price data cache

---

DISCLAIMER: Advisory only. Not financial advice. Consult a SECP-registered
financial advisor and a qualified Islamic scholar before making any investment decision.

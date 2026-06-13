# 📈 PSX Advisory Agent v3

A professional cross-platform AI-powered advisor, strategy backtester, and portfolio manager for the **Pakistan Stock Exchange (PSX)**.

This system leverages local AI models (via Ollama), advanced quantitative momentum algorithms (HQM), deep technical analysis indicators, and automated Shariah compliance filters to help you analyze, backtest, and manage your stock investments.

---

## ✨ Features

- **🏛️ AI Board Room**: Multi-agent local AI Council (using Ollama models like Llama3, Qwen, or DeepSeek) synthesizes macro indicators, technical patterns, and fundamental health.
- **⚖️ Shariah Screening**: Automated screening against the **5 KMI criteria** (Karachi Meezan Index) to filter and score compliant stocks.
- **💼 Portfolio & Money Manager**: Log transactions, track P&L, calculate position sizing, and purification requirements.
- **🧪 Strategy Backtester**: Run historical backtests on momentum and technical strategies across 5+ years of daily stock closes.
- **🧠 AI Learning & Reflection Loop**: Every day you run the system, the agent reviews yesterday's predictions against actual market movements, self-reflects on its errors/successes, stores these reflections in SQLite, and feeds these lessons learned back into future decision-making!

---

## 🚀 Getting Started

### Prerequisites

1. **Python 3.10+** (Ensure Python is added to your system `PATH`)
2. **Ollama** (For running local AI models)
   - Download and install Ollama from [ollama.com](https://ollama.com)
   - Run the required models (e.g. Qwen2.5 or Llama3):
     ```bash
     ollama run qwen2.5:7b
     ```

### Installation & Run

1. Clone or download this project directory.
2. Navigate to the project root and double-click `launch.bat` (on Windows) or run:
   ```bash
   # Windows
   .\launch.bat
   
   # Linux/MacOS
   ./launch.sh
   ```
   *The launcher will automatically create a virtual environment, install dependencies (`requirements.txt`), set up the database (`data/psx_memory.db`), and start the Streamlit interface.*

---

## 📁 System Architecture

- `app.py`: Main Streamlit entry point.
- `agent.py`: Orchestrator driving daily runs, predicting evaluations, and database saves.
- `core/`:
  - `data_engine.py`: Fetches and caches data from yfinance (mapped to `.KA` suffix for Karachi).
  - `shariah_engine.py`: Screening algorithms checking interest debt, liquid assets, and purifying dividends.
  - `hqm_engine.py`: Gray & Vogel's High-Quality Momentum relative percentile rank scoring.
  - `indicators.py`: Technical indicator calculations (RSI, MACD, EMA, Trailing Stop Loss).
- `memory/`:
  - `db.py`: Persistent SQLite schema for transactions, council verdicts, price history, and AI reflections.
- `ui/`: Custom tab rendering components for predictions, dashboard, and portfolio management.

---

## ⚖️ Shariah Compliance Checklist

We implement the standard 5-part Meezan / KMI screening methodology:
1. **Core Business Screen**: Disallows conventional banks, insurance, tobacco, alcohol, interest finance, gambling, etc.
2. **Debt to Assets Screen**: Interest-bearing debt must be `< 33%` of total assets.
3. **Non-Halal Income Screen**: Non-compliant revenues must be `< 5%` of total revenue.
4. **Illiquid Assets Screen**: Illiquid assets (Fixed assets, property) must exceed `25%` (or strictly `50%`) of total assets.
5. **Net Liquid Assets Screen**: Market capitalization must exceed net liquid assets (Total Assets - Total Equity).

---

## 🧠 Daily Self-Learning Loop

When you open or refresh the tool:
1. It compares yesterday's **BUY/HOLD/SELL** ratings with the actual closing price changes of the next day.
2. It classifies each prediction as a **Hit** (correct) or **Miss** (incorrect).
3. A local LLM evaluates the misses: it reviews the technical and quantitative factors at the time of the prediction and provides a critique explaining *why* it was wrong (e.g., ignoring a overbought RSI, or high debt risk).
4. These **Reflections** are saved to `psx_memory.db` and shown under the **AI Learning & Performance** tab.
5. In subsequent analyses, the AI Council pulls these reflections as a **"Lessons Learned" context**, dynamically improving its future recommendations!

---

*Disclaimer: This tool is for educational and advisory reference only. It does not constitute formal financial advice.*

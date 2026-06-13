# Changelog — PSX Advisory Agent v3 Accuracy Upgrades

All notable changes to the PSX Advisory Agent v3 codebase for improving predictive accuracy from 36.4% are documented in this file.

## [3.1.0] - 2026-06-01

### Added
- **`memory/migrations.py`**: Handles safe database migrations on startup.
  - Adds `consensus_strength` and `was_filtered` to `council_decisions`.
  - Creates the self-learning `analyst_weights` and `analyst_prediction_log` tables.
- **`memory/analyst_tracker.py`**: Implementation of the self-learning analyst weights.
  - Logs predictions, evaluates them (>5 days old) against actual market price movements, recalculates accuracy/streaks, and adjusts weights.
- **`core/psx_signals.py`**: Core PSX-specific signal enrichment.
  - State Bank of Pakistan KIBOR HTML scraping (cached 4h).
  - Relative sector momentum (10-day performance ranking).
  - Upcoming corporate earnings proximity risk flagging.
  - KSE-100 index market breadth expansion/contraction.

### Modified
- **`memory/db.py`**: 
  - Integrated `apply_migrations()` on startup.
  - Updated `save_council_decision()` to store `consensus_strength` and `was_filtered` metrics.
  - Implemented the `calculate_tiered_accuracy(lookback_days)` analytics engine.
- **`core/indicators.py`**:
  - Implemented the `detect_regime(df)` using `ta.trend.ADXIndicator` (+DI, -DI, and ADX).
- **`agent.py`**:
  - Wired Layer 2 (market regime detection) and Layer 5 (PSX signal enrichment) into the `analyse_stock()` routine.
  - Modified advisory score calculations based on regime modifiers and enrichment penalties.
  - Wired `evaluate_analyst_predictions()` in the daily analysis runner to keep self-learning weights updated.
- **`council/ollama_council.py`**:
  - Modified `ollama_chat()` to reduce model temperature to `0.1` and expand response token limit to `1500`.
  - Enforced Chain-of-Thought (CoT) preambles in all 6 analyst prompts.
  - Extracted reasoning scratchpad traces before JSON parsing.
  - Implemented the Layer 1 4/6 analyst agreement consensus filter.
  - Injected analyst weights and KIBOR/sector/earnings/breadth indicators in briefings.
- **`ui/council_tab.py`**:
  - Renders the premium **Accuracy Dashboard** at the top.
  - Displays the active **Consensus Filter Warning** in the final decision banner.
  - Implemented the responsive **Analyst Leaderboard** detailing weights, accuracy, and streaks.
- **`ui/predictions_tab.py`**:
  - Added sortable **Regime** column to the Rankings table.
  - Renders color-coded **Regime badges** in the detail header.
  - Displays the columned **PSX-Specific Signals Enrichment** panel.
- **`requirements.txt`**:
  - Added `beautifulsoup4>=4.12.0` and `lxml>=5.0.0` for SBP scraping.

### Fixed
- **PyArrow DataFrame incompatibility**: Fixed `RSI` and `Price (PKR)` mixed-type columns in `render_rankings_table` crashing Streamlit's `st.dataframe` on load. The columns now consistently store numeric float values with `None`/`NaN` representing missing values, and use Streamlit's `NumberColumn` configurations for beautiful representation and numeric sorting.
- **Console log visibility**: Restored all progress logs (data fetched, analysis runs, database migrations) in the terminal by passing `force=True` in `logging.basicConfig()`, which overrides Streamlit's internal logging hijack.

# RESET & REBUILD LOG — PSX Advisory Agent v3 Decision Layer

This log documents the comprehensive reset and rebuild of the PSX Advisory Agent v3 decision, scoring, and UI layer. These modifications resolve issues with zero BUY signals, incorrect SELL signals, ML-advisory mismatches, and fragile scraping of KMI Shariah constituents.

## 1. Root Causes Addressed

1. **Over-Gating / Overrides Stack:** Too many chained overrides (regime gates, macro gates, velocity modifiers, and multiple rating resets) were stacked sequentially in `agent.py` and `core/psx_signals.py`, collectively suppressing nearly all BUY signals.
2. **US-Calibrated Thresholds:** The system originally used US-calibrated indicator/voting thresholds (e.g., BUY > 60, SELL < 40), which are too restrictive for the high-volatility, high-spread PSX market.
3. **Rating Mismatches:** Parallel rating logic existed between `core/hqm_engine.py` and `core/scoring_engine.py`, causing contradictions between different views in the app.
4. **JavaScript Scraping Failure:** The KMI Shariah constituent scraper relied on scraping dynamic JS-rendered tables from `dps.psx.com.pk`, which returned empty elements when fetched using standard HTTP requests.
5. **ML Degradation:** The machine learning models suffered from overfitting and data-scarcity issues, producing unreliable prediction signals.

---

## 2. Core Architectural & Scoring Rebuild

### 1. Unified Verdict & Single Source of Truth
* **Authoritative Source:** `core/scoring_engine.py` was established as the single source of truth for the stock advisory verdict.
* **Agent Alignment:** In `agent.py`, the call to `hqm_engine.compute_advisory_rating()` was replaced with a call to `scoring_engine.compute_vote_score()` and `make_decision()`.

### 2. PSX-Calibrated Thresholds
* **Rule Engine Calibration:** Lowered the `BUY` threshold to `final_score >= 55` (from `> 60`) and the `SELL` threshold to `final_score < 35` (from `<= 40`) in [rule_engine.py](file:///d:/psx_agent_v3/psx_v3/core/rule_engine.py).
* **RSI Range Calibration:** Tuned standard technical indicators (e.g. RSI BUY trigger at 38, SELL at 72) to better suit PSX stock behaviors.

### 3. Simplified, Two-Stage PSX Signal Enrichment
Rebuilt `enrich_analysis` in [psx_signals.py](file:///d:/psx_agent_v3/psx_v3/core/psx_signals.py) into a clean, 2-stage system:
* **Stage 1 (Hard Disqualifiers):** Only major structural rules are allowed to override/downgrade the base decision (e.g., Non-Shariah compliance downgrades `BUY` to `HOLD`; earnings within 5 days defers `BUY` to `HOLD`).
* **Stage 2 (Score Adjustments Only):** Micro-factors adjust the numerical score but do not override the rating (e.g., high KIBOR penalty `-5`, sector laggard `-3`, sector leader bonus `+3`, market breadth contraction `-3`).

### 4. Regime Modifiers Replaced
* Removed the regime modifier override block in [agent.py](file:///d:/psx_agent_v3/psx_v3/agent.py) that suppressed BUY signals to HOLD in choppy markets.
* Market regime is now logged purely as informational context in the rationale.

---

## 3. Data & ML Layer Reliability Overhaul

### 1. Live KMI Shariah Compliance Scraper
* Switched the primary scraping target from JS-rendered HTML to the direct JSON endpoint: `https://dps.psx.com.pk/marginsymbols/KMI`.
* Integrated robust fallbacks to Meezan Bank / Al Meezan screener sites to ensure continuous compliance checking.

### 2. Machine Learning Stability
* Converted the Random Forest from a volatile 3-class model to a robust 2-class direction classifier (UP vs. NOT_UP).
* Added a data reliability guard: ML signals are labeled "unreliable" and bypassed if historical rows are < 100 or 5-fold cross-validation accuracy is < 52%.

---

## 4. UI Polish & Prediction Tracking

### 1. Capital Protection & Trend Checklists
* Integrated the **PSX Risk Prevention Matrix** and **Directional Indicators Checklist** in both [predictions_tab.py](file:///d:/psx_agent_v3/psx_v3/ui/predictions_tab.py) and [council_tab.py](file:///d:/psx_agent_v3/psx_v3/ui/council_tab.py).
* Styled with clean ASCII tables and expandable glassmorphic panels.

### 2. Performance Tracking
* Implemented `get_signal_quality_stats(days=30)` in [db.py](file:///d:/psx_agent_v3/psx_v3/memory/db.py) to aggregate and serve statistics.
* Enriched [learning_tab.py](file:///d:/psx_agent_v3/psx_v3/ui/learning_tab.py) to showcase 5-day horizon win rates, actionable signal hits, and historical reflection logs.

# Implementation Plan: PSX Advisory Agent v3 Complete Rebuild (with Auditing, Horizon, and Lifecycle Tracking)

This plan details a complete architectural reset and rebuild of the PSX Advisory Agent v3 into a single unified pipeline combining the Master Prompt requirements with the 15 specific architectural changes.

## User Review Required

> [!IMPORTANT]
> - **Unified 3-Tier Pipeline:**
>   - **Tier 1 (Quantitative Screen):** Runs mathematical checks and computes score/verdict for all 600+ stocks.
>   - **Tier 1.5 (Micro-Agent Spotter):** Single-prompt Ollama check to detect hidden structural patterns without issuing scores, ratings, or overrides. Output: `{"interesting": true, "structural_patterns": [...], "investigate_further": true, "explanation": "..."}`.
>   - **Tier 2 (AI Board Room):** Runs 6 Ollama analysts + Chairman ONLY on shortlisted candidates (top 15-20).
> - **Board Room Repositioning:** Restructured to challenge, validate, and contextualize quant recommendations (highlighting catalyst/failure risks). AI Chairman cannot override actions, Shariah status, target prices, or stop losses.
> - **Mathematical Engines:**
>   - **Confidence Engine (`confidence_engine.py`):** Derived mathematically (no LLMs) from signal agreement, anomaly strength, history, ML probability, and trend strength.
>   - **Prediction Audit Engine (`prediction_audit.py`):** Analyzes historical outcomes, failure reasons, and success rates.
>   - **Horizon Engine (`horizon_engine.py`):** Calculates holding period, target price, stop loss, and confidence interval using ATR.
>   - **Deterministic Shariah SSOT (`shariah_engine.py`):** Deterministic Meezan criteria. Evaluates defense/arms companies purely on financial metrics (no auto-fail on classification alone). Board room is restricted to notes only.
> - **Recommendation Lifecycle:** `pipeline_results` will track status (`OPEN`, `TARGET_HIT`, `STOP_HIT`, `EXPIRED`, `MANUALLY_CLOSED`).
> - **Validation & Guards:** Walk-forward validation (rolling windows) for ML. Feedback engine requires manual approval on the dashboard for weight proposals.
> - **Analysis Details Tab:** New UI tab explaining the exact "why" behind each generated recommendation.

## Proposed Changes

---

### Phase 1: Database & Data Layers

#### [MODIFY] [db.py](file:///d:/psx_agent_v3/psx_v3/memory/db.py)
* Add `pipeline_results` table storing the canonical recommendation package (`symbol`, `action`, `confidence`, `horizon`, `target_price`, `stop_loss`, `shariah_status`, `anomaly_flags`, `boardroom_summary`) and lifecycle fields (`recommendation_created_at`, `recommendation_expiry_at`, `target_hit`, `stop_hit`, `outcome_status`).
* Add `prediction_audit` table.
* Include `trading_journal`, `user_feedback`, `calibration_proposals`, `sentiment_history`, and `psx_announcements` tables.

#### [NEW] [psx_live.py](file:///d:/psx_agent_v3/psx_v3/core/psx_live.py)
* Fetch live quotes, market status, market watch, order book bid-ask depth, and announcements from `https://dps.psx.com.pk`. yfinance fallback included.
* Remove all legacy Capital Stakes references.

---

### Phase 2: Core Computational Engines

#### [NEW] [shariah_engine.py](file:///d:/psx_agent_v3/psx_v3/core/shariah_engine.py)
* Deterministic Meezan screening engine returning `status` (`COMPLIANT`, `NON_COMPLIANT`, `GRAY_AREA`), `score`, `violations`, and `gray_areas`.
* Defense/arms companies are evaluated based on financial criteria rather than auto-flagged on industry classification.
* Predictions Tab, Dashboard, Board Room, Alerts, and Reports all read from this single source of truth.

#### [NEW] [confidence_engine.py](file:///d:/psx_agent_v3/psx_v3/core/confidence_engine.py)
* Mathematical confidence calculator using signal agreement, anomaly strength, historical accuracy, ML probability, and trend strength. No LLM generation.

#### [NEW] [horizon_engine.py](file:///d:/psx_agent_v3/psx_v3/core/horizon_engine.py)
* Calculates recommended holding periods, target prices, stop losses, and confidence intervals using ATR.

#### [NEW] [prediction_audit.py](file:///d:/psx_agent_v3/psx_v3/core/prediction_audit.py)
* Audits historical predictions (predicted vs. actual outcome), outputting failure reasons, per-stock success rates, and per-indicator/anomaly success rates.

#### [NEW] [sentiment_engine.py](file:///d:/psx_agent_v3/psx_v3/core/sentiment_engine.py)
* Announcement-only sentiment analyzer utilizing disclosures, earnings, and dividend reports. Social scraping/forum buzz is disabled initially.

---

### Phase 3: ML, Pipeline, & Board Room REST

#### [MODIFY] [ml_engine.py](file:///d:/psx_agent_v3/psx_v3/core/ml_engine.py)
* Convert to 2-class problem (UP vs. NOT_UP), 200-row data guard, and pooled model training.
* Implement walk-forward validation and rolling windows instead of random train/test splits.

#### [NEW] [pipeline.py](file:///d:/psx_agent_v3/psx_v3/core/pipeline.py)
* Unified 3-Tier Pipeline (T1 Quant Screen $\rightarrow$ T1.5 Micro-Agent Spotter $\rightarrow$ T2 Board Room Debate).
* Tier 1.5 structural JSON output uses `{"interesting": true, "structural_patterns": [...], "investigate_further": true, "explanation": "..."}`. Discovery only, no scoring, no rating overrides.

#### [MODIFY] [ollama_council.py](file:///d:/psx_agent_v3/psx_v3/council/ollama_council.py)
* Reposition Board Room to challenge/validate quant recommendations. AI analysts focus on catalysts, risks of failure, and catalysts of success. Chairman summarizes debate, consensus, and disagreements, but cannot override actions, Shariah status, target prices, or stop losses. Shariah analyst limited to notes only.

---

### Phase 4: UI & Feedback Enhancements

#### [MODIFY] [ui/predictions_tab.py](file:///d:/psx_agent_v3/psx_v3/ui/predictions_tab.py)
* Sort recommendations by `FINAL_SCORE DESC, CONFIDENCE DESC`.
* Display order: BUY+COMPLIANT, BUY+GRAY AREA, HOLD, SELL.

#### [NEW] [ui/analysis_details_tab.py](file:///d:/psx_agent_v3/psx_v3/ui/analysis_details_tab.py)
* Explanation tab detailing signals, anomaly triggers, confidence breakdown, Shariah analysis, board room debate, historical performance, and recommendation lifecycle.

#### [NEW] [ui/feedback_tab.py](file:///d:/psx_agent_v3/psx_v3/ui/feedback_tab.py)
* Calibration proposals, correction forms, and post-mortems view.

#### [MODIFY] [feedback_analyser.py](file:///d:/psx_agent_v3/psx_v3/memory/feedback_analyser.py)
* Proposals are queued in the Feedback Dashboard for manual approval; the system cannot modify live weights or deploy calibrations automatically.

---

## Verification Plan

### Automated Tests
- Run offline validation scripts verifying Tier 1.5 does not score stocks or override Tier 1 decisions.
- Verify Shariah engine handles defense stocks correctly without auto-rejecting.
- Verify ML walk-forward validation executes without data leakage.

### Manual Verification
- Trace a stock from screening to debate, checking that Predictions, Dashboard, and Board Room share the identical recommendation package.

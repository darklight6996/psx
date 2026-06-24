# PSX Advisory Agent v3 - Code Audit & Implementation Plan

## Audit Findings

After comprehensive code review of the PSX Advisory Agent v3 system, several bugs, inconsistencies, and logic errors have been identified. The system has been fixed for the main RSI/ML issues but additional problems remain.

### Critical Issues:
1. **Inconsistent RSI Calculation** - The selective_ml.py module still uses the old rolling mean approach instead of the proper ta library RSI calculation
2. **Missing Error Handling** - Some functions don't properly handle edge cases and missing data
3. **Potential Data Race Conditions** - In multi-threaded contexts, data consistency may be compromised

### High Priority Issues:
1. **ML Model Accuracy Display Logic** - The predictions tab doesn't properly handle all ML status conditions
2. **Cache Invalidation** - When ML results are updated via sidebar, the cache isn't always properly invalidated
3. **Tab Navigation State** - The tab navigation system could be more robust

### Medium Priority Issues:
1. **Missing Input Validation** - Several functions don't validate inputs before processing
2. **Documentation Gaps** - Some complex functions lack clear docstrings
3. **Performance Optimization** - Certain loops could be optimized for better performance

## Implementation Plan

### Phase 1: Fix Critical Issues (Immediate)
- [ ] Update selective_ml.py to use proper RSI calculation from indicators module
- [ ] Add comprehensive error handling throughout ML modules
- [ ] Implement data validation checks in core functions

### Phase 2: Fix High Priority Issues 
- [ ] Improve ML display logic in predictions tab
- [ ] Implement proper cache invalidation for sidebar ML runs
- [ ] Enhance tab navigation robustness

### Phase 3: Address Medium Priority Issues
- [ ] Add missing input validation to key functions
- [ ] Improve docstrings and documentation
- [ ] Optimize performance-critical loops

## Detailed Implementation Steps

### Critical Issue 1: Inconsistent RSI Calculation
**File:** `core/selective_ml.py`
**Problem:** Line 32 uses `df["Close"].pct_change().rolling(14).mean().iloc[-1] * 100` instead of proper ta library RSI
**Fix:** Replace with call to `calc_rsi(df).iloc[-1]` from `core.indicators`

### Critical Issue 2: Missing Error Handling
**Files:** `core/ml_engine.py`, `core/pipeline.py`
**Problem:** Functions don't gracefully handle edge cases like empty dataframes or missing dependencies
**Fix:** Add comprehensive try-catch blocks and validation checks

### High Priority Issue 1: ML Display Logic
**File:** `ui/predictions_tab.py`
**Problem:** Incomplete handling of ML status conditions in display logic
**Fix:** Add proper handling for all ML statuses including "skipped", "error", and "insufficient_data"

### High Priority Issue 2: Cache Invalidation
**Files:** `app.py`, `core/selective_ml.py`
**Problem:** When sidebar ML runs, results aren't properly persisted to database
**Fix:** Add explicit DB update after selective ML completion

### Medium Priority Issue 1: Input Validation
**Files:** All core modules
**Problem:** Functions don't validate inputs before processing
**Fix:** Add input validation at function entry points

### Medium Priority Issue 2: Documentation
**Files:** `core/ml_engine.py`, `core/pipeline.py`
**Problem:** Missing or incomplete docstrings for complex functions
**Fix:** Add comprehensive docstrings with parameter descriptions and return values

### Medium Priority Issue 3: Performance Optimization
**Files:** `core/pipeline.py`, `core/ml_engine.py`  
**Problem:** Some loops could be optimized
**Fix:** Review and optimize data processing loops where possible

## Testing Requirements

1. **Unit Tests:** Each fixed function should have unit tests
2. **Integration Tests:** Test the end-to-end flow from daily analysis to ML prediction display
3. **Regression Tests:** Ensure existing functionality isn't broken by fixes
4. **Edge Case Tests:** Test with empty data, missing files, and error conditions

## Timeline Estimate

- Phase 1 (Critical): 2-3 hours
- Phase 2 (High Priority): 3-4 hours  
- Phase 3 (Medium Priority): 2-3 hours
- Testing & Validation: 2-3 hours
# PSX Real-Time Index Integration — Walkthrough

## Summary

Integrated live index data from the official Pakistan Stock Exchange (PSX) data portal (`dps.psx.com.pk`) into the PSX Advisory Agent v3. The system now captures real-time data for **KSE-100**, **KSE-30**, **KMI-30**, and **KSE-ALL** indices during market hours and displays them as styled ticker cards on the Streamlit dashboard.

---

## Changes Made

### New File: [psx_index_pipeline.py](file:///d:/psx_agent_v3/psx_v3/core/psx_index_pipeline.py)

Background daemon module that:
- **Scrapes the PSX homepage** using BeautifulSoup to extract index values, changes, percentages, highs, lows, and volumes
- **Falls back to JSON endpoints** (`/timeseries/int/{SYMBOL}` and `/timeseries/eod/{SYMBOL}`) if HTML parsing fails
- **Pre-seeds the cache** on first startup so the dashboard has data immediately
- **Runs a background daemon thread** that polls every 45 seconds during market hours (09:00–16:30 PKT, Mon–Fri) and writes to `data/live_index_cache.json`
- **Thread-safe** with lock-based guard against multiple tracker threads

### Modified: [psx_signals.py](file:///d:/psx_agent_v3/psx_v3/core/psx_signals.py)

Updated `get_psx_breadth()` to query `dps.psx.com.pk/timeseries/eod/KSE100` for actual historical daily closing values instead of relying solely on Yahoo Finance (which often returns "delisted" errors for `^KSE100`).

### Modified: [dashboard_tab.py](file:///d:/psx_agent_v3/psx_v3/ui/dashboard_tab.py)

Added a horizontal row of 4 styled index ticker cards at the top of the dashboard:
- Color-coded: green with ▲ for positive, red with ▼ for negative
- Shows value, change, % change, high, low, and volume
- Reads from the `live_index_cache.json` file

### Modified: [app.py](file:///d:/psx_agent_v3/psx_v3/app.py)

Starts the background index tracker daemon on app initialization.

---

## Bug Fixes

### `pct_change` always `0.0`
The HTML change text format from PSX is e.g. `"-1,310.54 (-0.75%)"`. When splitting on `(`, the percent part becomes `"-0.75%)"`. The `_clean_num()` helper stripped `%` and `,` but not `)`, causing `float("-0.75)")` to throw `ValueError` and return `0.0`. Fixed by adding `"("` and `")"` to the stripped characters.

### Streamlit `use_container_width` Deprecation
Replaced all 17 occurrences of the deprecated `use_container_width=True` parameter with `width="stretch"` across 6 files:
- `app.py`, `dashboard_tab.py`, `council_tab.py`, `predictions_tab.py`, `weekly_review_tab.py`, `backtest_tab.py`, `portfolio_tab.py`

---

## Verification Results

| Test | Result |
|------|--------|
| `fetch_live_indices_from_psx()` CLI | ✅ All 4 indices with correct values and pct_change |
| `get_psx_breadth()` CLI | ✅ KSE-100 breadth CONSOLIDATING, EMA-20 = 167,747 |
| Background thread creates cache file | ✅ `data/live_index_cache.json` created with 4 indices |
| `use_container_width` grep | ✅ 0 remaining occurrences |

### Sample Live Data (June 1, 2026 at 1:37 PM PKT)
```
KSE-100: 172,536.50 (-1,426.31 / -0.82%)
KSE-ALL: 103,606.95 (-571.66 / -0.55%)
KSE-30:   51,640.94 (-525.38 / -1.01%)
KMI-30:  248,061.79 (-2,434.68 / -0.97%)
```

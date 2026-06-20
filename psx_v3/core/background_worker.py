"""
core/background_worker.py — Thread-safe background daemon worker for non-blocking stock analysis.
Updates data/analysis_status.json to communicate status with Streamlit UI.
"""

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("background_worker")

STATUS_FILE = Path("data/analysis_status.json")

_lock = threading.Lock()
_status = {
    "running": False,
    "progress": "Idle",
    "started_at": None,
    "last_completed_at": None,
    "error": None
}

# --- Stale-run timeout: if "running" has been True for >90 minutes, auto-clear it.
# This prevents the UI rerun loop from persisting across app crashes.
MAX_RUN_DURATION_MINUTES = 90

def _is_stale_run(status: dict) -> bool:
    """Return True if the run has been 'running' for too long (crash scenario)."""
    if not status.get("running"):
        return False
    started_at = status.get("started_at")
    if not started_at:
        return True  # running=True but no start time → definitely stale
    try:
        started_dt = datetime.fromisoformat(started_at)
        elapsed = datetime.now() - started_dt
        return elapsed > timedelta(minutes=MAX_RUN_DURATION_MINUTES)
    except Exception:
        return True  # Unparseable start time → treat as stale


# Pre-load status from file on import, with stale-run check
if STATUS_FILE.exists():
    try:
        with open(STATUS_FILE, "r") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                if _is_stale_run(loaded):
                    # Clear the stale running state immediately
                    loaded["running"] = False
                    loaded["progress"] = "Cleared (stale — app likely crashed)"
                    loaded["error"] = "Previous run was abandoned (app restart or crash detected)."
                    logger.warning("Cleared stale background analysis status on startup.")
                    try:
                        with open(STATUS_FILE, "w") as wf:
                            json.dump(loaded, wf, indent=4)
                    except Exception:
                        pass
                _status.update(loaded)
    except Exception as e:
        logger.warning(f"Could not read initial background status: {e}")


def save_status_to_disk():
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(_status, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to write status file: {e}")


def update_status(running: bool = None, progress: str = None, error: str = None, last_completed: bool = False):
    with _lock:
        if running is not None:
            _status["running"] = running
        if progress is not None:
            _status["progress"] = progress
        if error is not None:
            _status["error"] = error
        if running is True and progress == "Started":
            _status["started_at"] = datetime.now().isoformat()
            _status["error"] = None
        if last_completed:
            _status["last_completed_at"] = datetime.now().isoformat()
            complete_file = Path("data/analysis_complete.json")
            try:
                with open(complete_file, "w") as f:
                    json.dump({"last_completed_at": _status["last_completed_at"]}, f)
            except Exception:
                pass
        save_status_to_disk()


def get_analysis_status() -> dict:
    with _lock:
        if not _status["running"] and STATUS_FILE.exists():
            try:
                with open(STATUS_FILE, "r") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        # Also apply stale-run check on every poll
                        if _is_stale_run(loaded):
                            loaded["running"] = False
                            loaded["progress"] = "Cleared (stale)"
                            loaded["error"] = "Previous run was abandoned."
                        _status.update(loaded)
            except Exception:
                pass
        return _status.copy()


def is_analysis_running() -> bool:
    status = get_analysis_status()
    # Extra safety: if running but stale, return False
    if status.get("running") and _is_stale_run(status):
        return False
    return status.get("running", False)


def _run_worker(watchlist, force_refresh, include_portfolio):
    try:
        update_status(running=True, progress="Started")

        # Local import to avoid circular dependency
        from agent import run_daily_analysis

        run_daily_analysis(watchlist=watchlist, force_refresh=force_refresh, include_portfolio=include_portfolio)

        update_status(running=False, progress="Completed", last_completed=True)
    except Exception as e:
        logger.exception("Background analysis failed")
        update_status(running=False, progress="Failed", error=str(e))


def start_background_analysis(watchlist=None, force_refresh=False, include_portfolio=True):
    if is_analysis_running():
        logger.warning("Background analysis is already running. Skipping request.")
        return False

    t = threading.Thread(
        target=_run_worker,
        args=(watchlist, force_refresh, include_portfolio),
        name="PSXBackgroundAnalysis",
        daemon=True
    )
    t.start()
    logger.info("Started background analysis thread.")
    return True

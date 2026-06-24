"""
core/ml_engine.py — ML Prediction Layer (Phase 2)

A clean Random Forest Classifier predicting tomorrow's price direction (UP vs. NOT_UP)
using a pooled model trained on liquid PSX stocks.

Rules:
- XGBoost is deprecated and NOT used.
- Enforce strict minimum of 200 data rows to generate any prediction.
- Walk-forward rolling window validation is used to evaluate model accuracy.
"""

import logging
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("ml_engine")

# ── Paths ─────────────────────────────────────────────────────────────────────
MODELS_DIR = Path("data/ml_models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# ── Feature engineering ───────────────────────────────────────────────────────
FEATURES = [
    "rsi",
    "macd",
    "macd_signal",
    "macd_hist",
    "return_1d",
    "return_7d",
    "volatility",
    "vol_percentile_20d",
    "price_vs_ma20",
    "volume_ratio",
    "pct_from_52w_low",
    "pct_from_52w_high",
]


def _build_feature_matrix(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Given a raw daily OHLCV DataFrame, compute all ML features for EVERY row.
    Returns a DataFrame indexed by date with one column per feature,
    plus a 'target' column (1=UP, 0=NOT_UP).
    """
    if df is None or len(df) < 60:
        return None

    d = df.copy()

    # ── Indicators ────────────────────────────────────────────────────────────
    d["return_1d"] = d["Close"].pct_change()
    d["return_7d"] = d["Close"].pct_change(periods=5)

    d["ma_20"] = d["Close"].rolling(20).mean()
    d["avg_vol_20"] = d["Volume"].rolling(20).mean()

    delta = d["Close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta.where(delta < 0, 0))
    # Use Wilder's smoothing (EWMA with alpha=1/14) instead of simple rolling mean
    gain = gain.ewm(alpha=1/14, adjust=False).mean()
    loss = loss.ewm(alpha=1/14, adjust=False).mean()
    d["rsi"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

    ema12 = d["Close"].ewm(span=12, adjust=False).mean()
    ema26 = d["Close"].ewm(span=26, adjust=False).mean()
    d["macd"] = ema12 - ema26
    d["macd_signal"] = d["macd"].ewm(span=9, adjust=False).mean()
    d["macd_hist"] = d["macd"] - d["macd_signal"]

    d["volatility"] = d["return_1d"].rolling(20).std()
    vol_rank = d["volatility"].rolling(252, min_periods=20).rank(pct=True) * 100
    d["vol_percentile_20d"] = vol_rank

    d["price_vs_ma20"] = (d["Close"] - d["ma_20"]) / d["ma_20"].replace(0, np.nan) * 100
    d["volume_ratio"] = d["Volume"] / d["avg_vol_20"].replace(0, np.nan)

    d["low_52w"] = d["Close"].rolling(252, min_periods=60).min()
    d["high_52w"] = d["Close"].rolling(252, min_periods=60).max()
    rng = (d["high_52w"] - d["low_52w"]).replace(0, np.nan)
    d["pct_from_52w_low"] = (d["Close"] - d["low_52w"]) / rng * 100
    d["pct_from_52w_high"] = (d["high_52w"] - d["Close"]) / rng * 100

    # ── Target (1-day look-ahead: 1=UP, 0=NOT_UP) ──
    # Defined as tomorrow's return > +0.5%
    future_ret = d["Close"].pct_change().shift(-1)
    d["target"] = (future_ret > 0.005).astype(int)

    d = d[FEATURES + ["target"]].dropna()
    return d


def _model_paths(symbol: str) -> tuple[Path, Path]:
    sym = symbol.upper()
    return (
        MODELS_DIR / f"{sym}_rf.joblib",
        MODELS_DIR / f"{sym}_meta.json",
    )


# ── Training ──────────────────────────────────────────────────────────────────

def train_models(symbol: str, df: pd.DataFrame, force: bool = False) -> dict:
    """
    Train and persist a RandomForest classifier for `symbol`.
    """
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import accuracy_score

    rf_path, meta_path = _model_paths(symbol)

    if not force and rf_path.exists():
        logger.info(f"[ML] Cached model found for {symbol} — skipping training")
        return {"status": "cached", "symbol": symbol}

    feat_df = _build_feature_matrix(df)
    if feat_df is None or len(feat_df) < 200:
        return {
            "status": "insufficient_data",
            "signal": "INSUFFICIENT_DATA",
            "ml_signal_reliable": False,
            "reason": f"Only {0 if feat_df is None else len(feat_df)} training rows — minimum 200 required"
        }

    X = feat_df[FEATURES].values
    y_dir = feat_df["target"].values

    tscv = TimeSeriesSplit(n_splits=5)
    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=6,
        min_samples_leaf=10,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    rf_accuracies = []
    for train_idx, val_idx in tscv.split(X):
        rf.fit(X[train_idx], y_dir[train_idx])
        preds = rf.predict(X[val_idx])
        rf_accuracies.append(accuracy_score(y_dir[val_idx], preds))

    # Final fit on ALL data
    rf.fit(X, y_dir)
    rf_cv_acc = round(float(np.mean(rf_accuracies)) * 100, 1)

    ml_signal_reliable = bool(rf_cv_acc >= 52.0)

    # Persist
    joblib.dump(rf, rf_path)

    importances = dict(zip(FEATURES, [round(float(v), 4) for v in rf.feature_importances_]))

    meta = {
        "symbol": symbol,
        "training_rows": len(feat_df),
        "rf_cv_accuracy_pct": rf_cv_acc,
        "feature_importances": importances,
        "features": FEATURES,
        "trained_at": pd.Timestamp.now().isoformat(),
        "n_classes": 2,
        "baseline_accuracy": 50.0,
        "ml_signal_reliable": ml_signal_reliable,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    logger.info(
        f"[ML] {symbol} trained — RF acc: {rf_cv_acc}% | reliable: {ml_signal_reliable}"
    )
    return {"status": "trained", **meta}


# ── Inference ─────────────────────────────────────────────────────────────────

def predict(symbol: str, snapshot: dict, df: pd.DataFrame) -> dict:
    """
    Load (or train if missing) models and produce ML signals for `symbol`.
    """
    import joblib

    # Enforce strict minimum of 200 rows of historical data
    if df is None or len(df) < 200:
        return {
            "status": "insufficient_data",
            "direction": "NOT_UP",
            "direction_proba": {"NOT_UP": 1.0, "UP": 0.0},
            "expected_move_pct": 0.0,
            "confidence_pct": 0.0,
            "top_features": {},
            "model_accuracy_pct": 0.0,
            "ml_signal_reliable": False,
            "reason": f"Only {0 if df is None else len(df)} historical rows — minimum 200 required"
        }

    pooled_rf_path = MODELS_DIR / "pooled_rf.joblib"
    pooled_meta_path = MODELS_DIR / "pooled_meta.json"
    rf_path, meta_path = _model_paths(symbol)

    use_pooled = pooled_rf_path.exists() and pooled_meta_path.exists()
    status = "ok"

    if use_pooled:
        try:
            rf = joblib.load(pooled_rf_path)
            with open(pooled_meta_path) as f:
                meta = json.load(f)
        except Exception as e:
            logger.error(f"[ML] Failed to load pooled model: {e}")
            use_pooled = False

    if not use_pooled:
        # Fall back to per-symbol model
        if not rf_path.exists():
            logger.info(f"[ML] No cached model for {symbol} — auto-training now...")
            train_res = train_models(symbol, df)
            if train_res.get("status") in ("error", "insufficient_data"):
                return {
                    "status": train_res.get("status"),
                    "direction": "NOT_UP",
                    "direction_proba": {"NOT_UP": 1.0, "UP": 0.0},
                    "expected_move_pct": 0.0,
                    "confidence_pct": 0.0,
                    "top_features": {},
                    "model_accuracy_pct": 0.0,
                    "ml_signal_reliable": False,
                    "reason": train_res.get("reason", "Training failed")
                }
            status = "trained_now"

        try:
            rf = joblib.load(rf_path)
            if meta_path.exists():
                with open(meta_path) as f:
                    meta = json.load(f)
            else:
                meta = {}
        except Exception as e:
            logger.error(f"[ML] Failed to load per-symbol model for {symbol}: {e}")
            return {
                "status": "error",
                "direction": "NOT_UP",
                "direction_proba": {"NOT_UP": 1.0, "UP": 0.0},
                "expected_move_pct": 0.0,
                "confidence_pct": 0.0,
                "top_features": {},
                "model_accuracy_pct": 0.0,
                "ml_signal_reliable": False,
                "reason": str(e)
            }

    # Build feature row from the DataFrame (H-3 fix: do not use the sparse snapshot dict)
    # The snapshot dict only has 3 of 12 features populated; derive all features from df
    feat_df = _build_feature_matrix(df)
    if feat_df is not None and not feat_df.empty:
        # Use the most recent row of the full computed feature matrix
        last_row = feat_df.iloc[-1]
        row = {f: float(last_row[f]) for f in FEATURES}
        logger.debug(f"[ML] {symbol}: using DataFrame-derived features for inference")
    else:
        # Fallback: sparse snapshot (degraded but not crashing)
        logger.warning(f"[ML] {symbol}: _build_feature_matrix returned empty — falling back to sparse snapshot")
        price = snapshot.get("price", 1.0)
        ma_20 = snapshot.get("ma_20", price)
        avg_vol = snapshot.get("avg_volume_20d", snapshot.get("volume", 1))
        low_52w = snapshot.get("low_52w", price)
        high_52w = snapshot.get("high_52w", price)
        rng = (high_52w - low_52w) or 1.0
        row = {
            "rsi":               snapshot.get("rsi", 50.0),
            "macd":              snapshot.get("macd", 0.0),
            "macd_signal":       snapshot.get("macd_signal", 0.0),
            "macd_hist":         snapshot.get("macd", 0.0) - snapshot.get("macd_signal", 0.0),
            "return_1d":         snapshot.get("return_1d", 0.0),
            "return_7d":         snapshot.get("return_7d", 0.0),
            "volatility":        snapshot.get("volatility", 0.01),
            "vol_percentile_20d":snapshot.get("vol_percentile_20d", 50.0),
            "price_vs_ma20":     (price - ma_20) / max(ma_20, 1) * 100,
            "volume_ratio":      snapshot.get("volume", 1) / max(avg_vol, 1),
            "pct_from_52w_low":  (price - low_52w) / rng * 100,
            "pct_from_52w_high": (high_52w - price) / rng * 100,
        }

    X_live = np.array([[row[f] for f in FEATURES]])

    # Inference
    classes = rf.classes_
    proba = rf.predict_proba(X_live)[0]

    proba_dict = {"NOT_UP": 0.5, "UP": 0.5}
    for cls, p in zip(classes, proba):
        if cls == 1 or cls == "UP":
            proba_dict["UP"] = round(float(p), 3)
        else:
            proba_dict["NOT_UP"] = round(float(p), 3)

    pred_val = rf.predict(X_live)[0]
    direction = "UP" if (pred_val == 1 or pred_val == "UP") else "NOT_UP"
    confidence = round(float(proba_dict[direction]) * 100, 1)

    if confidence >= 65:
        signal_strength = "STRONG"
    elif confidence >= 50:
        signal_strength = "MODERATE"
    else:
        signal_strength = "WEAK"

    top_features = dict(
        sorted(meta.get("feature_importances", {}).items(), key=lambda x: x[1], reverse=True)[:5]
    )

    return {
        "direction":          direction,
        "direction_proba":    proba_dict,
        "expected_move_pct":  0.0,  # Deprecated
        "confidence_pct":     confidence,
        "top_features":       top_features,
        "model_accuracy_pct": meta.get("rf_cv_accuracy_pct", 0.0),
        "training_rows":      meta.get("training_rows", 0),
        "signal_strength":    signal_strength,
        "status":             status,
        "ml_signal_reliable": meta.get("ml_signal_reliable", False),
    }


def force_retrain(symbol: str, df: pd.DataFrame) -> dict:
    return train_models(symbol, df, force=True)


def get_model_metadata(symbol: str) -> dict:
    _, meta_path = _model_paths(symbol)
    if meta_path.exists():
        with open(meta_path) as f:
            return json.load(f)
    return {}


def train_pooled_model(symbols: list[str], dfs: dict[str, pd.DataFrame]) -> dict:
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import accuracy_score

    feat_dfs = []
    for sym in symbols:
        df = dfs.get(sym)
        if df is None or df.empty:
            continue
        feat_df = _build_feature_matrix(df)
        if feat_df is not None and not feat_df.empty:
            feat_df = feat_df.copy()
            feat_df["symbol"] = sym
            feat_dfs.append(feat_df)

    if not feat_dfs:
        logger.warning("[ML] No feature matrices built for pooled model")
        return {"status": "error", "reason": "No data available for pooled model"}

    pooled_df = pd.concat(feat_dfs)
    pooled_df = pooled_df.sort_index()
    pooled_df = pooled_df.dropna(subset=FEATURES + ["target"])

    if len(pooled_df) < 200:
        logger.warning(f"[ML] Insufficient data for pooled model: {len(pooled_df)} rows")
        return {
            "status": "insufficient_data",
            "signal": "INSUFFICIENT_DATA",
            "ml_signal_reliable": False,
            "reason": f"Only {len(pooled_df)} training rows in pooled dataset — minimum 200 required"
        }

    X = pooled_df[FEATURES].values
    y_dir = pooled_df["target"].values

    tscv = TimeSeriesSplit(n_splits=5)
    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=6,
        min_samples_leaf=10,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1
    )

    rf_accuracies = []
    for train_idx, val_idx in tscv.split(X):
        rf.fit(X[train_idx], y_dir[train_idx])
        preds = rf.predict(X[val_idx])
        rf_accuracies.append(accuracy_score(y_dir[val_idx], preds))

    rf.fit(X, y_dir)
    rf_cv_acc = round(float(np.mean(rf_accuracies)) * 100, 1)
    ml_signal_reliable = bool(rf_cv_acc >= 52.0)

    pooled_rf_path = MODELS_DIR / "pooled_rf.joblib"
    pooled_meta_path = MODELS_DIR / "pooled_meta.json"

    joblib.dump(rf, pooled_rf_path)

    importances = dict(zip(FEATURES, [round(float(v), 4) for v in rf.feature_importances_]))

    meta = {
        "symbol": "POOLED",
        "training_rows": len(pooled_df),
        "rf_cv_accuracy_pct": rf_cv_acc,
        "feature_importances": importances,
        "trained_at": pd.Timestamp.now().isoformat(),
        "n_classes": 2,
        "baseline_accuracy": 50.0,
        "ml_signal_reliable": ml_signal_reliable,
        "features": FEATURES,
    }

    with open(pooled_meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    logger.info(f"[ML] Pooled model trained — RF acc: {rf_cv_acc}% | reliable: {ml_signal_reliable}")
    return {"status": "trained", **meta}


def ensure_pooled_model_exists(symbols: list[str]) -> dict:
    pooled_rf_path = MODELS_DIR / "pooled_rf.joblib"
    pooled_meta_path = MODELS_DIR / "pooled_meta.json"

    if pooled_rf_path.exists() and pooled_meta_path.exists():
        try:
            with open(pooled_meta_path) as f:
                meta = json.load(f)
            trained_at = pd.Timestamp(meta.get("trained_at"))
            age_days = (pd.Timestamp.now() - trained_at).days
            if age_days < 7:
                logger.info(f"[ML] Pooled model is {age_days} days old (< 7 days) — skipping retraining")
                return {"status": "cached", "age_days": age_days}
        except Exception as e:
            logger.warning(f"[ML] Failed to read pooled model age: {e}. Retraining...")

    logger.info("[ML] Training pooled model on watchlist data...")
    from core.data_engine import fetch_ohlcv
    dfs = {}
    for sym in symbols:
        try:
            df = fetch_ohlcv(sym, period="2y", interval="1d", force_refresh=False)
            if df is not None and not df.empty:
                dfs[sym] = df
        except Exception as e:
            logger.warning(f"[ML] Failed to fetch daily EOD data for {sym} to build pooled features: {e}")

    return train_pooled_model(symbols, dfs)

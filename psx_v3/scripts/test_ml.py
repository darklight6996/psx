from core.data_engine import fetch_ohlcv
from core.ml_engine import train_models, predict
from data.clean_market_data import compute_indicators
import json

print("Fetching SYS historical data...")
df = fetch_ohlcv("SYS", period="2y", interval="1d")
print(f"Got {len(df)} rows")

print("Training models...")
meta = train_models("SYS", df, force=True)
print(f"Training result: {meta['status']}")
print(f"  RF CV accuracy: {meta['rf_cv_accuracy_pct']}%")

print(f"  Training rows:  {meta['training_rows']}")
print()

print("Running inference...")
snap = compute_indicators(df)
result = predict("SYS", snap, df)
print(f"  Direction:       {result['direction']} ({result['confidence_pct']}%)")
print(f"  Expected move:   {result['expected_move_pct']:+.2f}%")
print(f"  Signal strength: {result['signal_strength']}")
print(f"  Top features:    {list(result['top_features'].keys())[:3]}")
print()
print("All done!")

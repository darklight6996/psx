import pandas as pd
import numpy as np

def compute_indicators(df: pd.DataFrame) -> dict:
    """
    Takes a DataFrame with ['Open', 'High', 'Low', 'Close', 'Volume']
    and computes all technical indicators needed for the market schema.
    Returns the latest row as a dictionary.
    """
    if df is None or len(df) < 20:
        return {}
        
    df = df.copy()
    
    # 1. Returns
    df['return_1d'] = df['Close'].pct_change()
    df['return_7d'] = df['Close'].pct_change(periods=5) # 5 trading days ~ 7 calendar days
    
    # 2. Moving Averages
    df['ma_20'] = df['Close'].rolling(window=20).mean()
    df['avg_volume_20d'] = df['Volume'].rolling(window=20).mean()
    
    # 3. Volatility (20-day standard deviation of daily returns)
    df['volatility'] = df['return_1d'].rolling(window=20).std()
    
    # Volatility percentile: rank current volatility vs past year
    vol_history = df['volatility'].dropna()
    if not vol_history.empty:
        current_vol = vol_history.iloc[-1]
        df['vol_percentile_20d'] = (vol_history < current_vol).mean() * 100
    else:
        df['vol_percentile_20d'] = 50.0

    # 4. RSI (14-day)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # 5. MACD
    ema_12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema_12 - ema_26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    
    # 6. 52-week High/Low (252 trading days)
    df['low_52w'] = df['Close'].rolling(window=252, min_periods=20).min()
    df['high_52w'] = df['Close'].rolling(window=252, min_periods=20).max()
    
    # Extract latest row
    latest = df.iloc[-1]
    
    # Fallback to prevent NaN
    def clean_val(val, default=0.0):
        if pd.isna(val) or np.isinf(val):
            return default
        return float(val)

    # Previous close is the close of the row before the latest
    prev_close = df['Close'].iloc[-2] if len(df) >= 2 else latest['Close']
    
    return {
        "price": clean_val(latest['Close']),
        "open": clean_val(latest['Open']),
        "prev_close": clean_val(prev_close),
        "volume": clean_val(latest['Volume']),
        "avg_volume_20d": clean_val(latest['avg_volume_20d']),
        "rsi": clean_val(latest['rsi'], 50.0), # neutral RSI default
        "macd": clean_val(latest['macd']),
        "macd_signal": clean_val(latest['macd_signal']),
        "return_1d": clean_val(latest['return_1d']),
        "return_7d": clean_val(latest['return_7d']),
        "volatility": clean_val(latest['volatility']),
        "vol_percentile_20d": clean_val(latest['vol_percentile_20d'], 50.0),
        "ma_20": clean_val(latest['ma_20'], latest['Close']),
        "low_52w": clean_val(latest['low_52w'], latest['Close']),
        "high_52w": clean_val(latest['high_52w'], latest['Close'])
    }

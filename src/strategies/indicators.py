"""
Technical indicators for trading strategies
"""
import pandas as pd
import numpy as np
from typing import Optional

def sma(data: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average"""
    return data.rolling(window=period).mean()

def ema(data: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average"""
    return data.ewm(span=period, adjust=False).mean()

def rsi(data: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index"""
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def macd(data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD indicator"""
    exp1 = data.ewm(span=fast, adjust=False).mean()
    exp2 = data.ewm(span=slow, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {
        'macd': macd_line,
        'signal': signal_line,
        'histogram': histogram
    }

def bollinger_bands(data: pd.Series, period: int = 20, std_dev: float = 2) -> dict:
    """Bollinger Bands"""
    middle = data.rolling(window=period).mean()
    std = data.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    return {
        'upper': upper,
        'middle': middle,
        'lower': lower,
        'bandwidth': (upper - lower) / middle
    }

def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range"""
    high_low = high - low
    high_close = np.abs(high - close.shift())
    low_close = np.abs(low - close.shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def volume_profile(volume: pd.Series, price: pd.Series, bins: int = 20) -> dict:
    """Volume Profile"""
    price_bins = pd.cut(price, bins=bins)
    vp = volume.groupby(price_bins).sum()
    return {
        'profile': vp,
        'poc': vp.idxmax()  # Point of Control
    }

def detect_vcp(df: pd.DataFrame, min_contractions: int = 3) -> pd.Series:
    """
    Detect Volatility Contraction Pattern (VCP)
    Minervini's pattern: multiple contractions with decreasing volatility
    """
    # Calculate range as percentage of price
    df['range_pct'] = (df['high'] - df['low']) / df['close'] * 100

    # Find local minima in range (contractions)
    df['range_sma'] = sma(df['range_pct'], 10)
    df['is_contraction'] = df['range_pct'] < df['range_sma']

    # Count consecutive contractions
    contraction_count = df['is_contraction'].astype(int).groupby(
        (df['is_contraction'] != df['is_contraction'].shift()).cumsum()
    ).cumsum()

    return contraction_count >= min_contractions

def stage_analysis(df: pd.DataFrame, ma_period: int = 30) -> pd.Series:
    """
    Stan Weinstein Stage Analysis
    Returns stage: 1 (base), 2 (advance), 3 (top), 4 (decline)
    """
    df['ma'] = sma(df['close'], ma_period)
    df['ma_slope'] = df['ma'].diff(5) / df['ma'].shift(5) * 100

    # Stage classification based on MA slope and price position
    conditions = [
        (df['close'] > df['ma']) & (df['ma_slope'] > 0),  # Stage 2: Advancing
        (df['close'] < df['ma']) & (df['ma_slope'] < 0),  # Stage 4: Declining
        (df['close'] > df['ma']) & (df['ma_slope'].abs() < 0.5),  # Stage 3: Topping
        (df['close'] < df['ma']) & (df['ma_slope'].abs() < 0.5),  # Stage 1: Basing
    ]
    choices = [2, 4, 3, 1]

    return pd.Series(np.select(conditions, choices, default=1), index=df.index)

def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> dict:
    """SuperTrend indicator"""
    hl2 = (df['high'] + df['low']) / 2
    atr_val = atr(df['high'], df['low'], df['close'], period)

    upper_band = hl2 + (multiplier * atr_val)
    lower_band = hl2 - (multiplier * atr_val)

    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)

    for i in range(len(df)):
        if i == 0:
            supertrend.iloc[i] = upper_band.iloc[i]
            direction.iloc[i] = 1
        else:
            if df['close'].iloc[i] > supertrend.iloc[i-1]:
                supertrend.iloc[i] = lower_band.iloc[i]
                direction.iloc[i] = 1
            else:
                supertrend.iloc[i] = upper_band.iloc[i]
                direction.iloc[i] = -1

    return {
        'supertrend': supertrend,
        'direction': direction
    }

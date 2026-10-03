"""Minimal indicator set — only what the trend-following strategy needs."""
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    result = 100 - (100 / (1 + rs))
    return result.where(avg_loss != 0, 100.0)


def donchian_high(high: pd.Series, period: int) -> pd.Series:
    """Highest high over the prior `period` bars, excluding today -- shift(1)
    before rolling so "today breaks out" can be tested against a channel
    that doesn't include today's own bar."""
    return high.shift(1).rolling(period).max()


def donchian_low(low: pd.Series, period: int) -> pd.Series:
    return low.shift(1).rolling(period).min()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()

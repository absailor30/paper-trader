import numpy as np
import pandas as pd

from paper_trader.strategy.indicators import atr, rsi, sma


def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5])
    result = sma(s, 3)
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == 2.0
    assert result.iloc[4] == 4.0


def test_atr_positive_and_stable_on_flat_series():
    high = pd.Series([101.0] * 20)
    low = pd.Series([99.0] * 20)
    close = pd.Series([100.0] * 20)
    result = atr(high, low, close, period=14)
    assert (result.dropna() > 0).all()
    assert abs(result.iloc[-1] - 2.0) < 0.01


def test_rsi_bounded_between_0_and_100():
    close = pd.Series(100 + np.sin(np.arange(60) / 3) * 5)
    result = rsi(close, period=14)
    valid = result.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_rsi_high_on_steady_gains_low_on_steady_losses():
    up = pd.Series(np.linspace(100, 150, 30))
    down = pd.Series(np.linspace(150, 100, 30))
    assert rsi(up, 14).iloc[-1] > 70
    assert rsi(down, 14).iloc[-1] < 30

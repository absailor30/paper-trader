import pandas as pd

from paper_trader.strategy.indicators import atr, sma


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

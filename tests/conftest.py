"""Deterministic synthetic OHLCV fixtures — no network, no randomness, no flakiness."""
import numpy as np
import pandas as pd
import pytest


def _make_ohlcv(close: np.ndarray, symbol: str, start="2023-01-01") -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=len(close), freq="B")
    noise = np.abs(np.sin(np.arange(len(close)))) * (close * 0.005) + 0.01
    high = close + noise
    low = close - noise
    volume = np.full(len(close), 1_000_000.0)
    df = pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )
    df["symbol"] = symbol
    df.index.name = "date"
    return df


@pytest.fixture
def uptrend_data() -> pd.DataFrame:
    """250 flat/declining bars (lets SMA200 settle), then a 300-bar shallow
    uptrend with an oscillation superimposed whose amplitude (5) exceeds
    the SMA50's typical lag behind the trend (~2.5), so price repeatedly
    crosses back above its 50 SMA after the golden cross, producing
    multiple entry signals. A perfectly smooth monotonic trend, or too
    small an oscillation relative to the trend's slope, crosses its own
    SMA only once (or never) after the cross and won't reproduce this."""
    flat = 100 - np.linspace(0, 5, 250)
    trend = flat[-1] + np.linspace(0, 30, 300)
    base = np.concatenate([flat, trend])
    oscillation = np.sin(np.arange(len(base)) * (2 * np.pi / 15)) * 5.0
    close = base + oscillation
    return _make_ohlcv(close, "TEST")


@pytest.fixture
def flat_data() -> pd.DataFrame:
    """No trend at all — the strategy should never signal a BUY on this."""
    close = 100 + np.sin(np.arange(300) / 10) * 0.5
    return _make_ohlcv(close, "FLAT")


@pytest.fixture
def short_data() -> pd.DataFrame:
    """Too few bars for any indicator to be meaningful."""
    close = np.linspace(100, 110, 30)
    return _make_ohlcv(close, "SHORT")

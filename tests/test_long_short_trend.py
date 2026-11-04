import numpy as np
import pandas as pd

from paper_trader.strategy.long_short_trend import describe, ls_states
from tests.conftest import _make_ohlcv


def _df(close):
    return _make_ohlcv(np.asarray(close, dtype=float), "X")


def test_goes_long_on_breakout_exits_on_channel_break():
    close = np.concatenate([np.full(70, 100.0), np.linspace(100, 140, 30), np.linspace(140, 100, 30)])
    df = _df(close)
    st = ls_states(df["close"], df["high"], df["low"], 55, 20)
    assert st.iloc[:70].eq(0).all() and (st.iloc[70:100] == 1).any() and st.iloc[-1] != 1  # long was exited (it may even flip short once the 55d low breaks)


def test_goes_short_on_breakdown_only_when_allowed():
    close = np.concatenate([np.full(70, 100.0), np.linspace(100, 60, 40)])
    df = _df(close)
    both = ls_states(df["close"], df["high"], df["low"], 55, 20, allow_short=True)
    longonly = ls_states(df["close"], df["high"], df["low"], 55, 20, allow_short=False)
    assert (both == -1).any() and (longonly == -1).sum() == 0 and longonly.eq(0).all()


def test_flip_long_to_short_and_no_lookahead():
    close = np.concatenate([np.full(70, 100.0), np.linspace(100, 130, 25), np.linspace(130, 50, 60)])
    df = _df(close)
    st = ls_states(df["close"], df["high"], df["low"], 55, 20)
    assert (st == 1).any() and (st == -1).any()
    # the state at bar t uses only data up to t: truncating the future must not change earlier states
    cut = ls_states(df["close"].iloc[:100], df["high"].iloc[:100], df["low"].iloc[:100], 55, 20)
    assert (cut.values == st.iloc[:100].values).all()


def test_describe_regime_and_distances():
    df = _df(np.concatenate([np.full(70, 100.0), np.linspace(100, 130, 30)]))
    d = describe(df, 55, 20)
    assert d["state"] == "LONG" and d["to_short_pct"] < 0 < d["to_long_pct"] + 1e-9 or d["to_long_pct"] <= 0
    assert describe(_df(np.full(10, 100.0))) is None

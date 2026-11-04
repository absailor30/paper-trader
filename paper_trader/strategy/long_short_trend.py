"""
Long/short Donchian trend following for futures-style instruments (they can be shorted, unlike the stock engine).
  enter long  : close > prior `entry`-bar high      enter short : close < prior `entry`-bar low   (if allow_short)
  exit long   : close < prior `exit_`-bar low       exit short  : close > prior `exit_`-bar high
Single source of truth for the backtest (scripts/futures_search.py) and the futures watch, so they cannot drift apart.
State is the position the rule would hold AFTER each bar's close: +1 long, -1 short, 0 flat.
"""
from typing import Optional

import numpy as np
import pandas as pd


def ls_states(close: pd.Series, high: pd.Series, low: pd.Series, entry: int = 55, exit_: int = 20,
              allow_short: bool = True) -> pd.Series:
    hh = high.shift(1).rolling(entry).max()
    ll = low.shift(1).rolling(entry).min()
    xl = low.shift(1).rolling(exit_).min()     # long exit channel
    xh = high.shift(1).rolling(exit_).max()    # short exit channel
    out = np.zeros(len(close))
    state = 0
    for i, (c, h, l, a, b) in enumerate(zip(close.values, hh.values, ll.values, xl.values, xh.values)):
        if np.isnan(c):
            out[i] = state
            continue
        if state == 1 and not np.isnan(a) and c < a:
            state = 0
        elif state == -1 and not np.isnan(b) and c > b:
            state = 0
        if state == 0:
            if not np.isnan(h) and c > h:
                state = 1
            elif allow_short and not np.isnan(l) and c < l:
                state = -1
        out[i] = state
    return pd.Series(out, index=close.index)


def describe(df: pd.DataFrame, entry: int = 55, exit_: int = 20, allow_short: bool = True) -> Optional[dict]:
    """Current regime + how far price is from flipping, for the dashboard: {'state', 'since', 'to_long_pct', 'to_short_pct'}."""
    if df is None or len(df) < entry + 2:
        return None
    st = ls_states(df["close"], df["high"], df["low"], entry, exit_, allow_short)
    cur = int(st.iloc[-1])
    changed = st[st != cur]
    since = str(st.index[-1].date()) if changed.empty else str(st.index[st.index.get_loc(changed.index[-1]) + 1].date())
    price = float(df["close"].iloc[-1])
    hi = float(df["high"].shift(1).rolling(entry).max().iloc[-1])
    lo = float(df["low"].shift(1).rolling(entry).min().iloc[-1])
    return {"state": {1: "LONG", -1: "SHORT", 0: "FLAT"}[cur], "since": since,
            "to_long_pct": (hi / price - 1) * 100, "to_short_pct": (lo / price - 1) * 100}

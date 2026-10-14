"""
Cross-sectional commodity rotation (CHECKPOINT.md "Commodities: portfolio-level tests"): at each
month-end hold the `top` funds with the best `lookback`-day return, but only funds that are up over
that window AND above their own SMA(`trend`). Everything else is cash. Equal weight per fund.
scripts/commodities_portfolio_search.py:rotation_weights is the backtested twin; a test keeps the
two in agreement.
"""
from typing import List

import pandas as pd


def rotation_targets(close: pd.DataFrame, top: int = 3, lookback: int = 126, trend: int = 200) -> List[str]:
    """`close`: one column per fund, rows up to and including the decision bar (last row)."""
    if len(close) <= max(lookback, trend):
        return []
    last = close.iloc[-1]
    mom = last / close.iloc[-1 - lookback] - 1
    ok = (mom > 0) & (last > close.rolling(trend).mean().iloc[-1])
    return list(mom.where(ok).dropna().nlargest(top).index)


def last_month_end(index: pd.DatetimeIndex):
    """Last bar of the most recent month that is COMPLETE (a later month has started), else None."""
    months = pd.Series(index, index=index).groupby([index.year, index.month]).max()
    return months.iloc[-2] if len(months) >= 2 else None

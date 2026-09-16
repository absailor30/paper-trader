"""
Momentum / relative-strength rotation.

Unlike TrendFollowingStrategy and MeanReversionStrategy, this doesn't
evaluate one symbol in isolation -- it ranks the whole universe against
each other by trailing return and rotates into the strongest names. That
cross-sectional ranking doesn't fit the single-symbol Strategy interface
(strategy/base.py), so it isn't a Strategy subclass; it's driven directly
by paper_trader/backtest/rotation_backtest.py.
"""
from typing import Dict, List

import pandas as pd

from paper_trader.config import settings


def compute_momentum(prices: pd.Series, lookback: int) -> pd.Series:
    """Trailing `lookback`-bar return at every point (NaN where insufficient history)."""
    return prices / prices.shift(lookback) - 1


def select_top_momentum(momentum_today: Dict[str, float]) -> List[str]:
    """
    Rank symbols by momentum and return up to rotation_top_n whose momentum
    clears rotation_min_momentum. Weak/negative-momentum names are excluded
    even if that leaves fewer than top_n selected -- rotation should hold
    cash rather than force capital into a universe with no real momentum.
    """
    ranked = sorted(momentum_today.items(), key=lambda kv: kv[1], reverse=True)
    return [
        symbol
        for symbol, momentum in ranked[: settings.rotation_top_n]
        if momentum > settings.rotation_min_momentum
    ]

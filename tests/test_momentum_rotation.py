import numpy as np
import pandas as pd

from paper_trader.strategy.momentum_rotation import compute_momentum, select_top_momentum


def test_compute_momentum_basic():
    prices = pd.Series([100, 105, 110, 120, 130])
    result = compute_momentum(prices, lookback=2)

    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert abs(result.iloc[2] - 0.10) < 1e-9          # 110/100 - 1
    assert abs(result.iloc[4] - (130 / 110 - 1)) < 1e-9


def test_select_top_momentum_ranks_descending_and_excludes_negative():
    momentum = {"A": 0.20, "B": 0.10, "C": 0.05, "D": -0.02, "E": 0.15}
    selected = select_top_momentum(momentum)
    # default rotation_top_n=5, rotation_min_momentum=0.0: all positive
    # names selected, ranked by momentum descending; D excluded.
    assert selected == ["A", "E", "B", "C"]


def test_select_top_momentum_respects_top_n(monkeypatch):
    from paper_trader.config import settings

    monkeypatch.setattr(settings, "rotation_top_n", 2)
    momentum = {"A": 0.20, "B": 0.10, "C": 0.05}
    assert select_top_momentum(momentum) == ["A", "B"]


def test_select_top_momentum_empty_when_nothing_clears_threshold(monkeypatch):
    from paper_trader.config import settings

    monkeypatch.setattr(settings, "rotation_min_momentum", 0.5)
    momentum = {"A": 0.20, "B": 0.10}
    assert select_top_momentum(momentum) == []

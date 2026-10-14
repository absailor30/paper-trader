import numpy as np
import pytest

from paper_trader.config import settings
from paper_trader.confidence import blend, position_pct, rule_confidence
from paper_trader.execution.paper_trader import PaperTrader
from paper_trader.orchestrator import size_position
from tests.conftest import _make_ohlcv


def _trader(cash=100.0):
    return PaperTrader(cash, settings.commission_rate, settings.slippage_rate)


def _uptrend(n=260):
    return _make_ohlcv(np.linspace(100, 160, n), "UP")


def _downtrend(n=260):
    return _make_ohlcv(np.linspace(160, 100, n), "DN")


def test_strong_uptrend_scores_higher_than_downtrend():
    up, down = rule_confidence(_uptrend()), rule_confidence(_downtrend())
    assert up.score > 0.6 > 0.3 > down.score or up.score > down.score + 0.3
    assert 0.0 <= down.score <= up.score <= 1.0
    assert set(up.parts) == {"trend", "momentum", "strength", "calm"}


def test_too_little_history_is_neutral():
    assert rule_confidence(_make_ohlcv(np.linspace(100, 110, 10), "X")).score == 0.5


def test_ramp_hits_the_agreed_anchor_points_in_crypto():
    assert position_pct(0.30, "CRYPTO") == pytest.approx(0.05)
    assert position_pct(0.55, "CRYPTO") == pytest.approx(0.10)
    assert position_pct(0.70, "CRYPTO") == pytest.approx(settings.max_position_size)
    assert position_pct(0.90, "CRYPTO") == pytest.approx(settings.max_position_size)
    assert position_pct(1.00, "CRYPTO") == pytest.approx(settings.confidence_max_size) == pytest.approx(0.15)


def test_ramp_is_smooth_and_never_decreasing():
    grid = [position_pct(x / 100, "CRYPTO") for x in range(30, 101)]
    assert all(b >= a - 1e-12 for a, b in zip(grid, grid[1:]))
    assert max(b - a for a, b in zip(grid, grid[1:])) < 0.01  # no cliffs between neighbouring scores


def test_below_minimum_confidence_is_skipped_in_every_market():
    for m in ("US", "INDIA", "CRYPTO"):
        assert position_pct(settings.confidence_min - 0.01, m) == 0.0


def test_us_is_flat_india_is_down_only_crypto_gets_the_full_ramp():
    base = settings.max_position_size
    assert position_pct(0.4, "US") == position_pct(0.95, "US") == base
    assert position_pct(0.95, "INDIA") == base and position_pct(0.4, "INDIA") < base
    assert position_pct(1.0, "CRYPTO") > base > position_pct(0.4, "CRYPTO")
    assert position_pct(None, "CRYPTO") == base


def test_blend_uses_jev_when_available():
    assert blend(0.8, None) == 0.8
    assert blend(0.8, 0.4) == pytest.approx(0.6)


def test_expensive_us_stock_gets_12_percent_not_half_the_account():
    t = _trader(100.0)
    qty = size_position(t, 614.91)  # AMD price on the day it took ~$50
    assert 0 < qty * 614.91 <= 100.0 * settings.max_position_size + 0.05


def test_higher_confidence_buys_more():
    t = _trader(100.0)
    low = size_position(t, 50.0, confidence=0.4, market="CRYPTO")
    high = size_position(t, 50.0, confidence=0.95, market="CRYPTO")
    assert 0 < low < high
    assert high * 50.0 <= 100.0 * settings.confidence_max_size + 0.05


def test_below_minimum_confidence_skips():
    assert size_position(_trader(100.0), 50.0, confidence=settings.confidence_min - 0.05, market="CRYPTO") == 0.0


def test_india_one_share_only_if_under_ceiling():
    t = _trader(10_000.0)
    assert size_position(t, 1_900.0, india=True) == 1.0      # 19% < 20% ceiling, above the 12% target
    assert size_position(t, 3_700.0, india=True) == 0.0      # 37% > ceiling
    assert size_position(t, 300.0, india=True) == 3.0        # floor(1200 / 300.45 incl. costs) = 3, not 4


def test_buying_more_of_a_held_symbol_adds_with_weighted_average_entry():
    t = _trader(1000.0)
    t.place_order("b1", "AAA", "BUY", 2.0, 100.0, "S", stop_loss=90.0)
    t.place_order("b2", "AAA", "BUY", 2.0, 120.0, "S")
    pos = t.portfolio.positions["AAA"]
    assert pos["quantity"] == 4.0
    assert 108.0 < pos["entry_price"] < 112.0   # about (100 + 120) / 2 plus costs
    assert pos["stop_loss"] == 90.0             # original stop kept when no new one is given

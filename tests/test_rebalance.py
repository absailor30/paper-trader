import pytest

from paper_trader import rebalance
from paper_trader.config import settings
from paper_trader.execution.paper_trader import PaperTrader


def _live_like_us_account():
    """The real 2026-10-14 US account: two ~$50 positions, two 0.0001-share scraps, 1 cent of cash."""
    t = PaperTrader(100.0, settings.commission_rate, settings.slippage_rate)
    t.portfolio.capital = 0.01
    for sym, qty, entry, now in (("QQQ", 0.0676, 736.62, 729.0), ("MSFT", 0.0891, 541.42, 533.7),
                                 ("AAPL", 0.0001, 339.92, 342.9), ("PG", 0.0001, 150.67, 156.5)):
        t.portfolio.positions[sym] = {"quantity": qty, "entry_price": entry, "current_price": now, "highest_price": now,
                                      "entry_time": "2026-09-21T15:24:00", "strategy": "Donchian_Breakout",
                                      "stop_loss": entry * 0.8, "take_profit": entry * 1.2}
    return t


PRICES = {"QQQ": 729.0, "MSFT": 533.7, "AAPL": 342.9, "PG": 156.5}
CONFS = {"QQQ": 0.8, "MSFT": 0.7, "AAPL": 0.9, "PG": 0.5}


def test_plan_trims_the_big_positions_and_tops_up_the_scraps():
    t = _live_like_us_account()
    p = rebalance.plan(t, PRICES, CONFS)
    sides = {r["symbol"]: r["side"] for r in p["rows"]}
    assert sides == {"QQQ": "SELL", "MSFT": "SELL", "AAPL": "BUY", "PG": "BUY"}
    assert [r["side"] for r in p["rows"]][:2] == ["SELL", "SELL"]  # sells first so the cash exists


def test_execute_never_closes_a_position_and_lands_near_confidence_scaled_targets():
    t = _live_like_us_account()
    p = rebalance.plan(t, PRICES, CONFS)
    value_before = t.portfolio.total_value
    rebalance.execute(t, p, "US rebalance", day="2026-10-15")
    assert set(t.portfolio.positions) == {"QQQ", "MSFT", "AAPL", "PG"}
    value = t.portfolio.total_value
    assert value == pytest.approx(value_before, rel=0.01)  # only costs are lost
    for r in p["rows"]:
        pos = t.portfolio.positions[r["symbol"]]
        held = pos["quantity"] * PRICES[r["symbol"]]
        assert held == pytest.approx(r["target_value"], abs=0.35)
        assert held <= value * settings.max_position_size + 0.35  # nothing above 12%
    assert t.portfolio.capital > 0.4 * value  # most of the account is cash again for new signals


def test_partial_sells_are_recorded_as_realized_trades_and_adds_keep_old_lots():
    t = _live_like_us_account()
    rebalance.execute(t, rebalance.plan(t, PRICES, CONFS), "US rebalance", day="2026-10-15")
    assert {h["symbol"] for h in t.portfolio.trade_history} == {"QQQ", "MSFT"}
    assert all(h["strategy"] == rebalance.STRATEGY for h in t.portfolio.trade_history)
    aapl = t.portfolio.positions["AAPL"]
    assert aapl["quantity"] > 0.0001 and aapl["strategy"] == "Donchian_Breakout"


def test_rerunning_the_same_day_changes_nothing():
    t = _live_like_us_account()
    p = rebalance.plan(t, PRICES, CONFS)
    rebalance.execute(t, p, "US rebalance", day="2026-10-15")
    cash, positions = t.portfolio.capital, {s: dict(v) for s, v in t.portfolio.positions.items()}
    rebalance.execute(t, rebalance.plan(t, PRICES, CONFS), "US rebalance", day="2026-10-15")
    # second plan is mostly HOLD; any residual orders reuse deterministic ids so no double-trade
    assert t.portfolio.capital == pytest.approx(cash, abs=0.5)
    assert set(t.portfolio.positions) == set(positions)


def test_low_confidence_is_floored_not_closed():
    t = _live_like_us_account()
    p = rebalance.plan(t, PRICES, {"QQQ": 0.0, "MSFT": 0.0, "AAPL": 0.0, "PG": 0.0})
    for r in p["rows"]:
        assert r["size_fraction"] == pytest.approx(settings.confidence_floor_fraction)
    rebalance.execute(t, p, "US rebalance", day="2026-10-15")
    assert set(t.portfolio.positions) == {"QQQ", "MSFT", "AAPL", "PG"}

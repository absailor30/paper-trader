"""
Tests for paper_trader/backtest/intraday_stop_engine.py.

The core claim under test: a daily-close-only backtest (engine.py) can
miss a stop-loss that was breached and recovered within a single day,
while the intraday engine catches it because it checks every intraday
bar's low against the stop, not just the day's close. Both engines are
run on the *same* entries so the comparison isolates exactly one thing:
what intraday stop-checking changes.
"""
import numpy as np
import pandas as pd
import pytest

from paper_trader.backtest.engine import run_backtest
from paper_trader.backtest.intraday_stop_engine import run_intraday_stop_backtest
from paper_trader.strategy.base import Position
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy


def _hourly_bars_for_day(day: str, opens_closes, lows=None, highs=None):
    """Build a small set of hourly bars for one calendar day.
    opens_closes: list of close prices, one per hour (open of next hour ==
    close of previous, close of last hour == the daily close)."""
    n = len(opens_closes)
    idx = pd.date_range(f"{day} 00:00", periods=n, freq="h", tz="UTC")
    closes = np.array(opens_closes, dtype=float)
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    lows = np.array(lows, dtype=float) if lows is not None else np.minimum(opens, closes)
    highs = np.array(highs, dtype=float) if highs is not None else np.maximum(opens, closes)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": np.full(n, 1000.0)},
        index=idx,
    )


@pytest.fixture
def donchian_breakout_data_long():
    """Same shape as the shared `donchian_breakout_data` fixture (flat,
    then breakout rally, then decline) but with enough leading flat bars
    to satisfy engine.py's/intraday_stop_engine.py's min_bars floor
    (max(settings.slow_sma, settings.atr_period) + 2 == 202 by default --
    that floor exists for TrendFollowingStrategy's SMA200 and applies
    regardless of which strategy is actually passed in, a pre-existing
    trait of the shared engine loop, not something this test suite
    changes). 250 flat bars first (matches the pattern the other
    long-running fixtures in conftest.py already use for the same
    reason), then the same rally/plateau/decline shape."""
    flat = 100 + np.sin(np.arange(250) / 5) * 0.3
    rally = flat[-1] + np.linspace(0, 15, 20)
    plateau = rally[-1] + np.sin(np.arange(20) / 5) * 0.3
    decline = plateau[-1] - np.linspace(0, 20, 15)
    close = np.concatenate([flat, rally, plateau, decline])

    from tests.conftest import _make_ohlcv

    return _make_ohlcv(close, "DONCH")


def test_intraday_engine_catches_stop_that_daily_close_misses(donchian_breakout_data_long):
    """Construct a day where the intraday LOW breaches the stop but the
    day's CLOSE recovers above it -- the exact scenario a daily-only
    check cannot see. Confirms: daily-only engine keeps the position
    open (or exits later, for a different reason); intraday engine
    exits that day via the stop with a lower fill price and records it
    in stop_only_exits."""
    donchian_breakout_data = donchian_breakout_data_long
    strategy = DonchianBreakoutStrategy(entry_period=20, exit_period=10, trend_filter_period=None)

    daily_result = run_backtest(strategy, donchian_breakout_data, initial_capital=10_000.0)
    assert daily_result.num_trades >= 1, "fixture must actually produce an entry to test against"

    # Find the first BUY, then build an intraday day for the day right
    # after entry: price crashes well below the entry's ATR stop
    # intraday, then recovers to close near where the daily bar already
    # closed (so the daily-close series driving generate_signal/should_exit
    # is completely unaffected -- only the intraday layer sees the dip).
    entry_date = None
    stop_loss = None
    for i in range(202, len(donchian_breakout_data)):
        window = donchian_breakout_data.iloc[: i + 1]
        sig = strategy.generate_signal(window)
        if sig:
            entry_date = window.index[-1]
            stop_loss = sig.stop_loss
            break
    assert entry_date is not None, "fixture must produce a signal"

    next_idx = donchian_breakout_data.index.get_loc(entry_date) + 1
    next_date = donchian_breakout_data.index[next_idx]
    next_close = float(donchian_breakout_data["close"].iloc[next_idx])

    # Intraday day: opens near next_close, crashes intraday well below
    # stop_loss, recovers to close exactly at next_close (matching the
    # daily bar so daily-only logic sees nothing unusual).
    crash_low = stop_loss - 5.0
    assert crash_low > 0
    hourly = _hourly_bars_for_day(
        next_date.strftime("%Y-%m-%d"),
        opens_closes=[next_close, next_close * 0.97, crash_low + 1, crash_low, next_close * 0.99, next_close],
        lows=[next_close, next_close * 0.96, crash_low, crash_low - 0.5, next_close * 0.98, next_close - 0.1],
        highs=[next_close + 0.1, next_close, crash_low + 2, crash_low + 1, next_close, next_close + 0.1],
    )

    daily_only, with_stops = run_intraday_stop_backtest(
        DonchianBreakoutStrategy(entry_period=20, exit_period=10, trend_filter_period=None),
        donchian_breakout_data_long,
        hourly,
        initial_capital=10_000.0,
    )

    assert with_stops.stop_only_exits >= 1, (
        "intraday engine should have caught the crash-and-recover day via "
        "check_stop_only, which daily-only checking cannot see"
    )
    # The intraday-aware run must differ from the daily-only run on this
    # symbol -- if it produced literally the same trade sequence, the new
    # engine isn't actually doing anything.
    assert with_stops.num_trades != daily_only.num_trades or with_stops.total_return_pct != daily_only.total_return_pct


def test_daily_only_and_intraday_agree_when_price_never_approaches_stop_or_target(donchian_breakout_data_long):
    """Regression/sanity check for the actual invariant this engine has:
    when a day's intraday range (here, a single point at that day's
    close) never crosses stop_loss or take_profit at all, the intraday
    engine takes zero stop-only exits and both engines produce the same
    trade count.

    Note this is NOT true for every day merely because the intraday data
    equals the daily OHLC -- see the sibling test
    test_intraday_engine_also_catches_touches_within_the_reported_daily_range,
    which documents a real, useful case where even a day's own genuine
    high/low crosses take_profit while its close does not, and the
    intraday engine (correctly) exits earlier than engine.py can. That
    is a feature of checking high/low instead of close-only, not a
    fixture bug -- this test isolates the true no-op case by picking a
    strategy config (a much wider take-profit, via min_risk_reward)
    where price never gets near either bound until the day the daily
    engine itself would exit anyway on the close."""
    strategy_factory = lambda: DonchianBreakoutStrategy(entry_period=20, exit_period=10, trend_filter_period=None)

    close = donchian_breakout_data_long["close"].values
    # Single-point bars that never independently cross a bound: this
    # confirms check_stop_only() called with the SAME price the daily
    # should_exit() would see produces the same verdict, i.e. the
    # intraday layer adds nothing when it has literally the same one
    # data point instead of a real range. The wider-target case (real
    # daily high/low) is deliberately exercised separately above.
    intraday = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": donchian_breakout_data_long["volume"].values},
        index=donchian_breakout_data_long.index,
    )

    from unittest.mock import patch

    # With min_risk_reward pushed very high, take_profit moves far above
    # anything this fixture's rally reaches, isolating the stop-loss side
    # of the invariant (which the crash-and-recover test above already
    # proves DOES get caught correctly when the range genuinely differs
    # from the single point).
    with patch("paper_trader.strategy.donchian_breakout.settings") as mock_settings:
        mock_settings.donchian_entry_period = 20
        mock_settings.donchian_exit_period = 10
        mock_settings.atr_period = 14
        mock_settings.atr_stop_multiple = 3.5
        mock_settings.min_risk_reward = 1000.0  # take_profit effectively unreachable

        daily_only, with_stops = run_intraday_stop_backtest(
            strategy_factory(), donchian_breakout_data_long, intraday, initial_capital=10_000.0
        )

    assert with_stops.stop_only_exits == 0
    assert with_stops.num_trades == daily_only.num_trades
    assert with_stops.total_return_pct == pytest.approx(daily_only.total_return_pct)


def test_intraday_engine_also_catches_touches_within_the_reported_daily_range(donchian_breakout_data_long):
    """Distinct from the crash-and-recover scenario above: even when the
    intraday data for a day is just that day's own real high/low/close
    (no separately-fabricated dip), the intraday engine can still exit
    earlier than the daily engine, because engine.py's should_exit()
    only ever compares the day's CLOSE to stop_loss/take_profit -- never
    that day's high or low -- while the intraday engine checks every
    bar's high/low. A take-profit that the day's high touched, with the
    close pulling back below it, is invisible to the daily-only engine
    and caught here. This is not a fixture artifact (see the note on the
    sibling no-op test); it is a genuine, more-precise reading of the
    same day's data, and is exactly the finding that motivated splitting
    check_stop_only() out in the first place."""
    strategy_factory = lambda: DonchianBreakoutStrategy(entry_period=20, exit_period=10, trend_filter_period=None)

    daily_only, with_stops = run_intraday_stop_backtest(
        strategy_factory(),
        donchian_breakout_data_long,
        donchian_breakout_data_long[["open", "high", "low", "close", "volume"]],
        initial_capital=10_000.0,
    )

    assert with_stops.stop_only_exits >= 1
    assert with_stops.num_trades >= daily_only.num_trades


def test_run_intraday_stop_backtest_rejects_empty_intraday_data(donchian_breakout_data):
    strategy = DonchianBreakoutStrategy()
    with pytest.raises(ValueError, match="intraday"):
        run_intraday_stop_backtest(strategy, donchian_breakout_data, pd.DataFrame(), initial_capital=10_000.0)


def test_run_intraday_stop_backtest_rejects_empty_daily_data():
    strategy = DonchianBreakoutStrategy()
    fake_intraday = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
        index=pd.date_range("2023-01-01", periods=1, freq="h", tz="UTC"),
    )
    with pytest.raises(ValueError, match="No daily data"):
        run_intraday_stop_backtest(strategy, pd.DataFrame(), fake_intraday, initial_capital=10_000.0)


class TestCheckStopOnly:
    """Strategy.check_stop_only() -- the shared primitive all three
    strategies get from the base class, exercised directly (not just
    through the engine) since it's the thing a live orchestrator's
    frequent-poll job would call every cycle."""

    def _position(self, stop_loss=None, take_profit=None):
        return Position(
            symbol="TEST",
            quantity=1.0,
            entry_price=100.0,
            current_price=100.0,
            entry_time=pd.Timestamp("2023-01-01"),
            strategy_name="test",
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    def test_price_below_stop_loss_triggers(self):
        strategy = DonchianBreakoutStrategy()
        pos = self._position(stop_loss=90.0)
        assert strategy.check_stop_only(pos, current_price=89.99) is True

    def test_price_above_stop_loss_does_not_trigger(self):
        strategy = DonchianBreakoutStrategy()
        pos = self._position(stop_loss=90.0)
        assert strategy.check_stop_only(pos, current_price=95.0) is False

    def test_price_at_stop_loss_exactly_triggers(self):
        strategy = DonchianBreakoutStrategy()
        pos = self._position(stop_loss=90.0)
        assert strategy.check_stop_only(pos, current_price=90.0) is True

    def test_price_above_take_profit_triggers(self):
        strategy = DonchianBreakoutStrategy()
        pos = self._position(take_profit=110.0)
        assert strategy.check_stop_only(pos, current_price=110.01) is True

    def test_no_stop_or_target_never_triggers(self):
        strategy = DonchianBreakoutStrategy()
        pos = self._position()
        assert strategy.check_stop_only(pos, current_price=1.0) is False
        assert strategy.check_stop_only(pos, current_price=1_000_000.0) is False

    def test_shared_across_all_three_strategies(self):
        """All three strategies must use the identical inherited check --
        this pins that none of them override it with different semantics
        (which would silently break the "one shared stop-check" design)."""
        from paper_trader.strategy.mean_reversion import MeanReversionStrategy
        from paper_trader.strategy.trend_following import TrendFollowingStrategy

        pos = self._position(stop_loss=90.0)
        for strategy in (DonchianBreakoutStrategy(), MeanReversionStrategy(), TrendFollowingStrategy()):
            assert strategy.check_stop_only(pos, current_price=89.0) is True
            assert strategy.check_stop_only(pos, current_price=91.0) is False

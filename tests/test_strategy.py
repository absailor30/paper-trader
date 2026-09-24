import numpy as np

from paper_trader.strategy.base import Position, SignalType
from paper_trader.strategy.trend_following import TrendFollowingStrategy
from tests.conftest import _make_ohlcv


def test_generates_buy_signal_somewhere_in_uptrend(uptrend_data):
    strategy = TrendFollowingStrategy()
    signals = []
    for i in range(210, len(uptrend_data)):
        window = uptrend_data.iloc[: i + 1]
        signal = strategy.generate_signal(window)
        if signal:
            signals.append(signal)

    assert len(signals) >= 1
    first = signals[0]
    assert first.signal_type == SignalType.BUY
    assert first.stop_loss < first.price < first.take_profit


def test_no_signal_on_flat_market(flat_data):
    strategy = TrendFollowingStrategy()
    signals = [strategy.generate_signal(flat_data.iloc[: i + 1]) for i in range(210, len(flat_data))]
    assert all(s is None for s in signals)


def test_no_signal_with_insufficient_history(short_data):
    strategy = TrendFollowingStrategy()
    assert strategy.generate_signal(short_data) is None


def test_should_exit_on_stop_loss(uptrend_data):
    strategy = TrendFollowingStrategy()
    position = Position(
        symbol="TEST", quantity=1, entry_price=150.0, current_price=140.0,
        entry_time="2024-01-01", strategy_name=strategy.name,
        stop_loss=145.0, take_profit=200.0,
    )
    assert strategy.should_exit(position, uptrend_data) is True


def test_single_day_dip_below_sma_does_not_exit():
    """Regression test for the whipsaw bug found in the first real
    backtest: a single-day dip below the 50 SMA must not trigger an exit
    on its own (that's what was causing frequent premature stop-outs)."""
    strategy = TrendFollowingStrategy()
    close = np.concatenate([np.full(60, 100.0), [90.0]])
    data = _make_ohlcv(close, "X")
    position = Position(
        symbol="X", quantity=1, entry_price=100.0, current_price=90.0,
        entry_time="2024-01-01", strategy_name=strategy.name,
        stop_loss=50.0, take_profit=500.0,
    )
    assert strategy.should_exit(position, data) is False


def test_two_consecutive_days_below_sma_does_exit():
    strategy = TrendFollowingStrategy()
    close = np.concatenate([np.full(60, 100.0), [90.0, 88.0]])
    data = _make_ohlcv(close, "X")
    position = Position(
        symbol="X", quantity=1, entry_price=100.0, current_price=88.0,
        entry_time="2024-01-01", strategy_name=strategy.name,
        stop_loss=50.0, take_profit=500.0,
    )
    assert strategy.should_exit(position, data) is True


def test_should_exit_on_take_profit(uptrend_data):
    strategy = TrendFollowingStrategy()
    last_price = float(uptrend_data["close"].iloc[-1])
    position = Position(
        symbol="TEST", quantity=1, entry_price=100.0, current_price=last_price,
        entry_time="2024-01-01", strategy_name=strategy.name,
        stop_loss=50.0, take_profit=last_price - 0.01,
    )
    assert strategy.should_exit(position, uptrend_data) is True

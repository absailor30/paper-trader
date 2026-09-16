from paper_trader.strategy.base import Position, SignalType
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy


def test_generates_buy_signal_on_new_high_breakout(donchian_breakout_data):
    strategy = DonchianBreakoutStrategy()
    signals = []
    for i in range(60, len(donchian_breakout_data)):
        window = donchian_breakout_data.iloc[: i + 1]
        signal = strategy.generate_signal(window)
        if signal:
            signals.append(signal)

    assert len(signals) >= 1
    first = signals[0]
    assert first.signal_type == SignalType.BUY
    assert first.stop_loss < first.price < first.take_profit


def test_no_signal_on_flat_market(flat_data):
    strategy = DonchianBreakoutStrategy()
    signals = [strategy.generate_signal(flat_data.iloc[: i + 1]) for i in range(30, len(flat_data))]
    assert all(s is None for s in signals)


def test_no_signal_with_insufficient_history(short_data):
    strategy = DonchianBreakoutStrategy()
    # short_data (30 bars) is actually long enough for Donchian's shorter
    # lookback (needs ~22 vs. trend-following's ~202), so trim it further
    # to genuinely test the insufficient-history guard.
    assert strategy.generate_signal(short_data.iloc[:15]) is None


def test_should_exit_on_new_low_breakdown(donchian_breakout_data):
    strategy = DonchianBreakoutStrategy()
    # The decline leg breaks the 10-day low channel; find where.
    from paper_trader.strategy.indicators import donchian_low
    low_channel = donchian_low(donchian_breakout_data["low"], 10)
    breakdown_idx = (donchian_breakout_data["close"] < low_channel)
    breakdown_positions = breakdown_idx[breakdown_idx].index
    assert len(breakdown_positions) > 0, "fixture doesn't produce a breakdown bar; test is unverifiable"

    idx_pos = donchian_breakout_data.index.get_loc(breakdown_positions[0])
    window = donchian_breakout_data.iloc[: idx_pos + 1]
    price = float(window["close"].iloc[-1])

    position = Position(
        symbol="DONCH", quantity=1, entry_price=price * 1.1, current_price=price,
        entry_time="2023-01-01", strategy_name=strategy.name,
        stop_loss=price * 0.5, take_profit=price * 2.0,
    )
    assert strategy.should_exit(position, window) is True


def test_should_exit_on_stop_loss(donchian_breakout_data):
    strategy = DonchianBreakoutStrategy()
    position = Position(
        symbol="DONCH", quantity=1, entry_price=120.0, current_price=100.0,
        entry_time="2023-01-01", strategy_name=strategy.name,
        stop_loss=105.0, take_profit=200.0,
    )
    assert strategy.should_exit(position, donchian_breakout_data) is True


def test_no_exit_with_insufficient_history(short_data):
    strategy = DonchianBreakoutStrategy()
    position = Position(
        symbol="SHORT", quantity=1, entry_price=100.0, current_price=105.0,
        entry_time="2023-01-01", strategy_name=strategy.name,
        stop_loss=90.0, take_profit=150.0,
    )
    assert strategy.should_exit(position, short_data) is False

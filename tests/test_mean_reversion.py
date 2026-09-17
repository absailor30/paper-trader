from paper_trader.strategy.base import Position, SignalType
from paper_trader.strategy.mean_reversion import MeanReversionStrategy


def test_generates_buy_signal_on_oversold_recovery_in_uptrend(pullback_in_uptrend_data):
    strategy = MeanReversionStrategy()
    signals = []
    for i in range(200, len(pullback_in_uptrend_data)):
        window = pullback_in_uptrend_data.iloc[: i + 1]
        signal = strategy.generate_signal(window)
        if signal:
            signals.append(signal)

    assert len(signals) >= 1
    first = signals[0]
    assert first.signal_type == SignalType.BUY
    assert first.stop_loss < first.price < first.take_profit


def test_no_signal_on_flat_market(flat_data):
    strategy = MeanReversionStrategy()
    signals = [strategy.generate_signal(flat_data.iloc[: i + 1]) for i in range(210, len(flat_data))]
    assert all(s is None for s in signals)


def test_no_signal_with_insufficient_history(short_data):
    strategy = MeanReversionStrategy()
    assert strategy.generate_signal(short_data) is None


def test_should_exit_on_overbought_rsi(pullback_in_uptrend_data):
    strategy = MeanReversionStrategy()
    # The recovery leg of the dip pushes RSI up sharply; find a bar where
    # it's actually overbought rather than assuming one.
    # Only consider bars past should_exit's own min-history requirement
    # (needs 200 SMA + 1); RSI is naturally pinned to 100 during the pure
    # monotonic climb before that, which isn't the recovery this test means.
    from paper_trader.strategy.indicators import rsi
    r = rsi(pullback_in_uptrend_data["close"], 14)
    overbought_idx = r[(r >= 70) & (r.index >= pullback_in_uptrend_data.index[201])].index
    assert len(overbought_idx) > 0, "fixture doesn't produce an overbought bar; test is unverifiable"

    idx_pos = pullback_in_uptrend_data.index.get_loc(overbought_idx[0])
    window = pullback_in_uptrend_data.iloc[: idx_pos + 1]
    price = float(window["close"].iloc[-1])

    position = Position(
        symbol="PULLBACK", quantity=1, entry_price=price * 0.9, current_price=price,
        entry_time="2024-01-01", strategy_name=strategy.name,
        stop_loss=price * 0.5, take_profit=price * 2.0,
    )
    assert strategy.should_exit(position, window) is True


def test_should_exit_on_stop_loss(pullback_in_uptrend_data):
    strategy = MeanReversionStrategy()
    position = Position(
        symbol="PULLBACK", quantity=1, entry_price=150.0, current_price=100.0,
        entry_time="2024-01-01", strategy_name=strategy.name,
        stop_loss=140.0, take_profit=200.0,
    )
    assert strategy.should_exit(position, pullback_in_uptrend_data) is True

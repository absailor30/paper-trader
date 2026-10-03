from dataclasses import replace

from paper_trader.backtest.engine import run_backtest
from paper_trader.strategy.trend_following import TrendFollowingStrategy


def test_backtest_runs_and_produces_sane_metrics(uptrend_data):
    strategy = TrendFollowingStrategy()
    result = run_backtest(strategy, uptrend_data, initial_capital=10_000.0)

    assert result.symbol == "TEST"
    assert result.final_value > 0
    assert -100 <= result.max_drawdown_pct <= 0
    assert result.num_trades >= 0
    assert 0 <= result.win_rate <= 100


def test_backtest_on_flat_market_takes_no_trades(flat_data):
    strategy = TrendFollowingStrategy()
    result = run_backtest(strategy, flat_data, initial_capital=10_000.0)

    assert result.num_trades == 0
    assert result.final_value == 10_000.0


def test_losing_less_than_a_falling_benchmark_is_not_validated(uptrend_data):
    """Regression test: a real run showed strategies with a negative
    return, and a losing profit factor, being labeled POSITIVE EDGE just
    because the underlying stock fell even further. Beating a falling
    benchmark while still losing money must never count as validated."""
    result = run_backtest(TrendFollowingStrategy(), uptrend_data, initial_capital=10_000.0)
    losing_but_beats_falling_benchmark = replace(
        result,
        total_return_pct=-2.0,
        benchmark_return_pct=-20.0,
        num_trades=10,
    )
    assert losing_but_beats_falling_benchmark.is_validated() is False


def test_profitable_and_beats_benchmark_is_validated(uptrend_data):
    result = run_backtest(TrendFollowingStrategy(), uptrend_data, initial_capital=10_000.0)
    genuinely_validated = replace(
        result,
        total_return_pct=5.0,
        benchmark_return_pct=1.0,
        num_trades=10,
    )
    assert genuinely_validated.is_validated() is True

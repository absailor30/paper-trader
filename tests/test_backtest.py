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

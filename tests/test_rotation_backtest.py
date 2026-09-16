import numpy as np
import pandas as pd

from paper_trader.backtest.rotation_backtest import run_rotation_backtest


def _make_price_matrix(n_bars: int = 300) -> pd.DataFrame:
    """Four symbols with distinct, deterministic trends: A steep up, B
    moderate up, C flat/slightly up, D declining -- so momentum ranking
    has an unambiguous, stable answer across the whole backtest (D should
    never be selected; A/B/C should be)."""
    dates = pd.date_range("2023-01-02", periods=n_bars, freq="B")
    return pd.DataFrame(
        {
            "A": 100 + np.linspace(0, 150, n_bars),
            "B": 100 + np.linspace(0, 60, n_bars),
            "C": 100 + np.linspace(0, 10, n_bars),
            "D": 100 - np.linspace(0, 40, n_bars),
        },
        index=dates,
    )


def test_rotation_backtest_runs_and_produces_sane_metrics():
    price_df = _make_price_matrix()
    result = run_rotation_backtest(price_df, "TEST", initial_capital=10_000.0)

    assert result.universe_name == "TEST"
    assert result.final_value > 0
    assert result.num_rebalances > 0
    assert result.num_trades > 0
    assert -100 <= result.max_drawdown_pct <= 0


def test_rotation_backtest_favors_the_steady_winner():
    """With top_n=5 (default) and only 4 symbols, all of A/B/C (positive
    momentum) get selected every rebalance and D (declining) never does --
    so the strategy should end up well ahead of a naive equal-weight
    benchmark that's dragged down by D the whole time."""
    price_df = _make_price_matrix()
    result = run_rotation_backtest(price_df, "TEST", initial_capital=10_000.0)

    assert result.total_return_pct > result.benchmark_return_pct


def test_rotation_backtest_raises_on_insufficient_history():
    price_df = _make_price_matrix(n_bars=50)
    try:
        run_rotation_backtest(price_df, "TEST", initial_capital=10_000.0)
        assert False, "expected ValueError for insufficient history"
    except ValueError:
        pass

"""
CLI: run the trend-following strategy's backtest over the configured
universe and print a verdict per symbol. This is the gate — nothing in
orchestrator.py should be trusted to auto-execute until this has been run
against real data and shown a positive edge.

Usage:
    python -m paper_trader.backtest.run_backtest
"""
from datetime import datetime, timedelta

from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.strategy.trend_following import TrendFollowingStrategy
from paper_trader.backtest.engine import run_backtest


def main():
    fetcher = DataFetcher()
    strategy = TrendFollowingStrategy()
    start_date = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")

    print("=" * 70)
    print(f"BACKTEST: {strategy.name}")
    print("=" * 70)

    results = []
    for symbol in settings.us_stocks:
        data = fetcher.fetch(symbol, start_date=start_date)
        if data.empty:
            print(f"{symbol}: no data, skipped")
            continue
        result = run_backtest(strategy, data, initial_capital=10_000.0)
        results.append(result)
        print(result.summary())

    print("\n" + "=" * 70)
    validated = [r for r in results if r.total_return_pct > r.benchmark_return_pct and r.num_trades >= 5]
    print(f"{len(validated)}/{len(results)} symbols show edge over buy-and-hold with >=5 trades.")
    print("Do not enable AUTO_EXECUTE until this looks right across the universe,")
    print("not just on a single cherry-picked symbol.")
    print("=" * 70)


if __name__ == "__main__":
    main()

"""
CLI: run every candidate strategy's backtest over the configured universe
and print a verdict per symbol. This is the gate — nothing in
orchestrator.py should be trusted to auto-execute until a strategy has
been run through here and shown a positive edge.

Usage:
    python -m paper_trader.backtest.run_backtest
"""
from datetime import datetime, timedelta

from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.strategy.mean_reversion import MeanReversionStrategy
from paper_trader.strategy.trend_following import TrendFollowingStrategy
from paper_trader.backtest.engine import run_backtest

STRATEGIES = [TrendFollowingStrategy(), MeanReversionStrategy()]


def main():
    fetcher = DataFetcher()
    start_date = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")

    all_results = []
    for strategy in STRATEGIES:
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

        validated = [r for r in results if r.total_return_pct > r.benchmark_return_pct and r.num_trades >= 5]
        print(f"\n{len(validated)}/{len(results)} symbols show edge over buy-and-hold with >=5 trades.\n")
        all_results.extend(results)

    print("=" * 70)
    print("OVERALL")
    print("=" * 70)
    for strategy in STRATEGIES:
        strategy_results = [r for r in all_results if r.strategy_name == strategy.name]
        validated = [r for r in strategy_results if r.total_return_pct > r.benchmark_return_pct and r.num_trades >= 5]
        print(f"{strategy.name}: {len(validated)}/{len(strategy_results)} symbols validated")
    print("\nDo not enable AUTO_EXECUTE for a strategy until it looks right")
    print("across the universe, not just on a single cherry-picked symbol.")
    print("=" * 70)


if __name__ == "__main__":
    main()

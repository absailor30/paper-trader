"""
CLI: run every candidate strategy's backtest over the configured universe
(US, India, commodities, or all of them) and print a verdict per symbol
plus aggregate stats. This is the gate -- nothing in orchestrator.py
should be trusted to auto-execute until a strategy has been run through
here and shown a real edge.

Usage:
    python -m paper_trader.backtest.run_backtest
    python -m paper_trader.backtest.run_backtest --universe commodities
    python -m paper_trader.backtest.run_backtest --universe us,india
"""
import argparse
from datetime import datetime, timedelta

from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.data.binance_fetcher import BinanceFetcher
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy
from paper_trader.strategy.mean_reversion import MeanReversionStrategy
from paper_trader.strategy.trend_following import TrendFollowingStrategy
from paper_trader.backtest.engine import run_backtest

STRATEGIES = [
    TrendFollowingStrategy(),
    MeanReversionStrategy(),
    DonchianBreakoutStrategy(trend_filter_period=100),
]
ALL_UNIVERSES = {
    "us": ("US", settings.us_stocks, False),
    "india": ("INDIA", settings.india_stocks, True),
    "commodities": ("COMMODITIES", settings.commodities, False),
    "crypto": ("CRYPTO", settings.crypto_pairs, False),
}
CRYPTO_START_CAPITAL = settings.crypto_capital

# Donchian variants to compare in one real-data run instead of guessing at
# one config blind -- see CHECKPOINT.md "Donchian iteration" for why these
# specific combos: the original default, the classic slower Turtle System 2
# periods (55/20), a faster/choppier variant (10/5), and the default entry
# window with a 100-day trend filter added (skip breakouts against the
# longer-term trend, the standard whipsaw fix for pure breakout systems).
DONCHIAN_SWEEP = [
    DonchianBreakoutStrategy(20, 10, None, name="Donchian_20_10_baseline"),
    DonchianBreakoutStrategy(55, 20, None, name="Donchian_55_20_turtle"),
    DonchianBreakoutStrategy(10, 5, None, name="Donchian_10_5_fast"),
    DonchianBreakoutStrategy(20, 10, 100, name="Donchian_20_10_trend100"),
    DonchianBreakoutStrategy(55, 20, 100, name="Donchian_55_20_trend100"),
]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--universe",
        default="us,india,commodities",
        help="Comma-separated subset to run: us, india, commodities, crypto (default: us,india,commodities)",
    )
    parser.add_argument(
        "--sweep",
        choices=["donchian"],
        help="Instead of the fixed strategy list, run a parameter sweep for the named strategy "
        "(currently only 'donchian') and compare variants side by side.",
    )
    args = parser.parse_args(argv)

    keys = [k.strip().lower() for k in args.universe.split(",")]
    unknown = [k for k in keys if k not in ALL_UNIVERSES]
    if unknown:
        parser.error(f"Unknown universe(s): {unknown}. Choose from: {list(ALL_UNIVERSES)}")
    universes = [ALL_UNIVERSES[k] for k in keys]

    fetcher = DataFetcher()
    crypto_fetcher = BinanceFetcher(market="spot")
    start_date = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")

    strategies = DONCHIAN_SWEEP if args.sweep == "donchian" else STRATEGIES

    all_results = []
    for strategy in strategies:
        print("=" * 70)
        print(f"BACKTEST: {strategy.name}")
        print("=" * 70)

        for market, symbols, india in universes:
            print(f"\n--- {market} universe ({len(symbols)} symbols) ---")
            results = []
            is_crypto = market == "CRYPTO"
            capital = CRYPTO_START_CAPITAL if is_crypto else 10_000.0
            for symbol in symbols:
                if is_crypto:
                    data = crypto_fetcher.fetch(symbol, start_date=start_date)
                else:
                    data = fetcher.fetch(symbol, start_date=start_date, india=india)
                if data.empty:
                    print(f"{symbol}: no data, skipped")
                    continue
                result = run_backtest(strategy, data, initial_capital=capital)
                results.append(result)
                print(result.summary())

            validated = [r for r in results if r.is_validated()]
            print(f"\n{len(validated)}/{len(results)} {market} symbols validated (profitable and beat buy-and-hold, >=5 trades).")
            all_results.extend(results)

    print("\n" + "=" * 70)
    print("OVERALL")
    print("=" * 70)
    print(
        "Note: 'beat buy-and-hold' is a near-impossible bar for any strategy\n"
        "that isn't fully invested the whole period, especially across a\n"
        "2022-2026 window that includes extreme runs (NVDA +1268%). The\n"
        "aggregate stats below (win rate, profit factor, drawdown) are the\n"
        "more meaningful read on whether a strategy has a real edge.\n"
    )
    for strategy in strategies:
        strategy_results = [r for r in all_results if r.strategy_name == strategy.name]
        traded = [r for r in strategy_results if r.num_trades >= 5]
        validated = [r for r in strategy_results if r.is_validated()]

        print(f"{strategy.name}:")
        print(f"  {len(validated)}/{len(strategy_results)} symbols validated (profitable and beat buy-and-hold, >=5 trades)")
        if traded:
            avg_win_rate = sum(r.win_rate for r in traded) / len(traded)
            finite_pf = [r.profit_factor for r in traded if r.profit_factor != float("inf")]
            avg_pf = sum(finite_pf) / len(finite_pf) if finite_pf else float("inf")
            avg_drawdown = sum(r.max_drawdown_pct for r in traded) / len(traded)
            total_trades = sum(r.num_trades for r in traded)
            print(f"  Across {len(traded)} symbols with >=5 trades ({total_trades} trades total):")
            print(f"    avg win rate: {avg_win_rate:.1f}%")
            print(f"    avg profit factor (finite only, {len(finite_pf)}/{len(traded)} symbols): {avg_pf:.2f}")
            print(f"    avg max drawdown: {avg_drawdown:.2f}%")
        else:
            print("  No symbol reached >=5 trades -- sample too thin to assess at all.")
        print()

    print("Do not enable AUTO_EXECUTE for a strategy until this looks right")
    print("across the universe on a large enough sample, not one symbol.")
    print("=" * 70)


if __name__ == "__main__":
    main()

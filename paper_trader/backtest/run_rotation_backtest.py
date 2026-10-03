"""
CLI: run the momentum rotation backtest over US and/or India universes.

Usage:
    python -m paper_trader.backtest.run_rotation_backtest
    python -m paper_trader.backtest.run_rotation_backtest --universe india
"""
import argparse
from datetime import datetime, timedelta

from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.backtest.rotation_backtest import build_price_matrix, run_rotation_backtest

ALL_UNIVERSES = {
    "us": ("US", settings.us_stocks, False),
    "india": ("INDIA", settings.india_stocks, True),
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--universe",
        default="us,india",
        help="Comma-separated subset to run: us, india (default: both)",
    )
    args = parser.parse_args(argv)

    keys = [k.strip().lower() for k in args.universe.split(",")]
    unknown = [k for k in keys if k not in ALL_UNIVERSES]
    if unknown:
        parser.error(f"Unknown universe(s): {unknown}. Choose from: {list(ALL_UNIVERSES)}")

    fetcher = DataFetcher()
    start_date = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")

    print("=" * 70)
    print("BACKTEST: Momentum_Rotation")
    print(
        f"(top {settings.rotation_top_n}, {settings.rotation_lookback_days}-day lookback, "
        f"rebalanced every {settings.rotation_rebalance_days} days)"
    )
    print("=" * 70)

    for key in keys:
        name, symbols, india = ALL_UNIVERSES[key]
        print(f"\n--- {name} universe ({len(symbols)} symbols) ---")
        try:
            price_df = build_price_matrix(fetcher, symbols, start_date, india)
            result = run_rotation_backtest(price_df, name, initial_capital=10_000.0)
            print(result.summary())
        except ValueError as e:
            print(f"{name}: skipped -- {e}")

    print("\nDo not enable AUTO_EXECUTE until this looks right, same bar as the other strategies.")
    print("=" * 70)


if __name__ == "__main__":
    main()

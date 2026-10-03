"""
Real-data runner for the intraday stop-monitoring comparison on stocks
(paper_trader/backtest/intraday_stop_engine.py), mirroring
run_intraday_stop_backtest.py's crypto version. Must be run from an
environment with real internet access to Yahoo Finance -- this sandbox
is fully network-blocked (confirmed repeatedly across this project), so
this has never actually executed against real data. See CHECKPOINT.md,
"Stocks: intraday stop monitoring added".

Note on yfinance intraday limits: hourly bars ("1h") are only available
for roughly the trailing 730 days, and finer intervals (5m/15m) for much
less (~60 days). --days defaults to 700 to stay under the 1h cap with
margin; a longer window just silently returns less history, not an error.

Usage:
    python scripts/run_intraday_stop_backtest_stocks.py
    python scripts/run_intraday_stop_backtest_stocks.py --universe us
    python scripts/run_intraday_stop_backtest_stocks.py --symbols AAPL,MSFT --interval 1h --days 700
"""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from paper_trader.backtest.intraday_stop_engine import run_intraday_stop_backtest
from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy

UNIVERSES = {
    "us": (settings.us_stocks, False),
    "india": (settings.india_stocks, True),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--universe", default="us,india",
        help="Comma-separated subset to run: us, india (default: both)",
    )
    parser.add_argument(
        "--symbols", default=None,
        help="Comma-separated symbols to override --universe entirely (all treated as US unless --india is also passed)",
    )
    parser.add_argument("--india", action="store_true", help="Treat --symbols as India tickers")
    parser.add_argument(
        "--interval", default="1h",
        help="Intraday granularity for DataFetcher (default 1h; yfinance also supports 15m, 5m, etc., with shorter lookback caps)",
    )
    parser.add_argument(
        "--days", type=int, default=700,
        help="Lookback window in days for both daily and intraday pulls (default 700, under yfinance's ~730d cap for 1h bars)",
    )
    args = parser.parse_args()

    if args.symbols:
        targets = [(s.strip(), args.india) for s in args.symbols.split(",") if s.strip()]
    else:
        keys = [k.strip().lower() for k in args.universe.split(",")]
        unknown = [k for k in keys if k not in UNIVERSES]
        if unknown:
            parser.error(f"Unknown universe(s): {unknown}. Choose from: {list(UNIVERSES)}")
        targets = []
        for k in keys:
            symbols, india = UNIVERSES[k]
            targets.extend((s, india) for s in symbols)

    start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    fetcher = DataFetcher()
    strategy_name = "Donchian_Stocks_IntradayCheck"

    results = []
    for symbol, india in targets:
        logger.info(f"=== {symbol} ===")
        daily = fetcher.fetch(symbol, start_date=start_date, india=india, interval="1d")
        intraday = fetcher.fetch(symbol, start_date=start_date, india=india, interval=args.interval)

        if daily.empty or intraday.empty:
            logger.warning(f"{symbol}: no data returned, skipping")
            continue

        strategy = DonchianBreakoutStrategy(trend_filter_period=100, name=strategy_name)
        daily_only, with_stops = run_intraday_stop_backtest(
            strategy, daily, intraday, initial_capital=10_000.0
        )
        results.append((symbol, daily_only, with_stops))

    print("\n" + "=" * 100)
    print(f"{'Symbol':<12} {'Daily-only':<28} {'With intraday stops':<28} {'Stops caught':<14} {'Delta return'}")
    print("=" * 100)
    for symbol, d, w in results:
        delta = w.total_return_pct - d.total_return_pct
        print(
            f"{symbol:<12} "
            f"{d.total_return_pct:+7.2f}% / {d.num_trades:3d}tr / {d.win_rate:5.1f}%wr    "
            f"{w.total_return_pct:+7.2f}% / {w.num_trades:3d}tr / {w.win_rate:5.1f}%wr    "
            f"{w.stop_only_exits:<14} "
            f"{delta:+.2f}%"
        )
    print("=" * 100)
    print(
        "\nRead this like every other result in CHECKPOINT.md: a positive stop_only_exits\n"
        "count is not automatically an improvement -- check whether total_return_pct actually\n"
        "went up, not just whether stops fired sooner. Record this table in CHECKPOINT.md\n"
        "under 'Stocks: intraday stop monitoring' before trusting the poller's numbers."
    )


if __name__ == "__main__":
    main()

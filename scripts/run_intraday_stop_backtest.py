"""
Real-data runner for the intraday stop-monitoring comparison
(paper_trader/backtest/intraday_stop_engine.py). Must be run from an
environment with real internet access to Binance -- confirmed
geo-blocked (HTTP 451) from the sandbox this was developed in, so this
has never actually executed against real data. See CHECKPOINT.md,
"Intraday stop monitoring".

Usage:
    python scripts/run_intraday_stop_backtest.py
    python scripts/run_intraday_stop_backtest.py --pairs BTCUSDT,ETHUSDT
    python scripts/run_intraday_stop_backtest.py --interval 1h --days 900
"""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from paper_trader.backtest.intraday_stop_engine import run_intraday_stop_backtest
from paper_trader.config import settings
from paper_trader.data.binance_fetcher import BinanceFetcher
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pairs", default=",".join(settings.crypto_pairs),
        help="Comma-separated symbols (default: settings.crypto_pairs, the 8 validated pairs)",
    )
    parser.add_argument(
        "--interval", default="1h",
        help="Intraday granularity for BinanceFetcher (default 1h; Binance also supports 15m, 5m, 4h, etc.)",
    )
    parser.add_argument(
        "--days", type=int, default=900,
        help="Lookback window in days for both daily and intraday pulls (default 900, ~2.5y)",
    )
    args = parser.parse_args()

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    fetcher = BinanceFetcher(market="spot")
    strategy_name = "Donchian_Crypto_IntradayCheck"

    results = []
    for symbol in pairs:
        logger.info(f"=== {symbol} ===")
        daily = fetcher.fetch(symbol, start_date=start_date, interval="1d")
        intraday = fetcher.fetch(symbol, start_date=start_date, interval=args.interval)

        if daily.empty or intraday.empty:
            logger.warning(f"{symbol}: no data returned, skipping")
            continue

        strategy = DonchianBreakoutStrategy(trend_filter_period=100, name=strategy_name)
        daily_only, with_stops = run_intraday_stop_backtest(
            strategy, daily, intraday, initial_capital=settings.crypto_capital
        )
        results.append((symbol, daily_only, with_stops))

    print("\n" + "=" * 100)
    print(f"{'Symbol':<10} {'Daily-only':<28} {'With intraday stops':<28} {'Stops caught':<14} {'Delta return'}")
    print("=" * 100)
    for symbol, d, w in results:
        delta = w.total_return_pct - d.total_return_pct
        print(
            f"{symbol:<10} "
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
        "under 'Intraday stop monitoring' before deciding whether to wire a live poller."
    )


if __name__ == "__main__":
    main()

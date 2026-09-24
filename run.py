"""
CLI entry point.

    python run.py cycle          # run one US + India cycle (propose-only unless AUTO_EXECUTE=true)
    python run.py cycle --market US
    python run.py cycle --stops-only   # check open positions' stop/take-profit against current price only
    python run.py retry-entry --market US --symbol QQQ   # re-attempt one symbol's BUY that was
                                                           # REJECTED earlier today (e.g. after a
                                                           # sizing bug fix) -- run_market_cycle
                                                           # itself never retries same-day by design
    python run.py backtest       # run the strategy backtest, all universes (see paper_trader/backtest/run_backtest.py)
    python run.py backtest --universe commodities
    python run.py backtest --universe crypto           # Binance spot pairs (see settings.crypto_pairs)
    python run.py backtest --universe crypto_futures   # same pairs, USD-M futures OHLCV (no leverage/funding modeled)
    python run.py backtest --sweep donchian   # compare Donchian entry/exit/trend-filter variants
    python run.py rotation       # run the momentum rotation backtest (see paper_trader/backtest/run_rotation_backtest.py)
    python run.py rotation --universe india
    python run.py crypto         # one crypto paper-trading cycle (propose-only unless AUTO_EXECUTE=true)
    python run.py crypto --loop --interval-hours 24   # run cycles forever, sleeping between them
    python run.py status         # refresh open positions to the latest price (via check_stops_only,
                                  # so a real stop can still fire) and print P&L for US, INDIA, CRYPTO
"""
import argparse
import json
import time

from loguru import logger

from paper_trader.config import settings
from paper_trader.orchestrator import TradingBot
from paper_trader.crypto_orchestrator import CryptoTradingBot


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    cycle_parser = sub.add_parser("cycle")
    cycle_parser.add_argument("--market", choices=["US", "INDIA"], default=None)
    cycle_parser.add_argument(
        "--stops-only", action="store_true",
        help=(
            "Run only TradingBot.check_stops_only() instead of the full cycle -- checks "
            "open positions' stop/take-profit against the current price and exits on a "
            "breach, never opens a new position. Meant for a separate, more frequent "
            "schedule than the once-daily full cycle, limited to market hours; see "
            "stocks-intraday-stops.yml and CHECKPOINT.md 'Intraday stop monitoring'."
        ),
    )

    backtest_parser = sub.add_parser("backtest")
    backtest_parser.add_argument(
        "--universe",
        default="us,india,commodities",
        help="Comma-separated subset to run: us, india, commodities (default: all three)",
    )
    backtest_parser.add_argument(
        "--sweep",
        choices=["donchian"],
        default=None,
        help="Run a parameter sweep for the named strategy instead of the fixed strategy list",
    )

    retry_parser = sub.add_parser("retry-entry")
    retry_parser.add_argument("--market", choices=["US", "INDIA"], required=True)
    retry_parser.add_argument("--symbol", required=True)

    sub.add_parser("status")

    rotation_parser = sub.add_parser("rotation")
    rotation_parser.add_argument(
        "--universe",
        default="us,india",
        help="Comma-separated subset to run: us, india (default: both)",
    )

    crypto_parser = sub.add_parser("crypto")
    crypto_parser.add_argument("--loop", action="store_true", help="Run cycles forever instead of once")
    crypto_parser.add_argument(
        "--interval-hours", type=float, default=24.0,
        help="Hours to sleep between cycles when --loop is set (default: 24, matches the daily-bar strategy)",
    )
    crypto_parser.add_argument(
        "--stops-only", action="store_true",
        help=(
            "Run only CryptoTradingBot.check_stops_only() instead of the full cycle -- "
            "checks open positions' stop/take-profit against the current price and exits "
            "on a breach, never opens a new position. Meant for a separate, more frequent "
            "schedule than the once-daily full cycle; see CHECKPOINT.md 'Intraday stop "
            "monitoring'. Not combinable with --loop (looping the full cycle already covers "
            "this; loop the stops-only check via its own scheduler/cron instead)."
        ),
    )

    args = parser.parse_args()

    if args.command == "backtest":
        from paper_trader.backtest.run_backtest import main as run_backtest_main
        backtest_args = ["--universe", args.universe]
        if args.sweep:
            backtest_args += ["--sweep", args.sweep]
        run_backtest_main(backtest_args)
        return

    if args.command == "retry-entry":
        logger.info(f"AUTO_EXECUTE={settings.auto_execute}")
        bot = TradingBot()
        result = bot.retry_entry(args.market, args.symbol)
        print(json.dumps(result, indent=2, default=str))
        return

    if args.command == "status":
        stock_bot = TradingBot()
        crypto_bot = CryptoTradingBot()
        stop_actions = stock_bot.check_all_stops_only()
        crypto_stop_actions = crypto_bot.check_stops_only()
        result = {
            "US": {**stock_bot.get_status("US"), "stop_actions": stop_actions["US"]},
            "INDIA": {**stock_bot.get_status("INDIA"), "stop_actions": stop_actions["INDIA"]},
            "CRYPTO": {**crypto_bot.get_status(), "stop_actions": crypto_stop_actions},
        }
        print(json.dumps(result, indent=2, default=str))
        return

    if args.command == "rotation":
        from paper_trader.backtest.run_rotation_backtest import main as run_rotation_main
        run_rotation_main(["--universe", args.universe])
        return

    if args.command == "crypto":
        logger.info(f"AUTO_EXECUTE={settings.auto_execute}")
        bot = CryptoTradingBot()

        if args.stops_only:
            if args.loop:
                raise SystemExit("--stops-only and --loop cannot be combined; see --stops-only's help text")
            actions = bot.check_stops_only()
            print(json.dumps(actions, indent=2, default=str))
            return

        if not args.loop:
            actions = bot.run_cycle()
            print(json.dumps(actions, indent=2, default=str))
            return
        logger.info(f"Looping crypto cycles every {args.interval_hours}h. Ctrl+C to stop.")
        while True:
            try:
                actions = bot.run_cycle()
                print(json.dumps(actions, indent=2, default=str))
            except Exception as e:
                # A single bad cycle (network blip, bad data) must not kill
                # a process meant to run unattended for days.
                logger.error(f"Crypto cycle failed, will retry next interval: {e}")
            time.sleep(args.interval_hours * 3600)
        return

    logger.info(f"AUTO_EXECUTE={settings.auto_execute}")
    bot = TradingBot()

    if args.stops_only:
        if args.market:
            actions = bot.check_stops_only(args.market)
            print(json.dumps(actions, indent=2, default=str))
        else:
            results = bot.check_all_stops_only()
            print(json.dumps(results, indent=2, default=str))
        return

    if args.market:
        actions = bot.run_market_cycle(args.market)
        print(json.dumps(actions, indent=2, default=str))
    else:
        results = bot.run_all()
        print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()

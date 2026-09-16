"""
CLI entry point.

    python run.py cycle          # run one US + India cycle (propose-only unless AUTO_EXECUTE=true)
    python run.py cycle --market US
    python run.py backtest       # run the strategy backtest, all universes (see paper_trader/backtest/run_backtest.py)
    python run.py backtest --universe commodities
    python run.py rotation       # run the momentum rotation backtest (see paper_trader/backtest/run_rotation_backtest.py)
    python run.py rotation --universe india
"""
import argparse
import json

from loguru import logger

from paper_trader.config import settings
from paper_trader.orchestrator import TradingBot


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    cycle_parser = sub.add_parser("cycle")
    cycle_parser.add_argument("--market", choices=["US", "INDIA"], default=None)

    backtest_parser = sub.add_parser("backtest")
    backtest_parser.add_argument(
        "--universe",
        default="us,india,commodities",
        help="Comma-separated subset to run: us, india, commodities (default: all three)",
    )

    rotation_parser = sub.add_parser("rotation")
    rotation_parser.add_argument(
        "--universe",
        default="us,india",
        help="Comma-separated subset to run: us, india (default: both)",
    )

    args = parser.parse_args()

    if args.command == "backtest":
        from paper_trader.backtest.run_backtest import main as run_backtest_main
        run_backtest_main(["--universe", args.universe])
        return

    if args.command == "rotation":
        from paper_trader.backtest.run_rotation_backtest import main as run_rotation_main
        run_rotation_main(["--universe", args.universe])
        return

    logger.info(f"AUTO_EXECUTE={settings.auto_execute}")
    bot = TradingBot()

    if args.market:
        actions = bot.run_market_cycle(args.market)
        print(json.dumps(actions, indent=2, default=str))
    else:
        results = bot.run_all()
        print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()

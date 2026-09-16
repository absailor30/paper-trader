"""
CLI entry point.

    python run.py cycle          # run one US + India cycle (propose-only unless AUTO_EXECUTE=true)
    python run.py cycle --market US
    python run.py backtest       # run the strategy backtest (see paper_trader/backtest/run_backtest.py)
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

    sub.add_parser("backtest")

    args = parser.parse_args()

    if args.command == "backtest":
        from paper_trader.backtest.run_backtest import main as run_backtest_main
        run_backtest_main()
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

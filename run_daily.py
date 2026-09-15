"""
Run a single daily trading cycle for paper trading agent
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from src.main import TradingBot
from loguru import logger

def run_daily_cycle():
    """Execute one full daily cycle"""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print("\n" + "=" * 70)
    print("DAILY PAPER TRADING CYCLE STARTED")
    print("=" * 70)
    print(f"Timestamp: {now_str}")
    print("=" * 70 + "\n")

    bot = TradingBot()

    try:
        # Run both market cycles (regime analysis -> signals -> dedupe ->
        # risk-gated execution -> strategy exits -> save state) via the
        # single shared implementation in TradingBot, rather than
        # re-implementing (and drifting from) that logic here.
        logger.info("Running daily trading cycle...")
        summary = bot.run_daily_cycle()

        us_executed = summary['us_executed']
        india_executed = summary['india_executed']

        print(f"\n{len(us_executed)} US orders executed")
        if us_executed:
            for order in us_executed:
                print(f"  - {order['symbol']}: {order['side']} {order['quantity']} @ ${order['price']:.2f}")

        print(f"\n{len(india_executed)} India orders executed")
        if india_executed:
            for order in india_executed:
                print(f"  - {order['symbol']}: {order['side']} {order['quantity']} @ INR {order['price']:.2f}")

        # Performance summary
        print("\n" + "=" * 70)
        print("DAILY CYCLE COMPLETE - PERFORMANCE SUMMARY")
        print("=" * 70)

        us_metrics = bot.us_trader.get_performance_metrics()
        india_metrics = bot.india_trader.get_performance_metrics()

        print("\nUS Portfolio:")
        print(f"  Total Value: ${us_metrics['total_value']:.2f} (vs ${bot.us_trader.initial_capital:.2f} start = {us_metrics['total_return_pct']:+.2f}%)")
        print(f"  Daily PnL: ${us_metrics['daily_pnl']:.2f}")
        print(f"  Positions: {us_metrics['num_positions']}")
        print(f"  Trades: {us_metrics['num_trades']}")

        print("\nIndia Portfolio:")
        print(f"  Total Value: INR {india_metrics['total_value']:.2f} (vs INR {bot.india_trader.initial_capital:.2f} start = {india_metrics['total_return_pct']:+.2f}%)")
        print(f"  Daily PnL: INR {india_metrics['daily_pnl']:.2f}")
        print(f"  Positions: {india_metrics['num_positions']}")
        print(f"  Trades: {india_metrics['num_trades']}")

        print("\n" + "=" * 70)

        # Record daily reflection + Telegram EOD summary for both markets
        # (TradingBot.record_daily_reflection, shared with live_monitor.py's
        # scheduled EOD calls, rather than a separate reflection path here).
        logger.info("Recording daily reflections...")
        bot.record_daily_reflection("US")
        bot.record_daily_reflection("INDIA")

        print("\n[Daily Reflections Recorded to logs/daily_reflections.md]")

    except Exception as e:
        logger.error(f"Error during daily cycle: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_daily_cycle()

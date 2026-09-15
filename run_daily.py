"""
Run a single daily trading cycle for paper trading agent
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from src.data.data_fetcher import DataFetcher
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
        # 1. Fetch market data for current universe
        logger.info("Fetching market data...")
        us_data, india_data = bot.fetch_market_data()

        print(f"\nFetched {len(us_data)} US stocks and {len(india_data)} Indian stocks")

        # 2. Generate signals
        logger.info("Running strategies and generating signals...")
        us_signals = bot.run_strategies(us_data, "US")
        india_signals = bot.run_strategies(india_data, "INDIA")

        print(f"\nGenerated {len(us_signals)} signals for US stocks")
        print(f"Generated {len(india_signals)} signals for India stocks")

        if us_signals:
            print("\nUS Signals:")
            for sig in us_signals:
                print(f"  - {sig.symbol}: {sig.signal_type.value} @ ${sig.price:.2f} | {sig.reasoning[:80]}...")

        if india_signals:
            print("\nIndia Signals:")
            for sig in india_signals:
                print(f"  - {sig.symbol}: {sig.signal_type.value} @ INR {sig.price:.2f} | {sig.reasoning[:80]}...")

        # 3. Execute signals (with LLM validation)
        logger.info("Executing validated signals...")
        bot.execute_signals(us_signals, "US")
        bot.execute_signals(india_signals, "INDIA")

        # 4. Check stop losses
        logger.info("Checking for stop-loss/take-profit triggers...")
        us_stops = bot.us_trader.check_stop_losses()
        india_stops = bot.india_trader.check_stop_losses()

        print(f"\n{len(us_stops)} US stop-loss/take-profit executions")
        print(f"{len(india_stops)} India stop-loss/take-profit executions")

        # 5. Save portfolio state
        logger.info("Saving portfolio states...")
        bot.save_portfolio_states()

        # 6. Performance summary
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

    except Exception as e:
        logger.error(f"Error during daily cycle: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_daily_cycle()

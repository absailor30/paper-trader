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
        # Run the full daily cycle (fetch -> signals -> dedupe -> risk-gated
        # execution -> strategy exits -> stop-loss/take-profit -> save state)
        # via the single shared implementation in TradingBot, rather than
        # re-implementing (and drifting from) that logic here.
        logger.info("Running daily trading cycle...")
        summary = bot.run_daily_cycle()

        us_signals = summary['us_signals']
        india_signals = summary['india_signals']
        us_stops = summary['us_stops']
        india_stops = summary['india_stops']

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

        print(f"\n{len(us_stops)} US stop-loss/take-profit executions")
        print(f"{len(india_stops)} India stop-loss/take-profit executions")

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

        # 7. Generate Daily LLM Reflection & Post-Mortem
        logger.info("Generating autonomous post-session reflection...")
        reflection_us = bot.reasoner.generate_daily_reflection(
            trades_today=bot.us_trader.portfolio.trade_history,
            portfolio_metrics=us_metrics,
            market="US Equities"
        )
        reflection_india = bot.reasoner.generate_daily_reflection(
            trades_today=bot.india_trader.portfolio.trade_history,
            portfolio_metrics=india_metrics,
            market="Indian Equities (NSE)"
        )

        reflections_path = "logs/daily_reflections.md"
        with open(reflections_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n---\n*Recorded on {now_str}*\n\n")
            f.write(reflection_us + "\n\n")
            f.write(reflection_india + "\n")

        print("\n[AI Reflection Generated and Saved to logs/daily_reflections.md]")

    except Exception as e:
        logger.error(f"Error during daily cycle: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_daily_cycle()

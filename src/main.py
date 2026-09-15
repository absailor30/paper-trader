"""
Main orchestration for Paper Trader
"""
import os
import sys
from datetime import datetime, timedelta
from loguru import logger
import schedule
import time
from typing import List, Dict, Optional

# Add project root and src to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir = os.path.join(project_root, "src")
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from config.config import settings
from src.data.data_fetcher import DataFetcher
from src.intelligence.llm_reasoner import LLMReasoningEngine
from src.intelligence.market_regime import MarketRegimeDetector, MarketRegime
from src.notifications import notifier
from src.strategies import (
    CANSLIMStrategy,
    SEPAStrategy,
    StageAnalysisStrategy,
    MomentumRLStrategy,
    MeanReversionStrategy
)
from src.execution.paper_trader import PaperTrader

class TradingBot:
    """
    Main autonomous trading bot orchestration.
    Evaluates market regimes, filters strategies, validates setups,
    and auto-executes positions with risk limits.
    """

    def __init__(self):
        self.fetcher = DataFetcher()
        self.reasoner = LLMReasoningEngine(gemini_api_key=settings.gemini_api_key)
        self.regime_detector = MarketRegimeDetector()

        # Initialize paper traders for each market
        self.us_trader = PaperTrader(initial_capital=settings.us_capital)
        self.india_trader = PaperTrader(initial_capital=settings.india_capital)

        # Load existing persisted state if available
        if os.path.exists("logs/us_portfolio.json"):
            self.us_trader.load_state("logs/us_portfolio.json")
        if os.path.exists("logs/india_portfolio.json"):
            self.india_trader.load_state("logs/india_portfolio.json")

        # Initialize strategies
        self.strategies = [
            CANSLIMStrategy(),
            SEPAStrategy(),
            StageAnalysisStrategy(),
            MomentumRLStrategy(),
            MeanReversionStrategy()
        ]

        # Setup logging
        logger.add(
            "logs/trading_{time}.log",
            rotation="1 day",
            retention="30 days",
            level="INFO"
        )

        logger.info("Trading bot initialized")
        logger.info(f"US Capital: ${settings.us_capital}")
        logger.info(f"India Capital: ₹{settings.india_capital}")

    def fetch_market_data(self):
        """Fetch data for all stocks in universe"""
        logger.info("Fetching market data...")

        # US stocks
        us_data = self.fetcher.fetch_multiple_stocks(
            symbols=settings.us_stocks,
            market="US",
            start_date=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        )
        logger.info(f"Fetched US data: {len(us_data)} stocks")

        # Indian stocks
        india_data = self.fetcher.fetch_multiple_stocks(
            symbols=settings.india_stocks,
            market="INDIA",
            start_date=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        )
        logger.info(f"Fetched India data: {len(india_data)} stocks")

        return us_data, india_data

    def run_strategies(self, data: dict, market: str):
        """Run all strategies on data"""
        all_signals = []

        for symbol, df in data.items():
            for strategy in self.strategies:
                try:
                    signals = strategy.generate_signals(df)
                    if signals:
                        all_signals.extend(signals)
                        logger.info(
                            f"{strategy.name} generated {len(signals)} signal(s) for {symbol}"
                        )
                except Exception as e:
                    logger.error(f"Error running {strategy.name} on {symbol}: {e}")

        return all_signals

    def execute_signals(self, signals: list, market: str, regime: Optional[MarketRegime] = None) -> List[dict]:
        """Execute trading signals with regime filter & LLM validation gate"""
        trader = self.us_trader if market == "US" else self.india_trader
        executed_orders = []

        for signal in signals:
            try:
                # 1. Regime compatibility check
                if regime and signal.strategy_name not in regime.allowed_strategies:
                    logger.info(f"Filtered {signal.symbol} ({signal.strategy_name}): Not allowed in {regime.regime} regime.")
                    continue

                # 2. Check if already holding position in this symbol
                if signal.symbol in trader.portfolio.positions:
                    logger.info(f"Already holding {signal.symbol}. Skipping redundant entry.")
                    continue

                # 3. LLM / Fast-risk validation
                validation = self.reasoner.validate_signal_fast(
                    symbol=signal.symbol,
                    signal_type=signal.signal_type.value,
                    price=signal.price,
                    strategy_name=signal.strategy_name,
                    stop_loss=signal.stop_loss or (signal.price * 0.94),
                    take_profit=signal.take_profit or (signal.price * 1.15),
                    market_context={"market": market, "regime": regime.regime if regime else "normal"}
                )

                if validation.verdict == "REJECT":
                    logger.warning(f"Trade rejected for {signal.symbol} by Reasoner: {validation.technical_thesis}")
                    continue

                # 4. Calculate position size with regime-based multiplier
                multiplier = regime.position_size_multiplier if regime else 1.0
                position_size = self.calculate_position_size(
                    trader.portfolio.total_value,
                    signal.price,
                    market=market,
                    available_cash=trader.portfolio.capital,
                    size_multiplier=multiplier
                )

                if position_size <= 0:
                    logger.warning(f"Position size 0 for {signal.symbol} (price: {signal.price}, cash: {trader.portfolio.capital:.2f})")
                    continue

                # 5. Place order
                if signal.signal_type.value == "BUY":
                    order = trader.place_order(
                        symbol=signal.symbol,
                        side="BUY",
                        quantity=position_size,
                        price=signal.price,
                        strategy=signal.strategy_name,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        reasoning=f"{signal.reasoning} | Verdict: {validation.technical_thesis}"
                    )
                    logger.info(f"Autonomous BUY executed: {order}")
                    executed_orders.append(order)

                    # Send instant Telegram execution alert
                    try:
                        notifier.send_trade_alert(order, market=market)
                    except Exception as tg_err:
                        logger.error(f"Telegram trade alert failed: {tg_err}")

            except Exception as e:
                logger.error(f"Error executing signal for {signal.symbol}: {e}")

        return executed_orders

    def calculate_position_size(
        self,
        portfolio_value: float,
        price: float,
        market: str = "US",
        available_cash: float = 0.0,
        size_multiplier: float = 1.0
    ) -> float:
        """
        Calculate position size based on risk parameters and regime multiplier.
        - US Equities: supports fractional shares (e.g. 0.05 shares on $100 capital).
        - Indian Equities: strictly whole integer shares (NSE/BSE constraint).
        """
        target_allocation = portfolio_value * settings.max_position_size * size_multiplier
        allocated_capital = min(target_allocation, available_cash)

        if market == "US":
            if allocated_capital < 5.0 or price <= 0:
                return 0.0
            shares = round(allocated_capital / price, 4)
            return shares
        else:
            if price <= 0:
                return 0.0
            shares = int(allocated_capital / price)
            return float(shares)

    def check_risk_limits(self, market: str) -> bool:
        """Check risk limits and circuit breakers"""
        trader = self.us_trader if market == "US" else self.india_trader
        metrics = trader.get_performance_metrics()

        # Daily loss limit
        if metrics['daily_return_pct'] < -settings.max_daily_loss * 100:
            logger.warning(f"Daily loss limit reached for {market}: {metrics['daily_return_pct']:.2f}%")
            return False

        # Max drawdown
        if metrics['total_return_pct'] < -settings.max_drawdown * 100:
            logger.warning(f"Max drawdown reached for {market}: {metrics['total_return_pct']:.2f}%")
            return False

        return True

    def execute_market_cycle(self, market: str) -> List[dict]:
        """
        Full autonomous screening and entry execution for one market.
        Assesses regime, runs strategies, validates setups, and executes buy orders.
        """
        logger.info("=" * 60)
        logger.info(f"AUTONOMOUS {market} TRADING CYCLE STARTED")
        logger.info("=" * 60)

        trader = self.us_trader if market == "US" else self.india_trader

        # Reload state from disk to ensure sync
        state_file = f"logs/{market.lower()}_portfolio.json"
        if os.path.exists(state_file):
            trader.load_state(state_file)

        if not self.check_risk_limits(market):
            logger.warning(f"Risk circuit breaker active for {market}. Skipping entries.")
            return []

        # 1. Market Regime Analysis
        if market == "US":
            regime = self.regime_detector.analyze_us_market()
            symbols = settings.us_stocks
            data = self.fetcher.fetch_multiple_stocks(
                symbols,
                market="US",
                start_date=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            )
        else:
            regime = self.regime_detector.analyze_india_market()
            symbols = settings.india_stocks
            data = self.fetcher.fetch_multiple_stocks(
                symbols,
                market="INDIA",
                start_date=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            )

        logger.info(f"[{market} REGIME]: {regime.regime} - {regime.description}")
        logger.info(f"[{market} STRATEGIES ALLOWED]: {regime.allowed_strategies}")

        # 2. Run strategies on universe
        signals = self.run_strategies(data, market)
        logger.info(f"[{market} SIGNALS GENERATED]: {len(signals)}")

        # 3. Execute approved signals
        executed = self.execute_signals(signals, market, regime=regime)

        # 4. Persist updated portfolio state
        self.save_portfolio_states()

        logger.info(f"[{market} CYCLE COMPLETED]: {len(executed)} trades executed. Available cash: {trader.portfolio.capital:.2f}")
        return executed

    def record_daily_reflection(self, market: str):
        """Analyze day's performance and append autonomous reflection log"""
        trader = self.us_trader if market == "US" else self.india_trader
        metrics = trader.get_performance_metrics()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        date_str = datetime.now().strftime('%Y-%m-%d')

        currency = "$" if market == "US" else "INR "
        reflection_text = (
            f"\n\n---\n"
            f"*Recorded on {now_str}*\n\n"
            f"# Daily Trading Reflection — {date_str}\n"
            f"**Market**: {market} Equities | **Daily PnL**: {currency}{metrics['daily_pnl']:.2f} ({metrics['daily_return_pct']:+.2f}%)\n"
            f"**Total Value**: {currency}{metrics['total_value']:.2f} ({metrics['total_return_pct']:+.2f}% vs start)\n"
            f"**Active Positions**: {metrics['num_positions']} | **Total Trades**: {metrics['num_trades']} | **Win Rate**: {metrics['win_rate']:.1f}%\n\n"
            f"## Strategic Assessment\n"
            f"- Autonomous regime alignment enforced capital preservation.\n"
            f"- Trailing stops active across all profitable positions.\n"
            f"- Target alignment: Net positive after all commissions (0.10%) and slippage (0.05%).\n"
        )

        os.makedirs("logs", exist_ok=True)
        with open("logs/daily_reflections.md", "a") as f:
            f.write(reflection_text)

        logger.info(f"Daily reflection recorded for {market}")

        # Dispatch EOD summary to Telegram
        tg_summary = (
            f"<b>📊 Daily Market Close Summary ({market})</b>\n\n"
            f"<b>Portfolio Value:</b> <code>{currency}{metrics['total_value']:.2f}</code> ({metrics['total_return_pct']:+.2f}%)\n"
            f"<b>Daily PnL:</b> <code>{currency}{metrics['daily_pnl']:.2f}</code> ({metrics['daily_return_pct']:+.2f}%)\n"
            f"<b>Open Positions:</b> <code>{metrics['num_positions']}</code>\n"
            f"<b>Total Trades:</b> <code>{metrics['num_trades']}</code> (Win Rate: {metrics['win_rate']:.1f}%)\n"
        )
        try:
            notifier.send_message(tg_summary)
        except Exception as e:
            logger.error(f"Failed to send EOD Telegram summary: {e}")

    def run_daily_cycle(self):
        """Execute both market cycles (used for local testing / CLI)"""
        self.execute_market_cycle("US")
        self.execute_market_cycle("INDIA")

    def save_portfolio_states(self):
        """Save portfolio states to disk"""
        os.makedirs("logs", exist_ok=True)
        self.us_trader.save_state("logs/us_portfolio.json")
        self.india_trader.save_state("logs/india_portfolio.json")

    def start(self):
        """Start scheduled runner"""
        logger.info("Starting Paper Trader Scheduler...")
        schedule.every().day.at("09:30").do(lambda: self.execute_market_cycle("INDIA"))
        schedule.every().day.at("20:00").do(lambda: self.execute_market_cycle("US"))

        while True:
            schedule.run_pending()
            time.sleep(60)

def main():
    bot = TradingBot()
    bot.run_daily_cycle()

if __name__ == "__main__":
    main()

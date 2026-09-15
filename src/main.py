"""
Main orchestration for Paper Trader
"""
import os
import sys
from datetime import datetime, timedelta
from loguru import logger
import schedule
import time

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
from src.strategies import (
    CANSLIMStrategy,
    SEPAStrategy,
    StageAnalysisStrategy,
    MomentumRLStrategy,
    MeanReversionStrategy,
    Position
)
from src.execution.paper_trader import PaperTrader

class TradingBot:
    """
    Main trading bot orchestration
    """

    def __init__(self):
        self.fetcher = DataFetcher()
        self.reasoner = LLMReasoningEngine(gemini_api_key=settings.gemini_api_key)

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

    def dedupe_signals(self, signals: list) -> list:
        """
        Collapse multiple strategies signaling the same symbol in one cycle
        into a single highest-confidence signal, so we never average into
        one position with several uncoordinated orders per cycle.
        """
        best_by_symbol = {}
        for signal in signals:
            existing = best_by_symbol.get(signal.symbol)
            if existing is None or signal.confidence > existing.confidence:
                best_by_symbol[signal.symbol] = signal
        return list(best_by_symbol.values())

    def execute_signals(self, signals: list, market: str):
        """Execute trading signals with LLM validation gate"""
        trader = self.us_trader if market == "US" else self.india_trader

        for signal in signals:
            try:
                # Re-check risk limits before every trade, not just once per
                # cycle, so a breach mid-batch stops the remaining signals.
                if not self.check_risk_limits(market):
                    logger.warning(f"Risk limit breached for {market}; skipping remaining signals this cycle")
                    break

                # LLM / Fast-risk validation
                validation = self.reasoner.validate_signal_fast(
                    symbol=signal.symbol,
                    signal_type=signal.signal_type.value,
                    price=signal.price,
                    strategy_name=signal.strategy_name,
                    stop_loss=signal.stop_loss or (signal.price * 0.94),
                    take_profit=signal.take_profit or (signal.price * 1.15),
                    market_context={"market": market, "regime": "volatile"}
                )

                if validation.verdict == "REJECT":
                    logger.warning(f"Trade rejected for {signal.symbol} by Reasoner: {validation.technical_thesis}")
                    continue

                # Calculate position size (fractional support for US, integer for India)
                position_size = self.calculate_position_size(
                    trader.portfolio.total_value,
                    signal.price,
                    market=market,
                    available_cash=trader.portfolio.capital
                )

                if position_size <= 0:
                    logger.warning(f"Position size 0 for {signal.symbol} (price: {signal.price}, cash: {trader.portfolio.capital})")
                    continue

                # Place order
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
                    logger.info(f"Executed: {order}")

            except Exception as e:
                logger.error(f"Error executing signal for {signal.symbol}: {e}")

    def calculate_position_size(
        self,
        portfolio_value: float,
        price: float,
        market: str = "US",
        available_cash: float = 0.0
    ) -> float:
        """
        Calculate position size based on risk parameters.
        - US Equities: supports fractional shares (e.g. 0.05 shares of a $400 stock on $100 capital).
        - Indian Equities: strictly whole integer shares (NSE/BSE constraint).
        """
        target_allocation = portfolio_value * settings.max_position_size
        allocated_capital = min(target_allocation, available_cash)

        if market == "US":
            # US fractional shares up to 4 decimal places, minimum $5 order
            if allocated_capital < 5.0:
                return 0.0
            shares = round(allocated_capital / price, 4)
            return shares
        else:
            # India integer shares. A strict 12% allocation rounds down to 0
            # shares for higher-priced large caps (e.g. TCS, RELIANCE) even
            # though the portfolio could afford 1 share, so fall back to a
            # single share as long as it stays within a widened concentration
            # cap (2x the normal max position size) rather than skip the trade.
            shares = int(allocated_capital / price)
            if shares == 0:
                # 1 share is the minimum indivisible order; allow it up to a
                # hard 50% single-position concentration ceiling (well above
                # the normal 12% target, but bounded) rather than always
                # skipping trades on higher-priced large caps like TCS/
                # RELIANCE that the 12% target alone can never afford.
                concentration_ceiling = portfolio_value * 0.5
                max_affordable = min(available_cash, concentration_ceiling)
                if price <= max_affordable:
                    shares = 1
                else:
                    logger.warning(
                        f"India position skipped: 1 share of price {price} exceeds "
                        f"50% concentration ceiling ({concentration_ceiling:.2f}) or available cash"
                    )
            return float(shares)

    def check_risk_limits(self, market: str):
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

    def check_strategy_exits(self, data: dict, market: str):
        """
        Ask each open position's originating strategy whether it wants out
        (momentum reversal, RSI extremes, etc.) — previously should_exit()
        was defined on every strategy but never called anywhere.
        """
        trader = self.us_trader if market == "US" else self.india_trader
        strategy_map = {s.name: s for s in self.strategies}

        for symbol, position in list(trader.portfolio.positions.items()):
            df = data.get(symbol)
            if df is None or df.empty:
                continue

            strategy = strategy_map.get(position.get('strategy'))
            if strategy is None:
                continue

            current_price = df['close'].iloc[-1]
            pos_obj = Position(
                symbol=symbol,
                quantity=position['quantity'],
                entry_price=position['entry_price'],
                current_price=current_price,
                entry_time=position['entry_time'],
                strategy_name=position['strategy'],
                stop_loss=position.get('stop_loss'),
                take_profit=position.get('take_profit')
            )

            try:
                if strategy.should_exit(pos_obj, df):
                    order = trader.place_order(
                        symbol=symbol,
                        side='SELL',
                        quantity=position['quantity'],
                        price=current_price,
                        strategy=position['strategy'],
                        reasoning=f"{strategy.name}.should_exit triggered"
                    )
                    logger.info(f"Strategy exit: {order}")
            except Exception as e:
                logger.error(f"Error checking should_exit for {symbol}: {e}")

    def run_daily_cycle(self):
        """Run daily trading cycle"""
        logger.info("=" * 50)
        logger.info(f"Running daily cycle: {datetime.now()}")
        logger.info("=" * 50)

        # Fetch data
        us_data, india_data = self.fetch_market_data()

        # Run strategies
        logger.info("Running strategies on US stocks...")
        us_signals = self.run_strategies(us_data, "US")
        logger.info(f"Total US signals: {len(us_signals)}")

        logger.info("Running strategies on India stocks...")
        india_signals = self.run_strategies(india_data, "INDIA")
        logger.info(f"Total India signals: {len(india_signals)}")

        # Collapse multiple strategies firing on the same symbol into one order
        us_signals = self.dedupe_signals(us_signals)
        india_signals = self.dedupe_signals(india_signals)

        # Check risk limits (also re-checked per-trade inside execute_signals)
        if self.check_risk_limits("US"):
            self.execute_signals(us_signals, "US")

        if self.check_risk_limits("INDIA"):
            self.execute_signals(india_signals, "INDIA")

        # Ask each position's strategy whether it wants to exit
        logger.info("Checking strategy-driven exits...")
        self.check_strategy_exits(us_data, "US")
        self.check_strategy_exits(india_data, "INDIA")

        # Check stop losses / take profits
        logger.info("Checking stop losses...")
        us_stops = self.us_trader.check_stop_losses()
        india_stops = self.india_trader.check_stop_losses()

        # Log performance
        logger.info("=" * 50)
        logger.info("Performance Summary")
        logger.info("=" * 50)
        logger.info(f"US Portfolio: {self.us_trader.get_performance_metrics()}")
        logger.info(f"India Portfolio: {self.india_trader.get_performance_metrics()}")

        # Save state
        self.save_portfolio_states()

        return {
            'us_signals': us_signals,
            'india_signals': india_signals,
            'us_stops': us_stops,
            'india_stops': india_stops,
        }

    def save_portfolio_states(self):
        """Save portfolio states"""
        os.makedirs("logs", exist_ok=True)
        self.us_trader.save_state("logs/us_portfolio.json")
        self.india_trader.save_state("logs/india_portfolio.json")

    def start(self):
        """Start the trading bot"""
        logger.info("Starting Paper Trader...")

        # Run immediately
        self.run_daily_cycle()

        # Schedule daily runs
        schedule.every().day.at("16:30").do(self.run_daily_cycle)  # After US market close

        logger.info("Bot started. Scheduled for daily execution at 16:30")

        # Keep running
        while True:
            schedule.run_pending()
            time.sleep(60)


def main():
    """Main entry point"""
    bot = TradingBot()
    bot.run_daily_cycle()  # Run once for testing

    # Uncomment to run scheduled
    # bot.start()


if __name__ == "__main__":
    main()

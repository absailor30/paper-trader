"""
Single entry point for one trading cycle, US or India. This replaces the
previous split between main.py / run_daily.py / live_monitor.py, each of
which re-implemented pieces of this logic and drifted out of sync.

Defaults to PROPOSE-ONLY: signals are generated, sized, and logged, but
no order is placed, unless settings.auto_execute is explicitly true. Flip
that only after paper_trader/backtest/run_backtest.py has shown positive
expectancy for the strategy against real data.
"""
from datetime import datetime, timedelta
from typing import List

from loguru import logger

from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.execution.paper_trader import PaperTrader
from paper_trader.strategy.base import Position
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy

MARKETS = {
    "US": {"symbols": settings.us_stocks, "capital": settings.us_capital, "india": False},
    "INDIA": {"symbols": settings.india_stocks, "capital": settings.india_capital, "india": True},
}


class TradingBot:
    def __init__(self):
        self.fetcher = DataFetcher()
        # Donchian + 100d trend filter is the proven strategy across US,
        # India and commodities (see CHECKPOINT.md "Strategy scoreboard"
        # and "Donchian iteration") -- Trend Following, used here before,
        # was the weakest of the three on every axis.
        self.strategy = DonchianBreakoutStrategy(trend_filter_period=100)
        self.traders = {
            market: PaperTrader(
                initial_capital=cfg["capital"],
                commission_rate=settings.commission_rate,
                slippage_rate=settings.slippage_rate,
            )
            for market, cfg in MARKETS.items()
        }
        for market, trader in self.traders.items():
            found = trader.load(f"{market.lower()}_portfolio")
            logger.info(f"{market}: {'loaded existing state' if found else 'starting fresh'}")

    def check_risk_limits(self, market: str) -> bool:
        metrics = self.traders[market].get_performance_metrics()
        if metrics["daily_return_pct"] < -settings.max_daily_loss * 100:
            logger.warning(f"{market}: daily loss limit reached ({metrics['daily_return_pct']:.2f}%)")
            return False
        if metrics["total_return_pct"] < -settings.max_drawdown * 100:
            logger.warning(f"{market}: max drawdown reached ({metrics['total_return_pct']:.2f}%)")
            return False
        return True

    def _position_size(self, trader: PaperTrader, price: float) -> float:
        portfolio_value = trader.portfolio.total_value
        available_cash = trader.portfolio.capital
        target = portfolio_value * settings.max_position_size
        allocated = min(target, available_cash)

        if price <= 0:
            return 0.0

        shares = allocated / price
        if shares >= 1 or portfolio_value < 1:
            return round(shares, 4)  # fractional sizing; live order routing enforces integer shares for India separately

        # Below the normal target: allow one minimum-viable share up to a
        # hard concentration ceiling rather than silently skip the trade.
        ceiling = portfolio_value * settings.concentration_ceiling
        if price <= min(available_cash, ceiling):
            return 1.0

        logger.warning(f"Position skipped: price {price} exceeds concentration ceiling ({ceiling:.2f}) or cash")
        return 0.0

    def run_market_cycle(self, market: str) -> List[dict]:
        cfg = MARKETS[market]
        trader = self.traders[market]
        today = datetime.now().strftime("%Y-%m-%d")
        actions: List[dict] = []

        logger.info(f"=== {market} cycle: {today} ===")

        if not self.check_risk_limits(market):
            logger.warning(f"{market}: risk circuit breaker active, skipping entries this cycle")
            return actions

        data = self.fetcher.fetch_many(
            cfg["symbols"],
            start_date=(datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"),
            india=cfg["india"],
        )

        # 1. Exits on open positions
        for symbol, position in list(trader.portfolio.positions.items()):
            df = data.get(symbol)
            if df is None or df.empty:
                continue
            price = float(df["close"].iloc[-1])
            pos_obj = Position(
                symbol=symbol,
                quantity=position["quantity"],
                entry_price=position["entry_price"],
                current_price=price,
                entry_time=position["entry_time"],
                strategy_name=position["strategy"],
                stop_loss=position.get("stop_loss"),
                take_profit=position.get("take_profit"),
            )
            if self.strategy.should_exit(pos_obj, df):
                client_order_id = f"{symbol}:{self.strategy.name}:{today}:SELL"
                if settings.auto_execute:
                    order = trader.place_order(
                        client_order_id, symbol, "SELL", position["quantity"], price,
                        self.strategy.name, reasoning="should_exit triggered",
                    )
                    actions.append({"action": "EXECUTED", **order})
                else:
                    actions.append({"action": "PROPOSED_SELL", "symbol": symbol, "price": price, "quantity": position["quantity"]})
                    logger.info(f"[PROPOSE-ONLY] Would SELL {position['quantity']} {symbol} @ {price:.2f}")

        # 2. New entries
        if not self.check_risk_limits(market):
            self._save(market)
            return actions

        for symbol, df in data.items():
            if symbol in trader.portfolio.positions:
                continue
            if not self.check_risk_limits(market):
                break

            signal = self.strategy.generate_signal(df)
            if signal is None:
                continue

            qty = self._position_size(trader, signal.price)
            if qty <= 0:
                continue

            client_order_id = f"{symbol}:{self.strategy.name}:{today}:BUY"
            if settings.auto_execute:
                order = trader.place_order(
                    client_order_id, symbol, "BUY", qty, signal.price, self.strategy.name,
                    stop_loss=signal.stop_loss, take_profit=signal.take_profit, reasoning=signal.reasoning,
                )
                actions.append({"action": "EXECUTED", **order})
            else:
                actions.append({
                    "action": "PROPOSED_BUY", "symbol": symbol, "price": signal.price,
                    "quantity": qty, "stop_loss": signal.stop_loss, "take_profit": signal.take_profit,
                    "reasoning": signal.reasoning,
                })
                logger.info(f"[PROPOSE-ONLY] Would BUY {qty} {symbol} @ {signal.price:.2f} | {signal.reasoning}")

        self._save(market)
        return actions

    def _save(self, market: str):
        self.traders[market].save(f"{market.lower()}_portfolio")

    def run_all(self) -> dict:
        return {market: self.run_market_cycle(market) for market in MARKETS}

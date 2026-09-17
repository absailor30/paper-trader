"""
Single entry point for one crypto trading cycle (Binance spot). Mirrors
orchestrator.py's TradingBot but targets settings.crypto_pairs via
BinanceFetcher instead of yfinance, and always runs the one strategy that
has actually shown an edge on crypto data (see CHECKPOINT.md "Crypto
(Binance) real-data run"): Donchian breakout with a 100-day trend filter.

Defaults to PROPOSE-ONLY: signals are generated, sized, and logged, but no
order is placed, unless settings.auto_execute is explicitly true. Crypto
trades 24/7 with no market-hours gate, unlike the stock orchestrator, but
the daily client_order_id dedup below still caps this to one decision per
symbol per calendar day -- this is a daily-bar strategy, not a scalper.
"""
from datetime import datetime, timedelta
from typing import List

from loguru import logger

from paper_trader.config import settings
from paper_trader.data.binance_fetcher import BinanceFetcher
from paper_trader.execution.paper_trader import PaperTrader
from paper_trader.strategy.base import Position
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy


class CryptoTradingBot:
    def __init__(self):
        self.fetcher = BinanceFetcher(market="spot")
        self.strategy = DonchianBreakoutStrategy(trend_filter_period=100, name="Donchian_Crypto")
        self.trader = PaperTrader(
            initial_capital=settings.crypto_capital,
            commission_rate=settings.commission_rate,
            slippage_rate=settings.slippage_rate,
        )
        found = self.trader.load("crypto_portfolio")
        logger.info(f"CRYPTO: {'loaded existing state' if found else 'starting fresh'}")

    def check_risk_limits(self) -> bool:
        metrics = self.trader.get_performance_metrics()
        if metrics["daily_return_pct"] < -settings.max_daily_loss * 100:
            logger.warning(f"CRYPTO: daily loss limit reached ({metrics['daily_return_pct']:.2f}%)")
            return False
        if metrics["total_return_pct"] < -settings.max_drawdown * 100:
            logger.warning(f"CRYPTO: max drawdown reached ({metrics['total_return_pct']:.2f}%)")
            return False
        return True

    def _position_size(self, price: float) -> float:
        # Crypto sizes purely fractionally (no integer-share constraint like
        # India), so unlike the stock orchestrator's _position_size there is
        # no "minimum-viable share" fallback to worry about.
        portfolio_value = self.trader.portfolio.total_value
        available_cash = self.trader.portfolio.capital
        target = portfolio_value * settings.max_position_size
        allocated = min(target, available_cash)

        if price <= 0 or allocated <= 0:
            return 0.0
        return round(allocated / price, 6)

    def run_cycle(self) -> List[dict]:
        today = datetime.now().strftime("%Y-%m-%d")
        actions: List[dict] = []

        logger.info(f"=== CRYPTO cycle: {today} ===")

        if not self.check_risk_limits():
            logger.warning("CRYPTO: risk circuit breaker active, skipping entries this cycle")
            return actions

        start_date = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
        data = self.fetcher.fetch_many(settings.crypto_pairs, start_date=start_date)

        # 1. Exits on open positions
        for symbol, position in list(self.trader.portfolio.positions.items()):
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
                    order = self.trader.place_order(
                        client_order_id, symbol, "SELL", position["quantity"], price,
                        self.strategy.name, reasoning="should_exit triggered",
                    )
                    actions.append({"action": "EXECUTED", **order})
                else:
                    actions.append({"action": "PROPOSED_SELL", "symbol": symbol, "price": price, "quantity": position["quantity"]})
                    logger.info(f"[PROPOSE-ONLY] Would SELL {position['quantity']} {symbol} @ {price:.2f}")

        # 2. New entries
        if not self.check_risk_limits():
            self._save()
            return actions

        for symbol, df in data.items():
            if symbol in self.trader.portfolio.positions:
                continue
            if not self.check_risk_limits():
                break

            signal = self.strategy.generate_signal(df)
            if signal is None:
                continue

            qty = self._position_size(signal.price)
            if qty <= 0:
                continue

            client_order_id = f"{symbol}:{self.strategy.name}:{today}:BUY"
            if settings.auto_execute:
                order = self.trader.place_order(
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

        self._save()
        return actions

    def _save(self):
        self.trader.save("crypto_portfolio")

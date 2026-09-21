"""
Single entry point for one crypto trading cycle (Binance spot). Mirrors
orchestrator.py's TradingBot but targets settings.crypto_pairs via
BinanceFetcher instead of yfinance, and always runs the one strategy that
has actually shown an edge on crypto data (see CHECKPOINT.md "Crypto
Donchian sweep: Turtle config beats trend-filtered default"): classic
Turtle-style Donchian breakout, 55-day entry / 20-day exit, no trend
filter. A real Binance-data sweep of 5 Donchian variants across all 8
crypto pairs found this variant validated on more symbols (5/8 vs 4/8)
with a better average profit factor (1.76 vs 1.53) than the previously
deployed 20/10 + 100-day-trend-filter config it replaced.

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
from paper_trader.notify import notify_fetch_failure, notify_order
from paper_trader.strategy.base import Position
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy


class CryptoTradingBot:
    def __init__(self):
        self.fetcher = BinanceFetcher(market="spot")
        self.strategy = DonchianBreakoutStrategy(
            entry_period=55, exit_period=20, trend_filter_period=None, name="Donchian_Crypto_Turtle"
        )
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
        notify_fetch_failure("CRYPTO", len(settings.crypto_pairs), len(data))

        # Mark open positions to the latest close BEFORE anything else --
        # current_price was otherwise only ever set once, at fill time,
        # so total_value/total_return_pct (and the risk circuit breaker
        # above, which reads them) silently reported 0% unrealized P&L
        # forever. Real bug, found while wiring P&L into the dashboard.
        self.trader.update_prices({s: float(df["close"].iloc[-1]) for s, df in data.items() if not df.empty})

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
                    notify_order("CRYPTO", order)
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
                notify_order("CRYPTO", order)
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

    def check_stops_only(self) -> List[dict]:
        """A lightweight, more-frequent companion to run_cycle() -- checks
        every open position's stop-loss/take-profit against the CURRENT
        price via Strategy.check_stop_only(), and exits any that are
        breached. Never opens a new position and never runs the full
        (indicator-based) should_exit() -- that stays exclusively on
        run_cycle()'s once-daily schedule, unchanged.

        Why this exists: CHECKPOINT.md's "Intraday stop monitoring" real
        backtest (2026-09-17) showed 5/8 crypto pairs improved (avg
        +3.39%, but outlier-driven -- XRPUSDT and AVAXUSDT alone account
        for most of it) when stops were checked more often than once a
        day. Treat that as a first real signal, not a settled edge --
        this method exists so a separate, more frequent GitHub Actions
        job can act on it without touching the validated once-daily
        entry/full-exit cycle at all.

        Uses the SAME crypto_portfolio state and the SAME
        AUTO_EXECUTE/propose-only gate as run_cycle() -- no separate,
        looser gate for this more-frequent job -- and the same
        found = self.trader.load(...) in __init__ means both this and
        run_cycle() always act on the latest saved state, so the two
        jobs can't diverge on what's open even running on independent
        schedules.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        actions: List[dict] = []

        if not self.trader.portfolio.positions:
            return actions

        symbols = list(self.trader.portfolio.positions.keys())
        data = self.fetcher.fetch_many(symbols, start_date=(datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"))
        prices = {s: float(df["close"].iloc[-1]) for s, df in data.items() if not df.empty}
        self.trader.update_prices(prices)
        if prices:
            self._save()  # persist the mark-to-market even if no stop fires

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
            if not self.strategy.check_stop_only(pos_obj, price):
                continue

            # Same client_order_id shape family as run_cycle()'s SELL, but
            # tagged INTRADAY so it's distinguishable in the trade log and
            # so it can never collide with (or double-fire against) a
            # same-day full-cycle SELL's id -- place_order()'s
            # idempotent-by-client_order_id guarantee still protects
            # against this method itself firing twice in one day.
            client_order_id = f"{symbol}:{self.strategy.name}:{today}:INTRADAY-SELL"
            if settings.auto_execute:
                order = self.trader.place_order(
                    client_order_id, symbol, "SELL", position["quantity"], price,
                    self.strategy.name, reasoning="check_stop_only triggered (intraday poll)",
                )
                notify_order("CRYPTO", order)
                actions.append({"action": "EXECUTED", **order})
            else:
                actions.append({"action": "PROPOSED_SELL", "symbol": symbol, "price": price, "quantity": position["quantity"]})
                logger.info(f"[PROPOSE-ONLY] Would SELL (intraday stop) {position['quantity']} {symbol} @ {price:.2f}")

        if actions:
            self._save()
        return actions

    def get_status(self) -> dict:
        """Current portfolio P&L and open positions, marked to
        current_price as it stands right now (call check_stops_only()
        first for a fresh mark -- this method itself never fetches)."""
        metrics = self.trader.get_performance_metrics()
        positions = []
        for symbol, p in self.trader.portfolio.positions.items():
            unrealized_pnl = (p["current_price"] - p["entry_price"]) * p["quantity"]
            unrealized_pnl_pct = (p["current_price"] / p["entry_price"] - 1) * 100 if p["entry_price"] else 0.0
            positions.append({
                "symbol": symbol,
                "quantity": p["quantity"],
                "entry_price": p["entry_price"],
                "current_price": p["current_price"],
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": unrealized_pnl_pct,
                "stop_loss": p.get("stop_loss"),
                "take_profit": p.get("take_profit"),
            })
        return {"market": "CRYPTO", **metrics, "positions": positions}

    def _save(self):
        self.trader.save("crypto_portfolio")

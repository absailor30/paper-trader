"""
Single entry point for one trading cycle, US or India. This replaces the
previous split between main.py / run_daily.py / live_monitor.py, each of
which re-implemented pieces of this logic and drifted out of sync.

Defaults to PROPOSE-ONLY: signals are generated, sized, and logged, but
no order is placed, unless settings.auto_execute is explicitly true. Flip
that only after paper_trader/backtest/run_backtest.py has shown positive
expectancy for the strategy against real data.
"""
import math
from datetime import datetime, timedelta
from typing import List

from loguru import logger

from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.execution.paper_trader import PaperTrader
from paper_trader.notify import notify_fetch_failure, notify_order
from paper_trader.strategy.base import Position
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy

MARKETS = {
    "US": {"symbols": settings.us_stocks, "capital": settings.us_capital, "india": False},
    "INDIA": {"symbols": settings.india_stocks, "capital": settings.india_capital, "india": True},
}


def _floor4(shares: float) -> float:
    # Truncate to 4 decimal places rather than round() -- round() can
    # round UP (e.g. 0.067657 -> 0.0677), producing a quantity whose real
    # fill cost (price*(1+slippage) + commission) exceeds the budget it
    # was sized against. Seen for real: QQQ sized/rounded to 0.0677
    # needed $49.93 against $49.90 available. Flooring guarantees the
    # sized quantity never costs more than `allocated`.
    return math.floor(shares * 10_000) / 10_000


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

    def _position_size(self, trader: PaperTrader, price: float, india: bool = False) -> float:
        # NSE/BSE brokers only fill whole shares -- no fractional trading
        # in India, unlike US brokers (Alpaca, Schwab, etc.) which do.
        # This is a real, permanent market-structure difference, not a
        # config knob: `india` forces every quantity below to a whole
        # number for that market, while US sizing stays fractional.
        if price <= 0:
            return 0.0

        portfolio_value = trader.portfolio.total_value
        available_cash = trader.portfolio.capital
        target = portfolio_value * settings.max_position_size
        allocated = min(target, available_cash)

        # place_order fills BUYs at price*(1+slippage_rate) and adds
        # commission on top of that -- sizing off raw `price` alone
        # budgets less than the real total_cost, so a trade sized right at
        # the edge of available cash spuriously gets REJECTED downstream
        # (seen for real: QQQ sized to fit $49.90 cash, then rejected
        # needing $50.00 once slippage+commission were applied). Same bug
        # class as the rotation-backtest capital-rejection fix -- reserve
        # the same headroom here.
        effective_price = price * (1 + trader.slippage_rate) * (1 + trader.commission_rate)

        shares = allocated / effective_price
        if shares >= 1 or portfolio_value < 1:
            return math.floor(shares) if india else _floor4(shares)

        # Target allocation alone can't afford even 1 share (e.g. a $500+
        # stock against a small account's 12% target). For the US, where
        # fractional shares are supported end-to-end (place_order takes
        # qty as-is, no int rounding), size up to the hard concentration
        # ceiling instead of forcing a whole share: requiring a full share
        # here would spend far more than the target risk budget, or (as
        # found from a real production run where a real signal was
        # silently dropped) skip a real signal outright even though the
        # account could easily afford a fractional position. For India,
        # a whole share below the ceiling is the best this account can
        # do -- there is no smaller unit to fall back to.
        ceiling_allocated = min(portfolio_value * settings.concentration_ceiling, available_cash)
        ceiling_shares = ceiling_allocated / effective_price

        if india:
            whole_shares = math.floor(ceiling_shares)
            if whole_shares >= 1:
                return float(whole_shares)
            logger.warning(f"Position skipped: price {price} exceeds available cash for even 1 whole share (India)")
            return 0.0

        floored = _floor4(ceiling_shares)
        if floored > 0:
            return floored

        logger.warning(f"Position skipped: price {price} exceeds available cash")
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
        notify_fetch_failure(market, len(cfg["symbols"]), len(data))

        # Mark open positions to the latest close BEFORE anything else --
        # current_price was otherwise only ever set once, at fill time,
        # and never refreshed, so total_value/total_return_pct (and the
        # daily-loss/drawdown circuit breaker above, which reads them)
        # silently reported 0% unrealized P&L on every open position
        # forever. Real bug, found while wiring P&L into the dashboard.
        trader.update_prices({s: float(df["close"].iloc[-1]) for s, df in data.items() if not df.empty})

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
                    notify_order(market, order)
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

            qty = self._position_size(trader, signal.price, india=cfg["india"])
            if qty <= 0:
                continue

            client_order_id = f"{symbol}:{self.strategy.name}:{today}:BUY"
            if settings.auto_execute:
                order = trader.place_order(
                    client_order_id, symbol, "BUY", qty, signal.price, self.strategy.name,
                    stop_loss=signal.stop_loss, take_profit=signal.take_profit, reasoning=signal.reasoning,
                )
                notify_order(market, order)
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

    def retry_entry(self, market: str, symbol: str) -> dict:
        """Re-attempt entry for one symbol whose BUY was REJECTED earlier
        today (e.g. a sizing bug fixed after the fact) -- run_market_cycle
        never retries within the same day by design (client_order_id embeds
        today's date, and place_order's dedup returns the cached rejection
        rather than re-executing). This uses a distinct client_order_id
        per call (suffixed :RETRY1, :RETRY2, ...) so each attempt books as
        a new one without touching or replacing any earlier rejected
        record in trade history -- all stay visible. A fixed :RETRY
        suffix would just collide with itself on a second same-day retry
        (hit for real: a retry that was itself rejected got replayed
        verbatim on the next attempt, even after the underlying bug was
        fixed).

        Only re-attempts a genuine outstanding signal: still fetches fresh
        data and re-checks generate_signal(), so this can't be used to
        force an entry that no longer qualifies. No-ops if the symbol is
        already an open position.
        """
        cfg = MARKETS[market]
        trader = self.traders[market]
        today = datetime.now().strftime("%Y-%m-%d")

        if symbol in trader.portfolio.positions:
            return {"action": "SKIPPED", "reason": "already an open position"}

        data = self.fetcher.fetch_many(
            [symbol],
            start_date=(datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"),
            india=cfg["india"],
        )
        df = data.get(symbol)
        if df is None or df.empty:
            return {"action": "SKIPPED", "reason": "no data"}

        signal = self.strategy.generate_signal(df)
        if signal is None:
            return {"action": "SKIPPED", "reason": "no signal"}

        qty = self._position_size(trader, signal.price, india=cfg["india"])
        if qty <= 0:
            return {"action": "SKIPPED", "reason": "position size is 0"}

        base = f"{symbol}:{self.strategy.name}:{today}:BUY"
        attempt = 1
        while f"{base}:RETRY{attempt}" in trader._order_results:
            attempt += 1
        client_order_id = f"{base}:RETRY{attempt}"
        if settings.auto_execute:
            order = trader.place_order(
                client_order_id, symbol, "BUY", qty, signal.price, self.strategy.name,
                stop_loss=signal.stop_loss, take_profit=signal.take_profit, reasoning=signal.reasoning,
            )
            notify_order(market, order)
            result = {"action": "EXECUTED", **order}
        else:
            result = {
                "action": "PROPOSED_BUY", "symbol": symbol, "price": signal.price,
                "quantity": qty, "stop_loss": signal.stop_loss, "take_profit": signal.take_profit,
                "reasoning": signal.reasoning,
            }

        self._save(market)
        return result

    def check_stops_only(self, market: str) -> List[dict]:
        """A lightweight, more-frequent companion to run_market_cycle() --
        checks every open position's stop-loss/take-profit against the
        CURRENT price via Strategy.check_stop_only(), and exits any that
        are breached. Never opens a new position and never runs the full
        (indicator-based) should_exit() -- that stays exclusively on
        run_market_cycle()'s once-daily schedule, unchanged. Mirrors
        CryptoTradingBot.check_stops_only() -- see that docstring and
        CHECKPOINT.md for why this split exists.

        Unlike crypto, this only matters during market hours -- a
        separate GitHub Actions cron limits when this actually runs (see
        stocks-intraday-stops.yml), this method itself has no time gate.

        Uses the SAME per-market PaperTrader state and the SAME
        AUTO_EXECUTE/propose-only gate as run_market_cycle() -- both act
        on the latest saved state via self.traders[market].load(...) in
        __init__, so the two jobs can't diverge on what's open even
        running on independent schedules.
        """
        cfg = MARKETS[market]
        trader = self.traders[market]
        today = datetime.now().strftime("%Y-%m-%d")
        actions: List[dict] = []

        if not trader.portfolio.positions:
            return actions

        symbols = list(trader.portfolio.positions.keys())
        data = self.fetcher.fetch_many(
            symbols,
            start_date=(datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
            india=cfg["india"],
        )
        prices = {s: float(df["close"].iloc[-1]) for s, df in data.items() if not df.empty}
        trader.update_prices(prices)
        if prices:
            self._save(market)  # persist the mark-to-market even if no stop fires

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
            if not self.strategy.check_stop_only(pos_obj, price):
                continue

            client_order_id = f"{symbol}:{self.strategy.name}:{today}:INTRADAY-SELL"
            if settings.auto_execute:
                order = trader.place_order(
                    client_order_id, symbol, "SELL", position["quantity"], price,
                    self.strategy.name, reasoning="check_stop_only triggered (intraday poll)",
                )
                notify_order(market, order)
                actions.append({"action": "EXECUTED", **order})
            else:
                actions.append({"action": "PROPOSED_SELL", "symbol": symbol, "price": price, "quantity": position["quantity"]})
                logger.info(f"[PROPOSE-ONLY] Would SELL (intraday stop) {position['quantity']} {symbol} @ {price:.2f}")

        if actions:
            self._save(market)
        return actions

    def check_all_stops_only(self) -> dict:
        return {market: self.check_stops_only(market) for market in MARKETS}

    def get_status(self, market: str) -> dict:
        """Current portfolio P&L and open positions, marked to
        current_price as it stands right now (call check_stops_only(market)
        first for a fresh mark -- this method itself never fetches)."""
        trader = self.traders[market]
        metrics = trader.get_performance_metrics()
        positions = []
        for symbol, p in trader.portfolio.positions.items():
            unrealized_pnl = (p["current_price"] - p["entry_price"]) * p["quantity"]
            unrealized_pnl_pct = (p["current_price"] / p["entry_price"] - 1) * 100 if p["entry_price"] else 0.0
            positions.append({
                "symbol": symbol,
                "quantity": p["quantity"],
                "entry_price": p["entry_price"],
                "current_price": p["current_price"],
                "invested": p["entry_price"] * p["quantity"],
                "current_value": p["current_price"] * p["quantity"],
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": unrealized_pnl_pct,
                "stop_loss": p.get("stop_loss"),
                "take_profit": p.get("take_profit"),
            })
        return {"market": market, **metrics, "positions": positions}

    def _save(self, market: str):
        self.traders[market].save(f"{market.lower()}_portfolio")

    def run_all(self) -> dict:
        return {market: self.run_market_cycle(market) for market in MARKETS}

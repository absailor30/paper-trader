"""
Commodities account (separate $100 paper account, 8 fixed ETFs): monthly rotation top 3, promoted live
on paper money 2026-10-15 after the 3-period backtest (CHECKPOINT.md "Commodities: portfolio-level
tests": +15.6 / +24.5 / +31.0 account return, the only rule that beat holding at the same exposure in
every period). The rule is the backtested one: decide on the last COMPLETED month-end bar, hold the top
3 funds (12% each, flat), no stop. Execution happens on the first run after that month closed, so a
missed day only delays a rebalance, never changes it. Honours AUTO_EXECUTE and the drawdown breaker
(entries only; exits are never blocked). State: `commodities_portfolio` (+ `commodities_meta`).
"""
from datetime import datetime, timedelta
from typing import List

import pandas as pd
from loguru import logger

from paper_trader.confidence import position_pct
from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.execution.paper_trader import PaperTrader
from paper_trader.history import history_view
from paper_trader.notify import notify_circuit_breaker, notify_fetch_failure, notify_order
from paper_trader.persistence.state_store import load_state, save_state
from paper_trader.strategy.commodity_rotation import last_month_end, rotation_targets

STRATEGY = "Rotation_Top3_126d_SMA200"
STATE_KEY, META_KEY = "commodities_portfolio", "commodities_meta"


class CommoditiesBot:
    def __init__(self, fetcher=None):
        self.fetcher = fetcher or DataFetcher()
        self.trader = PaperTrader(settings.commodities_capital, settings.commission_rate, settings.slippage_rate)
        found = self.trader.load(STATE_KEY)
        self.meta = load_state(META_KEY) or {"last_rebalance": None}
        logger.info(f"COMMODITIES: {'loaded existing state' if found else 'starting fresh'}")

    def _fetch(self) -> dict:
        start = (datetime.now() - timedelta(days=450)).strftime("%Y-%m-%d")
        data = self.fetcher.fetch_many(settings.commodities, start_date=start)
        notify_fetch_failure("COMMODITIES", len(settings.commodities), len(data))
        return data

    def check_risk_limits(self) -> bool:
        m = self.trader.get_performance_metrics()
        for reason, hit in (
            (f"daily loss limit reached ({m['daily_return_pct']:.2f}%)", m["daily_return_pct"] < -settings.max_daily_loss * 100),
            (f"max drawdown reached ({m['total_return_pct']:.2f}%)", m["total_return_pct"] < -settings.max_drawdown * 100),
        ):
            if hit:
                logger.warning(f"COMMODITIES: {reason}")
                notify_circuit_breaker("COMMODITIES", reason)
                return False
        return True

    def run_cycle(self) -> List[dict]:
        actions: List[dict] = []
        data = self._fetch()
        if not data:
            return actions
        self.trader.update_prices({s: float(df["close"].iloc[-1]) for s, df in data.items() if not df.empty})
        self._stamp(data)

        close = pd.DataFrame({s: df["close"] for s, df in data.items()}).sort_index().ffill(limit=3)
        decision_bar = last_month_end(close.index)
        if decision_bar is None:
            self._save()
            return actions
        label = f"{decision_bar:%Y-%m}"
        if self.meta.get("last_rebalance") == label:
            logger.info(f"COMMODITIES: {label} already rebalanced")
            self._save()
            return actions

        targets = rotation_targets(close.loc[:decision_bar].dropna(axis=1, how="all"))
        logger.info(f"COMMODITIES: rebalance for {label} (bar {decision_bar.date()}): targets {targets}")
        prices = {s: float(df["close"].iloc[-1]) for s, df in data.items() if not df.empty}
        held = self.trader.portfolio.positions

        for symbol, pos in list(held.items()):
            if symbol in targets or symbol not in prices:
                continue
            reason = f"rotation {label}: dropped out of the top {len(targets) or 3}"
            actions.append(self._order(f"COMM:{label}:{symbol}:SELL", symbol, "SELL", pos["quantity"], prices[symbol], reason))

        if self.check_risk_limits():
            for symbol in targets:
                if symbol in self.trader.portfolio.positions or symbol not in prices:
                    continue
                price = prices[symbol]
                allocated = min(self.trader.portfolio.total_value * position_pct(None, "COMMODITIES"),
                                self.trader.portfolio.capital)
                if price <= 0 or allocated < settings.min_position_value:
                    logger.info(f"COMMODITIES {symbol}: target skipped, only {allocated:.2f} available")
                    continue
                reason = f"rotation {label}: top {len(targets)} by 126d return, above SMA200"
                actions.append(self._order(f"COMM:{label}:{symbol}:BUY", symbol, "BUY", round(allocated / price, 4), price, reason))

        if settings.auto_execute:
            self.meta["last_rebalance"] = label
            save_state(META_KEY, self.meta)
        self._save()
        return actions

    def _order(self, order_id, symbol, side, quantity, price, reason) -> dict:
        if not settings.auto_execute:
            logger.info(f"[PROPOSE-ONLY] Would {side} {quantity} {symbol} @ {price:.2f} | {reason}")
            return {"action": f"PROPOSED_{side}", "symbol": symbol, "price": price, "quantity": quantity, "reasoning": reason}
        order = self.trader.place_order(order_id, symbol, side, quantity, price, STRATEGY, reasoning=reason)
        notify_order("COMMODITIES", order)
        return {"action": "EXECUTED", **order}

    def mark_to_market(self) -> None:
        """Refresh prices for the status page. No stops: the backtested rule has none."""
        held = list(self.trader.portfolio.positions)
        if not held:
            return
        start = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        data = self.fetcher.fetch_many(held, start_date=start)
        prices = {s: float(df["close"].iloc[-1]) for s, df in data.items() if not df.empty}
        if prices:
            self.trader.update_prices(prices)
            self._stamp(data)
            self._save()

    def _stamp(self, data: dict) -> None:
        """Record the newest price bar date actually used, so the dashboard can show how fresh prices are."""
        dates = [str(df.index[-1].date()) for df in data.values() if not df.empty]
        if dates:
            self.meta["prices_as_of"] = max(dates)
            logger.info(f"COMMODITIES: latest price bar {self.meta['prices_as_of']}")
            save_state(META_KEY, self.meta)

    def get_status(self) -> dict:
        metrics = self.trader.get_performance_metrics()
        positions = []
        for symbol, p in self.trader.portfolio.positions.items():
            pnl = (p["current_price"] - p["entry_price"]) * p["quantity"]
            positions.append({
                "symbol": symbol, "quantity": p["quantity"], "entry_price": p["entry_price"],
                "current_price": p["current_price"], "invested": p["entry_price"] * p["quantity"],
                "current_value": p["current_price"] * p["quantity"], "unrealized_pnl": pnl,
                "unrealized_pnl_pct": (p["current_price"] / p["entry_price"] - 1) * 100 if p["entry_price"] else 0.0,
            })
        return {"market": "COMMODITIES", **metrics, "positions": positions, **history_view(self.trader),
                "last_rebalance": self.meta.get("last_rebalance"), "prices_as_of": self.meta.get("prices_as_of")}

    def _save(self):
        self.trader.save(STATE_KEY)

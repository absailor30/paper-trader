"""
Propose-only shadow runs of candidate strategies, alongside the live ones
(India momentum, crypto Donchian 20/10). A shadow NEVER places an order and
NEVER touches a live portfolio state: it only keeps its own hypothetical
ledger (open positions + closed trades, net of the same commission/slippage
the backtests used) under its own state key, and sends a Telegram note on
each hypothetical entry/exit, so a candidate can be judged on real days
before it gets any real capital.
"""
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from paper_trader.config import settings
from paper_trader.data.binance_fetcher import BinanceFetcher
from paper_trader.data.fetcher import DataFetcher
from paper_trader.notify import notify_fetch_failure, notify_shadow
from paper_trader.persistence.state_store import load_state, save_state
from paper_trader.strategy.base import Position, Strategy
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy
from paper_trader.strategy.momentum_trend import MomentumTrend

STATE_KEY = "india_shadow_momentum"


def _net_return_pct(entry: float, exit_: float) -> float:
    s, c = settings.slippage_rate, settings.commission_rate
    return ((exit_ * (1 - s) * (1 - c)) / (entry * (1 + s) * (1 + c)) - 1) * 100


class ShadowRun:
    label = "shadow"

    def __init__(self, strategy: Strategy, fetcher, state_key: str):
        self.strategy, self.fetcher, self.state_key = strategy, fetcher, state_key
        self.state = load_state(state_key) or {"open": {}, "closed": [], "last_exit": {}}

    def symbols(self) -> list:
        raise NotImplementedError

    def fetch(self) -> dict:
        raise NotImplementedError

    def run(self) -> dict:
        symbols = self.symbols()
        data = self.fetch()
        notify_fetch_failure(self.label, len(symbols), len(data))

        opened, closed = [], []
        open_pos, last_exit = self.state["open"], self.state["last_exit"]

        for symbol, pos in list(open_pos.items()):
            df = data.get(symbol)
            if df is None or df.empty:
                continue
            bar_date = str(df.index[-1].date())
            price = float(df["close"].iloc[-1])
            position = Position(
                symbol=symbol, quantity=1.0, entry_price=pos["entry_price"], current_price=price,
                entry_time=pos["entry_date"], strategy_name=self.strategy.name,
                stop_loss=pos["stop_loss"], take_profit=pos["take_profit"],
            )
            if self.strategy.should_exit(position, df):
                trade = {
                    "symbol": symbol, "entry_date": pos["entry_date"], "entry_price": pos["entry_price"],
                    "exit_date": bar_date, "exit_price": price,
                    "net_return_pct": _net_return_pct(pos["entry_price"], price),
                }
                self.state["closed"].append(trade)
                del open_pos[symbol]
                last_exit[symbol] = bar_date
                closed.append(trade)
                notify_shadow(self.strategy.name, "SELL", symbol, price, f"net {trade['net_return_pct']:+.2f}%")

        for symbol, df in data.items():
            if symbol in open_pos or df.empty:
                continue
            bar_date = str(df.index[-1].date())
            if last_exit.get(symbol) == bar_date:
                continue
            signal = self.strategy.generate_signal(df)
            if signal is None:
                continue
            open_pos[symbol] = {
                "entry_date": bar_date, "entry_price": signal.price,
                "stop_loss": signal.stop_loss, "take_profit": signal.take_profit,
                "reasoning": signal.reasoning,
            }
            opened.append({"symbol": symbol, "price": signal.price, "reasoning": signal.reasoning})
            notify_shadow(self.strategy.name, "BUY", symbol, signal.price, signal.reasoning)

        save_state(self.state_key, self.state)
        return self._summary(data, opened, closed)

    def _summary(self, data: dict, opened: list, closed: list) -> dict:
        trades = self.state["closed"]
        wins = [t for t in trades if t["net_return_pct"] > 0]
        open_view = {}
        for symbol, pos in self.state["open"].items():
            df = data.get(symbol)
            last = float(df["close"].iloc[-1]) if df is not None and not df.empty else None
            open_view[symbol] = {**pos, "last_price": last, "unrealized_pct": (
                _net_return_pct(pos["entry_price"], last) if last else None)}
        logger.info(f"{self.label} ({self.strategy.name}): opened={len(opened)} closed={len(closed)} open={len(open_view)}")
        return {
            "strategy": self.strategy.name, "executed": False,
            "opened_today": opened, "closed_today": closed, "open_positions": open_view,
            "closed_trades": len(trades),
            "win_rate_pct": (len(wins) / len(trades) * 100) if trades else None,
            "avg_net_return_pct": (sum(t["net_return_pct"] for t in trades) / len(trades)) if trades else None,
        }


def _start_date() -> str:
    return (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")


class IndiaShadowRun(ShadowRun):
    label = "INDIA shadow"

    def __init__(self, strategy: Optional[Strategy] = None, fetcher: Optional[DataFetcher] = None):
        super().__init__(strategy or MomentumTrend(126, 0.10, 50), fetcher or DataFetcher(), STATE_KEY)

    def symbols(self) -> list:
        return settings.india_stocks

    def fetch(self) -> dict:
        return self.fetcher.fetch_many(self.symbols(), start_date=_start_date(), india=True)


def _completed_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the in-progress daily candle: backtests only ever see completed bars."""
    today = pd.Timestamp.now(tz="UTC").normalize()
    if df.index.tz is None:
        today = today.tz_localize(None)
    return df[df.index.normalize() < today]


class CryptoShadowRun(ShadowRun):
    label = "CRYPTO shadow"

    def __init__(self, strategy: Optional[Strategy] = None, fetcher: Optional[BinanceFetcher] = None):
        strategy = strategy or DonchianBreakoutStrategy(20, 10, None, name="Donchian_20_10_shadow")
        super().__init__(strategy, fetcher or BinanceFetcher(market="spot"), f"crypto_shadow_{strategy.name}")

    def symbols(self) -> list:
        return settings.crypto_pairs

    def fetch(self) -> dict:
        data = self.fetcher.fetch_many(self.symbols(), start_date=_start_date())
        completed = {s: _completed_bars(df) for s, df in data.items()}
        return {s: df for s, df in completed.items() if not df.empty}

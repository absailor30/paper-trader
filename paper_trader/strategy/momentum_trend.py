"""
Time-series momentum: hold while the lookback return is strong and price is
above a short SMA. Candidate for India from CHECKPOINT.md "India strategy
search (2026-10-02)"; run propose-only via paper_trader/shadow.py, not wired
to live execution.
"""
from typing import Optional

import pandas as pd

from paper_trader.config import settings
from paper_trader.strategy.base import Position, Signal, SignalType, Strategy
from paper_trader.strategy.indicators import atr, sma


class MomentumTrend(Strategy):
    def __init__(self, lookback: int, min_ret: float, sma_n: int):
        self.lookback, self.min_ret, self.sma_n = lookback, min_ret, sma_n
        self.name = f"Momentum_{lookback}d_ret{int(min_ret * 100)}_sma{sma_n}"

    def generate_signal(self, data: pd.DataFrame) -> Optional[Signal]:
        if len(data) < max(self.lookback, self.sma_n, settings.atr_period) + 2:
            return None
        close = data["close"]
        price = close.iloc[-1]
        ret = price / close.iloc[-1 - self.lookback] - 1
        trend = sma(close, self.sma_n).iloc[-1]
        atr_now = atr(data["high"], data["low"], close, settings.atr_period).iloc[-1]
        if pd.isna(trend) or pd.isna(atr_now) or ret < self.min_ret or price <= trend:
            return None
        stop = price - settings.atr_stop_multiple * atr_now
        if stop <= 0 or stop >= price:
            return None
        symbol = data["symbol"].iloc[-1] if "symbol" in data.columns else "UNKNOWN"
        return Signal(
            symbol=symbol, signal_type=SignalType.BUY, price=float(price), timestamp=data.index[-1],
            strategy_name=self.name, stop_loss=float(stop),
            take_profit=float(price + settings.min_risk_reward * (price - stop)),
            reasoning=f"{self.lookback}d return {ret:.1%}, above SMA{self.sma_n}",
        )

    def should_exit(self, position: Position, data: pd.DataFrame) -> bool:
        price = position.current_price
        if position.stop_loss and price <= position.stop_loss:
            return True
        if position.take_profit and price >= position.take_profit:
            return True
        trend = sma(data["close"], self.sma_n).iloc[-1]
        return bool(not pd.isna(trend) and data["close"].iloc[-1] < trend)

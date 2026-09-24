"""Strategy interface and shared types."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

import pandas as pd


class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Signal:
    symbol: str
    signal_type: SignalType
    price: float
    timestamp: datetime
    strategy_name: str
    stop_loss: float
    take_profit: float
    reasoning: str = ""


@dataclass
class Position:
    symbol: str
    quantity: float
    entry_price: float
    current_price: float
    entry_time: datetime
    strategy_name: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class Strategy(ABC):
    name: str

    @abstractmethod
    def generate_signal(self, data: pd.DataFrame) -> Optional[Signal]:
        """Look at the latest bar of `data` and decide whether to enter.
        `data` must have lowercase OHLCV columns and a DatetimeIndex, one
        row per bar, most recent last."""
        raise NotImplementedError

    @abstractmethod
    def should_exit(self, position: Position, data: pd.DataFrame) -> bool:
        """Whether an open position should be closed given the latest data."""
        raise NotImplementedError

    def check_stop_only(self, position: Position, current_price: float) -> bool:
        """Whether `current_price` alone breaches this position's stop-loss
        or take-profit, with no reference to any indicator series.

        This exists so a stop can be checked against intraday prices between
        the once-a-day full `should_exit()` evaluation (which needs a daily
        bar series to recompute channel/SMA/RSI exits) without recomputing
        those indicators on every intraday poll -- see
        paper_trader/backtest/intraday_stop_engine.py and CHECKPOINT.md's
        "Intraday stop monitoring" entry for why the split exists and what
        it does and doesn't change about the validated daily strategy.

        Every strategy shares this same stop_loss/take_profit semantics
        (see each should_exit()'s own stop/target check), so the default
        here covers all three without per-strategy overrides.
        """
        if position.stop_loss and current_price <= position.stop_loss:
            return True
        if position.take_profit and current_price >= position.take_profit:
            return True
        return False

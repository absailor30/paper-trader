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

"""
Base strategy class for all trading strategies
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, List
import pandas as pd
import numpy as np

class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

@dataclass
class Signal:
    """Trading signal"""
    symbol: str
    signal_type: SignalType
    price: float
    timestamp: datetime
    strategy_name: str
    confidence: float = 0.5
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'signal_type': self.signal_type.value,
            'price': self.price,
            'timestamp': self.timestamp.isoformat(),
            'strategy_name': self.strategy_name,
            'confidence': self.confidence,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'reasoning': self.reasoning
        }

@dataclass
class Position:
    """Open position"""
    symbol: str
    quantity: float
    entry_price: float
    current_price: float
    entry_time: datetime
    strategy_name: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    @property
    def pnl(self) -> float:
        return (self.current_price - self.entry_price) * self.quantity

    @property
    def pnl_pct(self) -> float:
        return (self.current_price - self.entry_price) / self.entry_price

class BaseStrategy(ABC):
    """Abstract base class for trading strategies"""

    def __init__(self, name: str):
        self.name = name
        self.positions = {}
        self.signals_history = []

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> List[Signal]:
        """
        Generate trading signals from data

        Args:
            data: OHLCV DataFrame

        Returns:
            List of Signal objects
        """
        pass

    @abstractmethod
    def should_exit(self, position: Position, current_data: pd.DataFrame) -> bool:
        """
        Determine if position should be closed

        Args:
            position: Current position
            current_data: Current market data

        Returns:
            True if should exit
        """
        pass

    def calculate_position_size(
        self,
        capital: float,
        price: float,
        risk_per_trade: float = 0.02
    ) -> float:
        """
        Calculate position size based on risk management

        Args:
            capital: Total capital
            price: Current price
            risk_per_trade: Risk percentage per trade

        Returns:
            Number of shares/units
        """
        risk_amount = capital * risk_per_trade
        position_value = capital * 0.12  # Max 12% per position
        shares = position_value / price
        return int(shares)

    def update_position(self, symbol: str, current_price: float):
        """Update position with current price"""
        if symbol in self.positions:
            self.positions[symbol].current_price = current_price

    def record_signal(self, signal: Signal):
        """Record signal for analysis"""
        self.signals_history.append(signal)

    def get_performance_metrics(self) -> dict:
        """Calculate strategy performance metrics"""
        if not self.signals_history:
            return {}

        signals = [s.to_dict() for s in self.signals_history]
        df = pd.DataFrame(signals)

        return {
            'total_signals': len(signals),
            'buy_signals': len(df[df['signal_type'] == 'BUY']),
            'sell_signals': len(df[df['signal_type'] == 'SELL']),
            'avg_confidence': df['confidence'].mean()
        }

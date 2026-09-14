"""
CAN SLIM Strategy (William O'Neil)

CAN SLIM criteria:
C - Current quarterly earnings (should be up 25%+)
A - Annual earnings growth (should be up 25%+ over 3 years)
N - New product, new management, new highs
S - Supply and demand (shares outstanding + volume)
L - Leader or laggard (relative strength)
I - Institutional sponsorship
M - Market direction

For paper trading, we focus on technical components with ML enhancement.
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Optional
from .base_strategy import BaseStrategy, Signal, SignalType, Position
from .indicators import sma, ema, rsi, volume_profile

class CANSLIMStrategy(BaseStrategy):
    """
    CAN SLIM strategy implementation with ML enhancement
    Focus on breakout patterns and momentum
    """

    def __init__(self):
        super().__init__("CAN_SLIM")
        self.min_volume_increase = 1.5  # 50% volume increase on breakout
        self.min_price_increase = 0.03  # 3% minimum price move
        self.lookback_period = 50

    def detect_cup_with_handle(self, data: pd.DataFrame) -> bool:
        """
        Detect cup-with-handle pattern

        Simplified detection:
        1. Price forms a rounded bottom (cup)
        2. Brief consolidation (handle)
        3. Breakout above pivot
        """
        if len(data) < 50:
            return False

        recent = data.tail(50)

        # Find pivot point (highest point before pullback)
        pivot_idx = recent['high'][:-10].idxmax()
        pivot_price = recent.loc[pivot_idx, 'high']

        # Cup depth should be 15-33% from pivot
        cup_low = recent['low'].min()
        cup_depth = (pivot_price - cup_low) / pivot_price

        if not (0.15 <= cup_depth <= 0.33):
            return False

        # Handle should be shallow (5-10% from pivot)
        handle_low = recent['low'].tail(10).min()
        handle_depth = (pivot_price - handle_low) / pivot_price

        if not (0.05 <= handle_depth <= 0.15):
            return False

        # Check for breakout
        current_price = recent['close'].iloc[-1]
        breakout = current_price > pivot_price

        return breakout

    def check_volume_surge(self, data: pd.DataFrame, idx: int = -1) -> bool:
        """Check if volume is above average"""
        if len(data) < 50:
            return False

        avg_volume = data['volume'].iloc[:-5].mean()
        current_volume = data['volume'].iloc[idx]

        return current_volume > avg_volume * self.min_volume_increase

    def calculate_relative_strength(self, data: pd.DataFrame, benchmark_data: pd.DataFrame) -> float:
        """
        Calculate relative strength vs benchmark
        RS > 1 means outperforming
        """
        if len(data) < 50 or len(benchmark_data) < 50:
            return 1.0

        # Price change over period
        price_change = data['close'].iloc[-1] / data['close'].iloc[-50]
        benchmark_change = benchmark_data['close'].iloc[-1] / benchmark_data['close'].iloc[-50]

        return price_change / benchmark_change

    def generate_signals(self, data: pd.DataFrame, benchmark_data: Optional[pd.DataFrame] = None) -> List[Signal]:
        """Generate CAN SLIM signals"""
        signals = []

        if len(data) < self.lookback_period:
            return signals

        symbol = data['symbol'].iloc[0] if 'symbol' in data.columns else 'UNKNOWN'

        # Calculate indicators
        data = data.copy()
        data['sma_50'] = sma(data['close'], 50)
        data['sma_200'] = sma(data['close'], 200)
        data['rsi'] = rsi(data['close'], 14)

        current_price = data['close'].iloc[-1]
        current_date = data.index[-1] if isinstance(data.index[-1], datetime) else datetime.now()

        # CAN SLIM checks
        checks_passed = 0

        # Check 1: Price above 50-day SMA
        if current_price > data['sma_50'].iloc[-1]:
            checks_passed += 1

        # Check 2: Volume surge
        volume_surge = self.check_volume_surge(data)
        if volume_surge:
            checks_passed += 1

        # Check 3: RSI not overbought
        if 30 < data['rsi'].iloc[-1] < 70:
            checks_passed += 1

        # Check 4: Cup-with-handle breakout
        cup_handle = self.detect_cup_with_handle(data)
        if cup_handle:
            checks_passed += 1

        # Check 5: Relative strength (if benchmark provided)
        rs_score = 1.0
        if benchmark_data is not None:
            rs_score = self.calculate_relative_strength(data, benchmark_data)
            if rs_score > 1.0:
                checks_passed += 1

        # Generate signal if enough checks passed
        if checks_passed >= 3:
            confidence = checks_passed / 5.0

            # Calculate stop loss (7-8% rule)
            stop_loss = current_price * 0.93

            # Take profit at 20-25%
            take_profit = current_price * 1.20

            reasoning = f"CAN SLIM signal: {checks_passed}/5 checks passed. "
            reasoning += f"Volume surge: {volume_surge}, Cup-handle: {cup_handle}, RS: {rs_score:.2f}"

            signal = Signal(
                symbol=symbol,
                signal_type=SignalType.BUY,
                price=current_price,
                timestamp=current_date,
                strategy_name=self.name,
                confidence=confidence,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reasoning=reasoning
            )
            signals.append(signal)
            self.record_signal(signal)

        return signals

    def should_exit(self, position: Position, current_data: pd.DataFrame) -> bool:
        """Exit logic for CAN SLIM"""
        current_price = current_data['close'].iloc[-1]

        # Stop loss hit (7-8% rule)
        if position.stop_loss and current_price <= position.stop_loss:
            return True

        # Take profit hit (20-25%)
        if position.take_profit and current_price >= position.take_profit:
            return True

        # Price below 50-day SMA
        sma_50 = sma(current_data['close'], 50).iloc[-1]
        if current_price < sma_50:
            return True

        return False

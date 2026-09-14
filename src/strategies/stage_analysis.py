"""
Stage Analysis Strategy (Stan Weinstein)

Four stages:
- Stage 1: Basing/Consolidation
- Stage 2: Advancing/Uptrend (BUY)
- Stage 3: Topping/Distribution
- Stage 4: Declining/Downtrend

Entry: Breakout from Stage 1 to Stage 2 with volume
Exit: Move to Stage 3 or breakdown to Stage 4
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List
from .base_strategy import BaseStrategy, Signal, SignalType, Position
from .indicators import sma, atr

class StageAnalysisStrategy(BaseStrategy):
    """
    Stan Weinstein Stage Analysis implementation
    Uses 30-week MA (150-day MA) for stage classification
    """

    def __init__(self):
        super().__init__("Stage_Analysis")
        self.ma_period = 150  # 30-week MA
        self.breakout_volume_mult = 1.5

    def classify_stage(self, data: pd.DataFrame) -> int:
        """
        Classify current market stage

        Returns:
            1: Basing
            2: Advancing (bullish)
            3: Topping
            4: Declining (bearish)
        """
        if len(data) < self.ma_period:
            return 1

        data = data.copy()
        data['ma'] = sma(data['close'], self.ma_period)

        current_price = data['close'].iloc[-1]
        current_ma = data['ma'].iloc[-1]

        # MA slope (5-day change)
        ma_slope = (data['ma'].iloc[-1] - data['ma'].iloc[-5]) / data['ma'].iloc[-5] * 100

        # Price vs MA
        price_vs_ma = (current_price - current_ma) / current_ma * 100

        # Stage classification
        if price_vs_ma > 5 and ma_slope > 0.5:
            return 2  # Advancing
        elif price_vs_ma < -5 and ma_slope < -0.5:
            return 4  # Declining
        elif abs(price_vs_ma) < 5 and abs(ma_slope) < 0.5:
            if price_vs_ma > 0:
                return 3  # Topping
            else:
                return 1  # Basing
        elif ma_slope > 0 and price_vs_ma > 0:
            return 2  # Advancing
        elif ma_slope < 0 and price_vs_ma < 0:
            return 4  # Declining
        else:
            return 1  # Default to basing

    def detect_breakout(self, data: pd.DataFrame, lookback: int = 50) -> dict:
        """
        Detect breakout from Stage 1 to Stage 2

        Returns breakout info or empty dict
        """
        if len(data) < lookback:
            return {}

        recent = data.tail(lookback)

        # Find resistance level
        resistance = recent['high'].iloc[:-1].max()

        # Current price
        current_price = data['close'].iloc[-1]

        # Volume analysis
        avg_volume = recent['volume'].iloc[:-5].mean()
        current_volume = data['volume'].iloc[-1]
        volume_expansion = current_volume > avg_volume * self.breakout_volume_mult

        # Breakout check
        breakout = current_price > resistance

        return {
            'resistance': resistance,
            'current_price': current_price,
            'breakout': breakout,
            'volume_expansion': volume_expansion,
            'breakout_pct': (current_price - resistance) / resistance * 100 if breakout else 0
        }

    def calculate_relative_strength(self, data: pd.DataFrame, benchmark: pd.DataFrame) -> float:
        """
        Calculate relative strength vs benchmark

        RS line should be rising for valid breakouts
        """
        if len(data) < 50 or len(benchmark) < 50:
            return 1.0

        # Rate of change
        price_roc = data['close'].pct_change(50).iloc[-1]
        benchmark_roc = benchmark['close'].pct_change(50).iloc[-1]

        # RS ratio
        if benchmark_roc == 0:
            return 1.0

        return (1 + price_roc) / (1 + benchmark_roc)

    def generate_signals(self, data: pd.DataFrame, benchmark: pd.DataFrame = None) -> List[Signal]:
        """Generate Stage Analysis signals"""
        signals = []

        if len(data) < self.ma_period:
            return signals

        symbol = data['symbol'].iloc[0] if 'symbol' in data.columns else 'UNKNOWN'

        current_price = data['close'].iloc[-1]
        current_date = data.index[-1] if isinstance(data.index[-1], datetime) else datetime.now()

        # Get current stage
        stage = self.classify_stage(data)

        # Only buy in Stage 2
        if stage != 2:
            return signals

        # Check for breakout
        breakout_info = self.detect_breakout(data)

        if not breakout_info.get('breakout'):
            return signals

        # Volume confirmation
        if not breakout_info.get('volume_expansion'):
            return signals

        # Relative strength check
        rs_score = 1.0
        if benchmark is not None:
            rs_score = self.calculate_relative_strength(data, benchmark)
            if rs_score < 1.0:
                return signals  # Not outperforming

        # Calculate confidence
        confidence = 0.6
        if breakout_info['volume_expansion']:
            confidence += 0.2
        if rs_score > 1.1:
            confidence += 0.1

        # Stop loss below breakout level
        stop_loss = breakout_info['resistance'] * 0.95

        # Take profit at 20%
        take_profit = current_price * 1.20

        reasoning = f"Stage Analysis: Stage {stage}, Breakout={breakout_info['breakout']:.2f}, "
        reasoning += f"Vol expansion={breakout_info['volume_expansion']}, RS={rs_score:.2f}"

        signal = Signal(
            symbol=symbol,
            signal_type=SignalType.BUY,
            price=current_price,
            timestamp=current_date,
            strategy_name=self.name,
            confidence=min(confidence, 1.0),
            stop_loss=stop_loss,
            take_profit=take_profit,
            reasoning=reasoning
        )
        signals.append(signal)
        self.record_signal(signal)

        return signals

    def should_exit(self, position: Position, current_data: pd.DataFrame) -> bool:
        """Exit when stage changes to 3 or 4"""
        current_stage = self.classify_stage(current_data)

        # Exit on stage deterioration
        if current_stage in [3, 4]:
            return True

        # Stop loss
        current_price = current_data['close'].iloc[-1]
        if position.stop_loss and current_price <= position.stop_loss:
            return True

        # Take profit
        if position.take_profit and current_price >= position.take_profit:
            return True

        return False

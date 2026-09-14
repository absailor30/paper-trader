"""
SEPA + VCP Strategy (Mark Minervini)

SEPA = Specific Entry Point Analysis
VCP = Volatility Contraction Pattern

Key rules:
- Only buy in Stage 2 uptrend
- Wait for VCP breakout with volume expansion
- Stop loss at 7-8% below entry
- Move stop to breakeven after 20% gain
- Tighten stops to 5-6% in weak markets
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Optional
from .base_strategy import BaseStrategy, Signal, SignalType, Position
from .indicators import sma, ema, atr, detect_vcp, stage_analysis

class SEPAStrategy(BaseStrategy):
    """
    SEPA + VCP strategy implementation
    """

    def __init__(self):
        super().__init__("SEPA_VCP")
        self.stop_loss_pct = 0.08  # 8% default stop
        self.breakeven_trigger = 0.20  # Move to breakeven after 20% gain
        self.weak_market_stop = 0.06  # 6% stop in weak markets

    def calculate_volatility_contraction(self, data: pd.DataFrame) -> dict:
        """
        Analyze volatility contraction

        Returns dict with contraction info
        """
        data = data.copy()

        # Calculate range as % of price
        data['range_pct'] = (data['high'] - data['low']) / data['close'] * 100

        # Find contractions
        data['range_sma'] = sma(data['range_pct'], 10)

        # Detect decreasing volatility
        recent_ranges = data['range_pct'].tail(30).values
        decreasing = all(recent_ranges[i] > recent_ranges[i+1]
                        for i in range(len(recent_ranges)-1)
                        if i % 5 == 0)  # Check every 5 bars

        # Volume analysis
        avg_volume = data['volume'].tail(30).mean()
        current_volume = data['volume'].iloc[-1]
        volume_expansion = current_volume > avg_volume * 1.5

        return {
            'range_pct': data['range_pct'].iloc[-1],
            'avg_range': data['range_sma'].iloc[-1],
            'decreasing_volatility': decreasing,
            'volume_expansion': volume_expansion,
            'current_volume': current_volume,
            'avg_volume': avg_volume
        }

    def check_stage_2(self, data: pd.DataFrame) -> bool:
        """
        Check if stock is in Stage 2 (uptrend)

        Stage 2 criteria:
        - Price above 30-week MA (210-day MA)
        - MA sloping upward
        - Higher highs and higher lows
        """
        if len(data) < 210:
            return False

        data = data.copy()

        # 30-week MA ≈ 150-day MA (weekly)
        data['ma_150'] = sma(data['close'], 150)

        # Price above MA
        above_ma = data['close'].iloc[-1] > data['ma_150'].iloc[-1]

        # MA slope positive
        ma_slope = (data['ma_150'].iloc[-1] - data['ma_150'].iloc[-20]) / data['ma_150'].iloc[-20]
        ma_rising = ma_slope > 0.02  # 2% rise over 20 days

        # Higher highs
        recent_highs = data['high'].tail(50)
        making_higher_highs = recent_highs.iloc[-1] > recent_highs.iloc[:-1].max() * 0.98

        return above_ma and ma_rising and making_higher_highs

    def find_vcp_entry_point(self, data: pd.DataFrame) -> Optional[float]:
        """
        Find optimal VCP entry point

        Returns pivot price or None
        """
        if len(data) < 60:
            return None

        recent = data.tail(60)

        # Find most recent pivot high
        pivot_idx = recent['high'].iloc[:-5].idxmax()
        pivot_price = recent.loc[pivot_idx, 'high']

        # Current price should be near pivot (within 5%)
        current_price = recent['close'].iloc[-1]
        distance_to_pivot = (pivot_price - current_price) / current_price

        if distance_to_pivot > 0.05:
            return None  # Too far from pivot

        return pivot_price

    def generate_signals(self, data: pd.DataFrame) -> List[Signal]:
        """Generate SEPA/VCP signals"""
        signals = []

        if len(data) < 150:
            return signals

        symbol = data['symbol'].iloc[0] if 'symbol' in data.columns else 'UNKNOWN'

        current_price = data['close'].iloc[-1]
        current_date = data.index[-1] if isinstance(data.index[-1], datetime) else datetime.now()

        # Stage 2 check
        in_stage_2 = self.check_stage_2(data)

        if not in_stage_2:
            return signals

        # VCP analysis
        vcp_data = self.calculate_volatility_contraction(data)

        # Entry criteria
        criteria_met = 0

        # 1. Volatility contraction
        if vcp_data['decreasing_volatility']:
            criteria_met += 1

        # 2. Volume expansion on breakout
        if vcp_data['volume_expansion']:
            criteria_met += 1

        # 3. Near pivot point
        pivot = self.find_vcp_entry_point(data)
        if pivot:
            criteria_met += 1

        # Generate signal if all criteria met
        if criteria_met >= 2 and pivot:
            confidence = criteria_met / 3.0

            # Stop loss (7-8% rule)
            stop_loss = current_price * (1 - self.stop_loss_pct)

            # Take profit (20-25%)
            take_profit = current_price * 1.25

            reasoning = f"SEPA/VCP: Stage 2={in_stage_2}, VCP contraction={vcp_data['decreasing_volatility']}, "
            reasoning += f"Vol expansion={vcp_data['volume_expansion']}, Pivot={pivot:.2f}"

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
        """Exit logic for SEPA"""
        current_price = current_data['close'].iloc[-1]

        # Hard stop loss
        if position.stop_loss and current_price <= position.stop_loss:
            return True

        # Take profit
        if position.take_profit and current_price >= position.take_profit:
            return True

        # Exit if breaks below Stage 2
        in_stage_2 = self.check_stage_2(current_data)
        if not in_stage_2:
            return True

        # Move stop to breakeven after 20% gain
        if position.pnl_pct >= self.breakeven_trigger:
            position.stop_loss = position.entry_price  # Breakeven

        return False

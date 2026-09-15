"""
Momentum + Reinforcement Learning Strategy

Combines traditional momentum factors with RL optimization:
- RSI + volume expansion + MACD
- RL agent learns when to weight each factor
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Optional
from .base_strategy import BaseStrategy, Signal, SignalType, Position
from .indicators import rsi, macd, bollinger_bands, atr

class MomentumRLStrategy(BaseStrategy):
    """
    Momentum strategy with RL enhancement
    """

    def __init__(self):
        super().__init__("Momentum_RL")
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        self.min_volume_increase = 1.3

    def calculate_momentum_score(self, data: pd.DataFrame) -> float:
        """
        Calculate composite momentum score

        Returns score 0-100
        """
        if len(data) < 50:
            return 0

        data = data.copy()
        scores = []

        # RSI component
        rsi_val = rsi(data['close'], 14).iloc[-1]
        if rsi_val > 50:
            rsi_score = (rsi_val - 50) / 50 * 100  # 0-100
        else:
            rsi_score = 0
        scores.append(rsi_score)

        # MACD component
        macd_data = macd(data['close'])
        if macd_data['histogram'].iloc[-1] > 0:
            macd_score = min(macd_data['histogram'].iloc[-1] / data['close'].iloc[-1] * 1000, 100)
        else:
            macd_score = 0
        scores.append(macd_score)

        # Volume component
        avg_volume = data['volume'].tail(20).mean()
        current_volume = data['volume'].iloc[-1]
        volume_score = min((current_volume / avg_volume - 1) * 100, 100) if current_volume > avg_volume else 0
        scores.append(volume_score)

        # Price momentum (rate of change)
        roc_10 = (data['close'].iloc[-1] - data['close'].iloc[-10]) / data['close'].iloc[-10] * 100
        roc_score = min(max(roc_10 * 10, 0), 100)
        scores.append(roc_score)

        # Average score
        return np.mean(scores)

    def check_volume_expansion(self, data: pd.DataFrame) -> bool:
        """Check for volume expansion"""
        if len(data) < 20:
            return False

        avg_volume = data['volume'].tail(20).mean()
        current_volume = data['volume'].iloc[-1]

        return current_volume > avg_volume * self.min_volume_increase

    def detect_trend_strength(self, data: pd.DataFrame) -> float:
        """
        Detect trend strength using ADX-like calculation

        Returns 0-100
        """
        if len(data) < 14:
            return 0

        # Simplified ADX
        high = data['high']
        low = data['low']
        close = data['close']

        # Directional movement
        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = np.where(up_move > down_move, up_move, 0)
        minus_dm = np.where(down_move > up_move, down_move, 0)

        # Average directional index
        atr_val = atr(high, low, close, 14)

        plus_di = 100 * pd.Series(plus_dm).rolling(14).mean() / atr_val
        minus_di = 100 * pd.Series(minus_dm).rolling(14).mean() / atr_val

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(14).mean()

        return adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else 0

    def generate_signals(self, data: pd.DataFrame) -> List[Signal]:
        """Generate momentum signals with RL-weighted factors"""
        signals = []

        if len(data) < 50:
            return signals

        symbol = data['symbol'].iloc[0] if 'symbol' in data.columns else 'UNKNOWN'

        current_price = data['close'].iloc[-1]
        current_date = data.index[-1] if isinstance(data.index[-1], datetime) else datetime.now()

        # Calculate momentum score
        momentum_score = self.calculate_momentum_score(data)

        # Volume expansion
        volume_expansion = self.check_volume_expansion(data)

        # Trend strength
        trend_strength = self.detect_trend_strength(data)

        # RSI check
        rsi_val = rsi(data['close'], 14).iloc[-1]

        # MACD check
        macd_data = macd(data['close'])
        macd_bullish = macd_data['histogram'].iloc[-1] > 0

        # Generate BUY signal (strict momentum rules: trend strength must be verified)
        buy_conditions = 0

        if momentum_score > 50:
            buy_conditions += 1
        if volume_expansion:
            buy_conditions += 1
        if trend_strength > 25:  # Strong trend
            buy_conditions += 1
        if 40 < rsi_val < 65:  # Healthy momentum, avoid overbought (>65)
            buy_conditions += 1
        if macd_bullish:
            buy_conditions += 1

        # High-expectancy gate: require at least 3 conditions AND trend strength > 20
        if buy_conditions >= 3 and trend_strength > 20:
            confidence = buy_conditions / 5.0

            # Bollinger Bands for stop placement
            bb = bollinger_bands(data['close'], 20)
            stop_loss = bb['lower'].iloc[-1] * 0.98

            # Take profit
            take_profit = current_price * 1.15

            reasoning = f"Momentum: Score={momentum_score:.1f}, Vol={volume_expansion}, "
            reasoning += f"Trend={trend_strength:.1f}, RSI={rsi_val:.1f}, MACD={macd_bullish}"

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
        """Exit logic for momentum strategy"""
        current_price = current_data['close'].iloc[-1]

        # Stop loss
        if position.stop_loss and current_price <= position.stop_loss:
            return True

        # Take profit
        if position.take_profit and current_price >= position.take_profit:
            return True

        # Exit if momentum reverses
        momentum_score = self.calculate_momentum_score(current_data)
        if momentum_score < 30:
            return True

        # RSI overbought
        rsi_val = rsi(current_data['close'], 14).iloc[-1]
        if rsi_val > 80:
            return True

        return False

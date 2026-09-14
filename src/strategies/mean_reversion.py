"""
Mean Reversion Strategy with Dynamic Z-Score

Based on Bollinger Band squeezes and Z-score extremes.
Adaptive thresholds based on realized volatility regime.
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List
from .base_strategy import BaseStrategy, Signal, SignalType, Position
from .indicators import bollinger_bands, rsi, atr

class MeanReversionStrategy(BaseStrategy):
    """
    Mean reversion with dynamic thresholds
    """

    def __init__(self):
        super().__init__("Mean_Reversion")
        self.lookback_period = 20
        self.z_score_threshold = 2.5  # Default, adjusted dynamically
        self.min_holding_period = 3  # Days

    def calculate_z_score(self, data: pd.Series, period: int = 20) -> float:
        """Calculate Z-score of current price"""
        if len(data) < period:
            return 0

        mean = data.tail(period).mean()
        std = data.tail(period).std()

        if std == 0:
            return 0

        return (data.iloc[-1] - mean) / std

    def detect_volatility_regime(self, data: pd.DataFrame) -> str:
        """
        Detect current volatility regime

        Returns: 'low', 'normal', 'high'
        """
        if len(data) < 100:
            return 'normal'

        # Historical volatility
        returns = data['close'].pct_change()
        hist_vol = returns.tail(100).std() * np.sqrt(252)  # Annualized

        # Recent volatility
        recent_vol = returns.tail(20).std() * np.sqrt(252)

        # Compare
        if recent_vol < hist_vol * 0.7:
            return 'low'
        elif recent_vol > hist_vol * 1.3:
            return 'high'
        else:
            return 'normal'

    def get_dynamic_threshold(self, regime: str) -> float:
        """Adjust Z-score threshold based on regime"""
        if regime == 'low':
            return 2.0  # Lower threshold in low vol
        elif regime == 'high':
            return 3.0  # Higher threshold in high vol
        else:
            return 2.5

    def detect_bb_squeeze(self, data: pd.DataFrame) -> dict:
        """
        Detect Bollinger Band squeeze

        Squeeze = low volatility before expansion
        """
        bb = bollinger_bands(data['close'], self.lookback_period)

        # Bandwidth (historical percentile)
        bandwidth = bb['bandwidth']
        bandwidth_pct = (bandwidth < bandwidth.rolling(100).quantile(0.2)).iloc[-1]

        # Squeeze detected
        squeeze = bandwidth_pct

        return {
            'squeeze': squeeze,
            'bandwidth': bandwidth.iloc[-1],
            'bandwidth_percentile': bandwidth.rolling(100).rank(pct=True).iloc[-1]
        }

    def generate_signals(self, data: pd.DataFrame) -> List[Signal]:
        """Generate mean reversion signals"""
        signals = []

        if len(data) < 100:
            return signals

        symbol = data['symbol'].iloc[0] if 'symbol' in data.columns else 'UNKNOWN'

        current_price = data['close'].iloc[-1]
        current_date = data.index[-1] if isinstance(data.index[-1], datetime) else datetime.now()

        # Get volatility regime
        regime = self.detect_volatility_regime(data)
        threshold = self.get_dynamic_threshold(regime)

        # Calculate Z-score
        z_score = self.calculate_z_score(data['close'], self.lookback_period)

        # RSI
        rsi_val = rsi(data['close'], 14).iloc[-1]

        # Bollinger Bands
        bb = bollinger_bands(data['close'], self.lookback_period)
        below_lower = current_price < bb['lower'].iloc[-1]
        above_upper = current_price > bb['upper'].iloc[-1]

        # BB squeeze
        squeeze_info = self.detect_bb_squeeze(data)

        # BUY signal (oversold)
        if z_score < -threshold and rsi_val < 30:
            confidence = min(abs(z_score) / threshold, 1.0)

            stop_loss = current_price * 0.95  # 5% stop
            take_profit = bb['middle'].iloc[-1]  # Target mean

            reasoning = f"Mean Reversion BUY: Z-score={z_score:.2f}, RSI={rsi_val:.1f}, "
            reasoning += f"Regime={regime}, Below BB lower={below_lower}"

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

        # SELL signal (overbought) - for shorting or exiting longs
        elif z_score > threshold and rsi_val > 70:
            confidence = min(z_score / threshold, 1.0)

            reasoning = f"Mean Reversion SELL: Z-score={z_score:.2f}, RSI={rsi_val:.1f}, "
            reasoning += f"Regime={regime}, Above BB upper={above_upper}"

            signal = Signal(
                symbol=symbol,
                signal_type=SignalType.SELL,
                price=current_price,
                timestamp=current_date,
                strategy_name=self.name,
                confidence=confidence,
                reasoning=reasoning
            )
            signals.append(signal)
            self.record_signal(signal)

        return signals

    def should_exit(self, position: Position, current_data: pd.DataFrame) -> bool:
        """Exit when price reverts to mean"""
        current_price = current_data['close'].iloc[-1]

        # Stop loss
        if position.stop_loss and current_price <= position.stop_loss:
            return True

        # Take profit (at mean)
        if position.take_profit and current_price >= position.take_profit:
            return True

        # Z-score normalized
        z_score = self.calculate_z_score(current_data['close'], self.lookback_period)
        if abs(z_score) < 0.5:  # Near mean
            return True

        # RSI normalized
        rsi_val = rsi(current_data['close'], 14).iloc[-1]
        if 40 < rsi_val < 60:  # Neutral RSI
            return True

        return False

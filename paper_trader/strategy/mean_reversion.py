"""
RSI mean-reversion strategy, long-term-trend filtered.

Entry: price is above its 200 SMA (long-term uptrend intact — this is a
pullback strategy, not a "catch the falling knife" strategy) and RSI(14)
crosses back up through 30 (buying the reversal off an oversold reading,
not the oversold reading itself, which can keep falling for days).
Exit: RSI crosses back above 70 (mean reversion played out), the ATR
stop, the take-profit, or price closing below the 200 SMA (the long-term
trend that justified the trade in the first place has broken).

Plain rule-based technical analysis, same as TrendFollowingStrategy —
not machine learning, not reinforcement learning.
"""
from typing import Optional

import pandas as pd

from paper_trader.config import settings
from paper_trader.strategy.base import Position, Signal, SignalType, Strategy
from paper_trader.strategy.indicators import atr, rsi, sma


class MeanReversionStrategy(Strategy):
    name = "Mean_Reversion_RSI"

    def generate_signal(self, data: pd.DataFrame) -> Optional[Signal]:
        min_bars = max(settings.slow_sma, settings.rsi_period, settings.atr_period) + 2
        if len(data) < min_bars:
            return None

        close = data["close"]
        long_term = sma(close, settings.slow_sma)
        rsi_series = rsi(close, settings.rsi_period)
        atr_series = atr(data["high"], data["low"], close, settings.atr_period)

        price = close.iloc[-1]
        trend_now = long_term.iloc[-1]
        rsi_now, rsi_prev = rsi_series.iloc[-1], rsi_series.iloc[-2]
        atr_now = atr_series.iloc[-1]

        if any(pd.isna(x) for x in (trend_now, rsi_now, rsi_prev, atr_now)):
            return None

        in_uptrend = price > trend_now
        crossed_up_from_oversold = rsi_prev <= settings.rsi_oversold and rsi_now > settings.rsi_oversold

        if not (in_uptrend and crossed_up_from_oversold):
            return None

        stop_loss = price - settings.atr_stop_multiple * atr_now
        if stop_loss <= 0 or stop_loss >= price:
            return None

        risk = price - stop_loss
        take_profit = price + settings.min_risk_reward * risk

        symbol = data["symbol"].iloc[-1] if "symbol" in data.columns else "UNKNOWN"
        timestamp = data.index[-1]

        return Signal(
            symbol=symbol,
            signal_type=SignalType.BUY,
            price=float(price),
            timestamp=timestamp,
            strategy_name=self.name,
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            reasoning=(
                f"RSI({settings.rsi_period}) crossed back above {settings.rsi_oversold:.0f} "
                f"({rsi_prev:.1f} -> {rsi_now:.1f}) while price {price:.2f} > "
                f"SMA{settings.slow_sma} ({trend_now:.2f}); ATR({settings.atr_period})={atr_now:.2f}"
            ),
        )

    def should_exit(self, position: Position, data: pd.DataFrame) -> bool:
        min_bars = max(settings.slow_sma, settings.rsi_period) + 1
        if len(data) < min_bars:
            return False

        close = data["close"]
        price = position.current_price
        long_term_now = sma(close, settings.slow_sma).iloc[-1]
        rsi_now = rsi(close, settings.rsi_period).iloc[-1]

        if position.stop_loss and price <= position.stop_loss:
            return True
        if position.take_profit and price >= position.take_profit:
            return True
        if not pd.isna(rsi_now) and rsi_now >= settings.rsi_overbought:
            return True
        if not pd.isna(long_term_now) and price < long_term_now:
            return True
        return False

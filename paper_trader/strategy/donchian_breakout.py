"""
Donchian channel breakout strategy (classic Turtle-style system).

Entry: today's close makes a new N-day high (breaks above the highest high
of the prior `donchian_entry_period` bars, not counting today).
Exit: today's close makes a new M-day low (breaks below the lowest low of
the prior `donchian_exit_period` bars, M < N so the exit channel is
tighter than the entry channel), or the ATR stop / take-profit is hit.

Unlike TrendFollowingStrategy (SMA crossover) and MeanReversionStrategy
(RSI pullback), this doesn't reference a moving average at all -- it's
pure price-extreme breakout, a different family of edge (trend
continuation off new highs, vs. crossing a smoothed average). Included as
strategy #2 of the "one by one" comparison the user asked for after
momentum rotation.

Plain rule-based technical analysis, same as the other strategies here --
not machine learning, not reinforcement learning.

Constructor args default to config.settings but can be overridden per
instance -- this is what lets run_backtest.py's --sweep sweep entry/exit
periods and the trend filter without touching global settings, so several
variants can be compared side by side in one real-data run instead of
guessing at one config blind.
"""
from typing import Optional

import pandas as pd

from paper_trader.config import settings
from paper_trader.strategy.base import Position, Signal, SignalType, Strategy
from paper_trader.strategy.indicators import atr, donchian_high, donchian_low, sma


class DonchianBreakoutStrategy(Strategy):
    def __init__(
        self,
        entry_period: int = None,
        exit_period: int = None,
        trend_filter_period: Optional[int] = None,
        name: str = "Donchian_Breakout",
    ):
        # trend_filter_period=None disables the filter (original
        # behavior); a positive value requires close > SMA(period) to
        # enter, which is the classic Turtle-system fix for whipsaw
        # breakouts in a sideways/choppy market -- a breakout against the
        # longer-term trend is far more likely to fail.
        self.entry_period = entry_period if entry_period is not None else settings.donchian_entry_period
        self.exit_period = exit_period if exit_period is not None else settings.donchian_exit_period
        self.trend_filter_period = trend_filter_period
        self.name = name

    def generate_signal(self, data: pd.DataFrame) -> Optional[Signal]:
        min_bars = max(self.entry_period, settings.atr_period, self.trend_filter_period or 0) + 2
        if len(data) < min_bars:
            return None

        close = data["close"]
        high = data["high"]
        low = data["low"]
        entry_channel = donchian_high(high, self.entry_period)
        atr_series = atr(high, low, close, settings.atr_period)

        price = close.iloc[-1]
        channel_now = entry_channel.iloc[-1]
        atr_now = atr_series.iloc[-1]

        if any(pd.isna(x) for x in (channel_now, atr_now)):
            return None

        breakout = price > channel_now
        if not breakout:
            return None

        if self.trend_filter_period is not None:
            trend_sma = sma(close, self.trend_filter_period).iloc[-1]
            if pd.isna(trend_sma) or price <= trend_sma:
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
                f"Close {price:.2f} broke above the {self.entry_period}-day "
                f"high ({channel_now:.2f}); ATR({settings.atr_period})={atr_now:.2f}"
            ),
        )

    def should_exit(self, position: Position, data: pd.DataFrame) -> bool:
        min_bars = self.exit_period + 2
        if len(data) < min_bars:
            return False

        close = data["close"]
        low = data["low"]
        price = position.current_price
        exit_channel = donchian_low(low, self.exit_period)
        channel_now = exit_channel.iloc[-1]

        if position.stop_loss and price <= position.stop_loss:
            return True
        if position.take_profit and price >= position.take_profit:
            return True
        if pd.isna(channel_now):
            return False
        return bool(close.iloc[-1] < channel_now)

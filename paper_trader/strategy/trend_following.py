"""
SMA(50/200) trend-following strategy with an ATR-based stop.

Entry: price closes above the 50 SMA while the 50 SMA is above the 200 SMA
(a Stage-2-style uptrend), and yesterday's close was at or below the 50 SMA
(so this is the crossover bar, not day 40 of an existing uptrend).
Exit: two consecutive closes back below the 50 SMA, or the ATR stop is hit.

A first backtest (2022-07 to 2026-09, SPY/QQQ/AAPL/MSFT/NVDA/AMD) showed
0/6 symbols beating buy-and-hold, with win rates of 8-27% — the exit was
firing on single-day dips below the 50 SMA, whipsawing out of real trends
before they played out (NVDA: -1.18% here vs +1268% buy-and-hold). The
2-consecutive-close confirmation and wider ATR stop below are the fix for
that; whether it actually helps still needs to be re-verified by running
the backtest again, not assumed.

This is plain rule-based technical analysis. It is not machine learning
and not reinforcement learning — it is not described as either anywhere
in this codebase, unlike the previous "Momentum_RL" strategy it replaces.
"""
from typing import Optional

import pandas as pd

from paper_trader.config import settings
from paper_trader.strategy.base import Position, Signal, SignalType, Strategy
from paper_trader.strategy.indicators import atr, sma


class TrendFollowingStrategy(Strategy):
    name = "Trend_Following_SMA"

    def generate_signal(self, data: pd.DataFrame) -> Optional[Signal]:
        min_bars = max(settings.slow_sma, settings.atr_period) + 2
        if len(data) < min_bars:
            return None

        close = data["close"]
        fast = sma(close, settings.fast_sma)
        slow = sma(close, settings.slow_sma)
        atr_series = atr(data["high"], data["low"], close, settings.atr_period)

        price = close.iloc[-1]
        fast_now, fast_prev = fast.iloc[-1], fast.iloc[-2]
        slow_now = slow.iloc[-1]
        prev_close = close.iloc[-2]
        atr_now = atr_series.iloc[-1]

        if any(pd.isna(x) for x in (fast_now, fast_prev, slow_now, atr_now)):
            return None

        uptrend = fast_now > slow_now
        crossed_up = prev_close <= fast_prev and price > fast_now

        if not (uptrend and crossed_up):
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
                f"Close {price:.2f} crossed above SMA{settings.fast_sma} "
                f"({fast_now:.2f}) with SMA{settings.fast_sma}>SMA{settings.slow_sma} "
                f"({slow_now:.2f}); ATR({settings.atr_period})={atr_now:.2f}"
            ),
        )

    def should_exit(self, position: Position, data: pd.DataFrame) -> bool:
        if len(data) < settings.fast_sma + 2:
            return False

        close = data["close"]
        price = position.current_price
        fast = sma(close, settings.fast_sma)

        if position.stop_loss and price <= position.stop_loss:
            return True
        if position.take_profit and price >= position.take_profit:
            return True

        # Require two consecutive daily closes below the 50 SMA, not one,
        # before treating this as a trend break. This checks the bar
        # series' own closes (a multi-day structural pattern), not
        # position.current_price — a single day's live price is a
        # different kind of comparison from "has the trend broken over
        # the last two closes."
        fast_now, fast_prev = fast.iloc[-1], fast.iloc[-2]
        if pd.isna(fast_now) or pd.isna(fast_prev):
            return False
        two_closes_below = close.iloc[-1] < fast_now and close.iloc[-2] < fast_prev
        return bool(two_closes_below)

"""
Intraday stop-loss backtest engine.

The existing engine.py evaluates a strategy once per bar -- entries via
generate_signal(), exits via the full should_exit() (which for every
strategy here also recomputes a daily indicator: a Donchian channel, an
SMA, an RSI). Feeding it hourly/minute bars directly would be wrong on
two counts: those indicators would be computed over hours instead of
days (a different, unvalidated strategy), and generate_signal() could
fire more than once per day.

This engine keeps entries and full (indicator-based) exits on the daily
bar -- exactly what was backtested and validated -- and adds ONLY a more
frequent stop-loss/take-profit check in between, using
Strategy.check_stop_only() against each intraday bar's low (for a stop)
and high (for a take-profit), not just its close. That mirrors what a
real intraday poll would catch: a stop can be breached and recovered
within a day, and a daily-close-only check misses that entirely.

Two results come out of a single run so they're directly comparable on
the same data: `daily_only` (equivalent to running engine.py) and
`with_intraday_stops` (same entries/full-exits, but the stop can also
fire between daily bars). The difference between them is the actual
measured value of adding intraday stop monitoring -- not a guess.

Why this is a separate module rather than a flag on engine.py: the bar
loop shape is genuinely different (nested daily/intraday loops vs. one
flat loop), and keeping it separate means engine.py -- already proven
correct and matching the checkpointed scoreboard -- is untouched.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import numpy as np
import pandas as pd
from loguru import logger

from paper_trader.config import settings
from paper_trader.execution.paper_trader import PaperTrader
from paper_trader.strategy.base import Position, Strategy


@dataclass
class IntradayStopResult:
    strategy_name: str
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float
    final_value: float
    total_return_pct: float
    num_trades: int
    win_rate: float
    profit_factor: float
    stop_only_exits: int  # count of exits that fired via check_stop_only
    # between daily bars -- i.e. would have been MISSED by daily-only
    # checking. Zero here means intraday monitoring changed nothing on
    # this symbol/period, a real and useful negative result, not a bug.

    def summary(self) -> str:
        return (
            f"{self.strategy_name} on {self.symbol} ({self.start_date} to {self.end_date}): "
            f"{self.total_return_pct:+.2f}%, {self.num_trades} trades, "
            f"{self.win_rate:.1f}% win rate, PF {self.profit_factor:.2f}, "
            f"{self.stop_only_exits} exits caught only by intraday stop-checking"
        )


def _position_size(portfolio_value: float, price: float, available_cash: float) -> float:
    target = portfolio_value * settings.max_position_size
    allocated = min(target, available_cash)
    if price <= 0 or allocated < 1.0:
        return 0.0
    return round(allocated / price, 6)


def _run(
    strategy: Strategy,
    daily: pd.DataFrame,
    intraday_by_day: dict,
    initial_capital: float,
    use_intraday_stops: bool,
) -> IntradayStopResult:
    """Shared loop for both daily_only and with_intraday_stops -- the only
    difference between the two calls is use_intraday_stops, so this stays
    a single implementation rather than two that could drift apart."""
    symbol = daily["symbol"].iloc[0] if "symbol" in daily.columns else "UNKNOWN"
    trader = PaperTrader(
        initial_capital=initial_capital,
        commission_rate=settings.commission_rate,
        slippage_rate=settings.slippage_rate,
    )
    min_bars = max(settings.slow_sma, settings.atr_period) + 2
    stop_only_exits = 0

    for i in range(min_bars, len(daily)):
        window = daily.iloc[: i + 1]
        date = window.index[-1]
        day_key = date.strftime("%Y-%m-%d")
        eod_price = float(window["close"].iloc[-1])

        position = trader.portfolio.positions.get(symbol)

        # Intraday stop check first -- if a position was open coming into
        # today, see whether any bar today breaches the stop/target before
        # we get to the full end-of-day should_exit() check. Skipped
        # entirely for the daily_only comparison run.
        if position and use_intraday_stops:
            todays_bars = intraday_by_day.get(day_key)
            if todays_bars is not None and not todays_bars.empty:
                pos_obj = Position(
                    symbol=symbol,
                    quantity=position["quantity"],
                    entry_price=position["entry_price"],
                    current_price=eod_price,
                    entry_time=position["entry_time"],
                    strategy_name=position["strategy"],
                    stop_loss=position.get("stop_loss"),
                    take_profit=position.get("take_profit"),
                )
                for _, bar in todays_bars.iterrows():
                    # A stop is breached if the bar's LOW touched it (not
                    # just its close) -- that's the whole point of
                    # intraday checking: catching a move the daily close
                    # alone would miss because price recovered by EOD.
                    # Symmetric for a take-profit against the bar's HIGH.
                    hit_stop = pos_obj.stop_loss and float(bar["low"]) <= pos_obj.stop_loss
                    hit_target = pos_obj.take_profit and float(bar["high"]) >= pos_obj.take_profit
                    if hit_stop or hit_target:
                        fill_price = pos_obj.stop_loss if hit_stop else pos_obj.take_profit
                        trader.place_order(
                            client_order_id=f"{symbol}-{bar.name.isoformat()}-INTRADAY-SELL",
                            symbol=symbol,
                            side="SELL",
                            quantity=position["quantity"],
                            price=float(fill_price),
                            strategy=strategy.name,
                            reasoning="intraday stop/target hit (would be missed by daily-close-only check)",
                        )
                        stop_only_exits += 1
                        position = None
                        break

        position = trader.portfolio.positions.get(symbol)
        if position:
            trader.update_prices({symbol: eod_price})
            pos_obj = Position(
                symbol=symbol,
                quantity=position["quantity"],
                entry_price=position["entry_price"],
                current_price=eod_price,
                entry_time=position["entry_time"],
                strategy_name=position["strategy"],
                stop_loss=position.get("stop_loss"),
                take_profit=position.get("take_profit"),
            )
            if strategy.should_exit(pos_obj, window):
                trader.place_order(
                    client_order_id=f"{symbol}-{date.isoformat()}-SELL",
                    symbol=symbol,
                    side="SELL",
                    quantity=position["quantity"],
                    price=eod_price,
                    strategy=strategy.name,
                    reasoning="should_exit triggered",
                )
        else:
            signal = strategy.generate_signal(window)
            if signal:
                qty = _position_size(trader.portfolio.total_value, signal.price, trader.portfolio.capital)
                if qty > 0:
                    trader.place_order(
                        client_order_id=f"{symbol}-{date.isoformat()}-BUY",
                        symbol=symbol,
                        side="BUY",
                        quantity=qty,
                        price=signal.price,
                        strategy=strategy.name,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        reasoning=signal.reasoning,
                    )

    final_value = trader.portfolio.total_value
    total_return_pct = (final_value - initial_capital) / initial_capital * 100
    metrics = trader.get_performance_metrics()

    return IntradayStopResult(
        strategy_name=strategy.name,
        symbol=symbol,
        start_date=str(daily.index[min_bars].date()) if len(daily) > min_bars else str(daily.index[0].date()),
        end_date=str(daily.index[-1].date()),
        initial_capital=initial_capital,
        final_value=final_value,
        total_return_pct=total_return_pct,
        num_trades=metrics["num_trades"],
        win_rate=metrics["win_rate"],
        profit_factor=metrics["profit_factor"],
        stop_only_exits=stop_only_exits,
    )


def run_intraday_stop_backtest(
    strategy: Strategy,
    daily: pd.DataFrame,
    intraday: pd.DataFrame,
    initial_capital: float,
) -> "tuple[IntradayStopResult, IntradayStopResult]":
    """
    daily: the same daily-bar OHLCV used by backtest/engine.py.
    intraday: finer-grained OHLCV (e.g. 1h) covering the same symbol and
      date range -- see paper_trader/data/binance_fetcher.py's `interval`
      param (BinanceFetcher already supports pulling this; no new
      fetcher needed, just a finer interval string).

    Returns (daily_only_result, with_intraday_stops_result) run against
    the identical entry/exit decisions so the only thing that can differ
    between them is stop_only_exits and whatever total_return/win_rate
    consequence that has. Run both, don't just eyeball one -- a positive
    stop_only_exits count is not automatically an improvement; it needs
    to be compared against the total_return_pct delta before concluding
    anything, same "backtest before trusting it" rule as the rest of
    this project.
    """
    if daily.empty:
        raise ValueError("No daily data to backtest")
    if intraday.empty:
        raise ValueError(
            "No intraday data to backtest -- this engine measures the "
            "*effect* of intraday stop-checking, so real intraday bars "
            "are required, not optional. Use BinanceFetcher(...).fetch(symbol, "
            "start_date, interval='1h') or similar."
        )

    intraday_by_day = {
        day: group for day, group in intraday.groupby(intraday.index.strftime("%Y-%m-%d"))
    }

    daily_only = _run(strategy, daily, intraday_by_day, initial_capital, use_intraday_stops=False)
    with_stops = _run(strategy, daily, intraday_by_day, initial_capital, use_intraday_stops=True)

    logger.info(f"[DAILY-ONLY]        {daily_only.summary()}")
    logger.info(f"[INTRADAY-STOPS]    {with_stops.summary()}")
    return daily_only, with_stops

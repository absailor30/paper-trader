"""
Backtesting engine. Runs a Strategy bar-by-bar over historical data using
the exact same PaperTrader execution logic (commission, slippage, sizing)
that live trading uses, so a backtest result and a live result are
comparable — they're produced by the same code path, not a separate
simulation that could silently diverge from what actually executes live.

Nothing in this codebase is wired to auto-execute until a strategy has
been run through here and shown positive expectancy net of costs.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List

import numpy as np
import pandas as pd
from loguru import logger

from paper_trader.config import settings
from paper_trader.execution.paper_trader import PaperTrader
from paper_trader.strategy.base import Position, Strategy


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float
    final_value: float
    total_return_pct: float
    cagr_pct: float
    benchmark_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    num_trades: int
    win_rate: float
    profit_factor: float

    def is_validated(self) -> bool:
        # Beating buy-and-hold on a falling stock (e.g. return -2%, benchmark
        # -20%) is not "edge" -- it's losing less than a bad benchmark. A
        # verdict must actually make money, not just outscore the comparison.
        # This is the single source of truth for "validated" -- callers
        # (run_backtest.py's per-symbol and aggregate counts, this summary)
        # must use it rather than re-deriving the same condition themselves.
        return (
            self.total_return_pct > self.benchmark_return_pct
            and self.total_return_pct > 0
            and self.num_trades >= 5
        )

    def summary(self) -> str:
        verdict = "POSITIVE EDGE" if self.is_validated() else "NOT VALIDATED"
        return (
            f"[{verdict}] {self.strategy_name} on {self.symbol} "
            f"({self.start_date} to {self.end_date}): "
            f"{self.total_return_pct:+.2f}% (buy-and-hold: {self.benchmark_return_pct:+.2f}%), "
            f"CAGR {self.cagr_pct:+.2f}%, Sharpe {self.sharpe_ratio:.2f}, "
            f"max drawdown {self.max_drawdown_pct:.2f}%, "
            f"{self.num_trades} trades, {self.win_rate:.1f}% win rate, "
            f"profit factor {self.profit_factor:.2f}"
        )


def _position_size(portfolio_value: float, price: float, available_cash: float) -> float:
    target = portfolio_value * settings.max_position_size
    allocated = min(target, available_cash)
    if price <= 0 or allocated < 1.0:
        return 0.0
    return round(allocated / price, 4)


def run_backtest(strategy: Strategy, data: pd.DataFrame, initial_capital: float) -> BacktestResult:
    if data.empty:
        raise ValueError("No data to backtest")

    symbol = data["symbol"].iloc[0] if "symbol" in data.columns else "UNKNOWN"
    trader = PaperTrader(
        initial_capital=initial_capital,
        commission_rate=settings.commission_rate,
        slippage_rate=settings.slippage_rate,
    )

    min_bars = max(settings.slow_sma, settings.atr_period) + 2
    equity_curve: List[float] = []
    dates: List[datetime] = []

    for i in range(min_bars, len(data)):
        window = data.iloc[: i + 1]
        date = window.index[-1]
        price = float(window["close"].iloc[-1])

        position = trader.portfolio.positions.get(symbol)
        if position:
            trader.update_prices({symbol: price})
            pos_obj = Position(
                symbol=symbol,
                quantity=position["quantity"],
                entry_price=position["entry_price"],
                current_price=price,
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
                    price=price,
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

        equity_curve.append(trader.portfolio.total_value)
        dates.append(date)

    final_value = trader.portfolio.total_value
    total_return_pct = (final_value - initial_capital) / initial_capital * 100

    days = max((dates[-1] - dates[0]).days, 1) if dates else 1
    years = days / 365.25
    cagr_pct = ((final_value / initial_capital) ** (1 / years) - 1) * 100 if years > 0 and final_value > 0 else 0.0

    buy_hold_shares = initial_capital / float(data["close"].iloc[min_bars])
    benchmark_final = buy_hold_shares * float(data["close"].iloc[-1])
    benchmark_return_pct = (benchmark_final - initial_capital) / initial_capital * 100

    equity = np.array(equity_curve)
    running_max = np.maximum.accumulate(equity) if len(equity) else np.array([initial_capital])
    drawdowns = (equity - running_max) / running_max * 100 if len(equity) else np.array([0.0])
    max_drawdown_pct = float(drawdowns.min()) if len(drawdowns) else 0.0

    daily_returns = np.diff(equity) / equity[:-1] if len(equity) > 1 else np.array([0.0])
    sharpe_ratio = (
        float(np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252))
        if len(daily_returns) > 1 and np.std(daily_returns) > 0
        else 0.0
    )

    metrics = trader.get_performance_metrics()

    result = BacktestResult(
        strategy_name=strategy.name,
        symbol=symbol,
        start_date=str(data.index[min_bars].date()) if len(data) > min_bars else str(data.index[0].date()),
        end_date=str(data.index[-1].date()),
        initial_capital=initial_capital,
        final_value=final_value,
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        benchmark_return_pct=benchmark_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        num_trades=metrics["num_trades"],
        win_rate=metrics["win_rate"],
        profit_factor=metrics["profit_factor"],
    )
    logger.info(result.summary())
    return result

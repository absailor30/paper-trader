"""
Backtesting engine for validating strategies against historical data
Simulates execution, commissions, slippage, and calculates standard quant metrics.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Type
import numpy as np
import pandas as pd
from loguru import logger

from src.strategies.base_strategy import BaseStrategy, Position, Signal, SignalType

@dataclass
class BacktestTrade:
    symbol: str
    entry_date: datetime
    exit_date: datetime
    entry_price: float
    exit_price: float
    quantity: float
    side: str
    pnl: float
    pnl_pct: float
    fees: float
    net_pnl: float
    strategy: str
    exit_reason: str

@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    initial_capital: float
    final_capital: float
    total_net_return_pct: float
    benchmark_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    total_trades: int
    win_rate_pct: float
    profit_factor: float
    avg_trade_pnl_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    max_consecutive_losses: int
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)

    def summary(self) -> str:
        return (
            f"=== {self.strategy_name} on {self.symbol} ===\n"
            f"Net Return: {self.total_net_return_pct:.2f}% | Benchmark: {self.benchmark_return_pct:.2f}%\n"
            f"Sharpe: {self.sharpe_ratio:.2f} | Sortino: {self.sortino_ratio:.2f} | Max DD: {self.max_drawdown_pct:.2f}%\n"
            f"Trades: {self.total_trades} | Win Rate: {self.win_rate_pct:.1f}% | Profit Factor: {self.profit_factor:.2f}\n"
            f"Avg Win: +{self.avg_win_pct:.2f}% | Avg Loss: {self.avg_loss_pct:.2f}%\n"
        )

class Backtester:
    """
    Event-driven bar-by-bar backtester.
    Avoids lookahead bias by streaming historical bars one at a time.
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        commission_pct: float = 0.001,  # 0.1% per trade (realistic for India delivery / US with fees)
        slippage_pct: float = 0.0005,    # 0.05% slippage on market orders
        max_position_pct: float = 0.12,  # 12% max capital per position
    ):
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.max_position_pct = max_position_pct

    def run(
        self,
        strategy: BaseStrategy,
        data: pd.DataFrame,
        symbol: str,
        warmup_bars: int = 150
    ) -> BacktestResult:
        """
        Run backtest bar-by-bar over data.

        Args:
            strategy: BaseStrategy instance
            data: DataFrame with OHLCV columns (lowercase) and datetime index or Date col
            symbol: Ticker
            warmup_bars: Minimum bars needed before generating signals
        """
        df = data.copy().reset_index(drop=True)
        if 'date' in df.columns:
            dates = pd.to_datetime(df['date'])
        else:
            dates = pd.date_range(start='2020-01-01', periods=len(df), freq='B')

        capital = self.initial_capital
        position: Optional[Position] = None
        completed_trades: List[BacktestTrade] = []
        equity_series: List[float] = []

        if len(df) <= warmup_bars:
            logger.warning(f"Data length {len(df)} <= warmup {warmup_bars}")
            return self._empty_result(strategy.name, symbol)

        for i in range(warmup_bars, len(df)):
            current_bar = df.iloc[i]
            history_so_far = df.iloc[: i + 1].copy()
            current_price = float(current_bar['close'])
            current_date = dates.iloc[i]

            # 1. Manage active position exit
            if position is not None:
                position.current_price = current_price
                should_exit = False
                exit_reason = ""

                # Stop loss
                if position.stop_loss and current_price <= position.stop_loss:
                    should_exit = True
                    exit_reason = "STOP_LOSS"
                # Take profit
                elif position.take_profit and current_price >= position.take_profit:
                    should_exit = True
                    exit_reason = "TAKE_PROFIT"
                # Strategy exit rule
                elif strategy.should_exit(position, history_so_far):
                    should_exit = True
                    exit_reason = "STRATEGY_EXIT"

                if should_exit:
                    exit_price = current_price * (1 - self.slippage_pct)
                    gross_pnl = (exit_price - position.entry_price) * position.quantity
                    exit_fee = exit_price * position.quantity * self.commission_pct
                    entry_fee = position.entry_price * position.quantity * self.commission_pct
                    total_fees = entry_fee + exit_fee
                    net_pnl = gross_pnl - total_fees
                    pnl_pct = (exit_price - position.entry_price) / position.entry_price * 100

                    capital += (exit_price * position.quantity) - exit_fee

                    completed_trades.append(
                        BacktestTrade(
                            symbol=symbol,
                            entry_date=position.entry_time,
                            exit_date=current_date,
                            entry_price=position.entry_price,
                            exit_price=exit_price,
                            quantity=position.quantity,
                            side="BUY",
                            pnl=gross_pnl,
                            pnl_pct=pnl_pct,
                            fees=total_fees,
                            net_pnl=net_pnl,
                            strategy=strategy.name,
                            exit_reason=exit_reason,
                        )
                    )
                    position = None

            # 2. Check for new entries if no active position
            if position is None:
                signals = strategy.generate_signals(history_so_far)
                buy_signals = [s for s in signals if s.signal_type == SignalType.BUY]

                if buy_signals:
                    sig = buy_signals[-1]
                    entry_price = current_price * (1 + self.slippage_pct)
                    alloc = capital * self.max_position_pct
                    quantity = alloc / entry_price

                    if alloc >= 10.0 and quantity > 0:
                        fee = alloc * self.commission_pct
                        capital -= (alloc + fee)
                        position = Position(
                            symbol=symbol,
                            quantity=quantity,
                            entry_price=entry_price,
                            current_price=entry_price,
                            entry_time=current_date,
                            strategy_name=strategy.name,
                            stop_loss=sig.stop_loss,
                            take_profit=sig.take_profit,
                        )

            # Record mark-to-market equity
            pos_val = (position.quantity * current_price) if position else 0.0
            equity_series.append(capital + pos_val)

        # Close open position at end
        if position is not None:
            last_price = float(df['close'].iloc[-1]) * (1 - self.slippage_pct)
            gross = (last_price - position.entry_price) * position.quantity
            fee = last_price * position.quantity * self.commission_pct
            net = gross - fee
            capital += (last_price * position.quantity) - fee
            completed_trades.append(
                BacktestTrade(
                    symbol=symbol,
                    entry_date=position.entry_time,
                    exit_date=dates.iloc[-1],
                    entry_price=position.entry_price,
                    exit_price=last_price,
                    quantity=position.quantity,
                    side="BUY",
                    pnl=gross,
                    pnl_pct=(last_price - position.entry_price) / position.entry_price * 100,
                    fees=fee,
                    net_pnl=net,
                    strategy=strategy.name,
                    exit_reason="END_OF_DATA",
                )
            )

        equity_curve = pd.Series(equity_series, index=dates.iloc[warmup_bars:])
        benchmark_ret = (float(df['close'].iloc[-1]) - float(df['close'].iloc[warmup_bars])) / float(df['close'].iloc[warmup_bars]) * 100

        return self._compute_metrics(
            strategy_name=strategy.name,
            symbol=symbol,
            capital=capital,
            equity_curve=equity_curve,
            trades=completed_trades,
            benchmark_return=benchmark_ret,
        )

    def _compute_metrics(
        self,
        strategy_name: str,
        symbol: str,
        capital: float,
        equity_curve: pd.Series,
        trades: List[BacktestTrade],
        benchmark_return: float
    ) -> BacktestResult:
        net_ret = (capital - self.initial_capital) / self.initial_capital * 100

        # Drawdown
        roll_max = equity_curve.cummax()
        drawdown = (equity_curve - roll_max) / roll_max * 100
        max_dd = abs(float(drawdown.min())) if len(drawdown) > 0 else 0.0

        # Returns & Sharpe
        daily_returns = equity_curve.pct_change().dropna()
        if len(daily_returns) > 1 and daily_returns.std() > 0:
            sharpe = float((daily_returns.mean() / daily_returns.std()) * np.sqrt(252))
            downside = daily_returns[daily_returns < 0]
            sortino = float((daily_returns.mean() / downside.std()) * np.sqrt(252)) if len(downside) > 0 and downside.std() > 0 else 0.0
        else:
            sharpe = 0.0
            sortino = 0.0

        # CAGR
        days = len(equity_curve)
        cagr = (((capital / self.initial_capital) ** (252 / max(days, 1))) - 1) * 100 if capital > 0 else -100.0

        # Trade metrics
        total = len(trades)
        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]
        win_rate = (len(wins) / total * 100) if total > 0 else 0.0

        gross_wins = sum(t.net_pnl for t in wins)
        gross_losses = abs(sum(t.net_pnl for t in losses))
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (99.0 if gross_wins > 0 else 0.0)

        avg_pnl = float(np.mean([t.pnl_pct for t in trades])) if total > 0 else 0.0
        avg_win = float(np.mean([t.pnl_pct for t in wins])) if wins else 0.0
        avg_loss = float(np.mean([t.pnl_pct for t in losses])) if losses else 0.0

        # Max consecutive losses
        consec = 0
        max_consec = 0
        for t in trades:
            if t.net_pnl <= 0:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 0

        return BacktestResult(
            strategy_name=strategy_name,
            symbol=symbol,
            initial_capital=self.initial_capital,
            final_capital=capital,
            total_net_return_pct=net_ret,
            benchmark_return_pct=benchmark_return,
            cagr_pct=cagr,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown_pct=max_dd,
            total_trades=total,
            win_rate_pct=win_rate,
            profit_factor=profit_factor,
            avg_trade_pnl_pct=avg_pnl,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            max_consecutive_losses=max_consec,
            trades=trades,
            equity_curve=equity_curve,
        )

    def _empty_result(self, strategy_name: str, symbol: str) -> BacktestResult:
        return BacktestResult(
            strategy_name=strategy_name,
            symbol=symbol,
            initial_capital=self.initial_capital,
            final_capital=self.initial_capital,
            total_net_return_pct=0.0,
            benchmark_return_pct=0.0,
            cagr_pct=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            max_drawdown_pct=0.0,
            total_trades=0,
            win_rate_pct=0.0,
            profit_factor=0.0,
            avg_trade_pnl_pct=0.0,
            avg_win_pct=0.0,
            avg_loss_pct=0.0,
            max_consecutive_losses=0,
        )

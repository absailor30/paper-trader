"""
Momentum rotation backtester.

Ranks the universe by trailing N-day return at each rebalance date, holds
the top K names equal-weighted, and fully re-allocates at every rebalance
-- using the same PaperTrader execution path (commission, slippage) as
the single-symbol backtester in engine.py, so results are comparable.

Mirrors engine.py's separation of concerns: this module takes a
pre-built price matrix and knows nothing about fetching data (that's
run_rotation_backtest.py's job), so it's testable against synthetic
data with no network involved.
"""
import math
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd
from loguru import logger

from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.execution.paper_trader import PaperTrader
from paper_trader.strategy.momentum_rotation import select_top_momentum


@dataclass
class RotationBacktestResult:
    universe_name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_value: float
    total_return_pct: float
    cagr_pct: float
    benchmark_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    num_rebalances: int
    num_trades: int

    def is_validated(self) -> bool:
        return self.total_return_pct > self.benchmark_return_pct and self.total_return_pct > 0

    def summary(self) -> str:
        verdict = "POSITIVE EDGE" if self.is_validated() else "NOT VALIDATED"
        return (
            f"[{verdict}] Momentum_Rotation on {self.universe_name} "
            f"({self.start_date} to {self.end_date}): "
            f"{self.total_return_pct:+.2f}% (equal-weight buy-and-hold: {self.benchmark_return_pct:+.2f}%), "
            f"CAGR {self.cagr_pct:+.2f}%, Sharpe {self.sharpe_ratio:.2f}, "
            f"max drawdown {self.max_drawdown_pct:.2f}%, "
            f"{self.num_rebalances} rebalances, {self.num_trades} trades"
        )


def build_price_matrix(fetcher: DataFetcher, symbols: List[str], start_date: str, india: bool) -> pd.DataFrame:
    closes = {}
    for symbol in symbols:
        df = fetcher.fetch(symbol, start_date=start_date, india=india)
        if not df.empty:
            closes[symbol] = df["close"]
        else:
            logger.warning(f"No data for {symbol}, excluded from rotation universe")

    price_df = pd.DataFrame(closes).sort_index()
    # Forward-fill short gaps (holiday calendars don't align across
    # exchanges/ETFs), then drop rows before every symbol has real data --
    # a partial universe on a given day would silently bias the ranking.
    price_df = price_df.ffill(limit=5).dropna(how="any")
    return price_df


def run_rotation_backtest(
    price_df: pd.DataFrame,
    universe_name: str,
    initial_capital: float = 10_000.0,
) -> RotationBacktestResult:
    lookback = settings.rotation_lookback_days
    rebalance_every = settings.rotation_rebalance_days

    if len(price_df) < lookback + rebalance_every:
        raise ValueError(
            f"Not enough aligned history for {universe_name} rotation backtest "
            f"({len(price_df)} bars, need >= {lookback + rebalance_every})"
        )

    trader = PaperTrader(
        initial_capital=initial_capital,
        commission_rate=settings.commission_rate,
        slippage_rate=settings.slippage_rate,
    )

    equity_curve: List[float] = []
    dates = []
    num_rebalances = 0

    for i in range(lookback, len(price_df)):
        date = price_df.index[i]
        prices_today: Dict[str, float] = price_df.iloc[i].to_dict()
        trader.update_prices(prices_today)

        if (i - lookback) % rebalance_every == 0:
            momentum_today = {
                symbol: price_df[symbol].iloc[i] / price_df[symbol].iloc[i - lookback] - 1
                for symbol in price_df.columns
            }
            target = select_top_momentum(momentum_today)

            # Fully liquidate, then equal-weight buy into the new target
            # set. Simpler and more transparent than partial rebalancing,
            # at the cost of extra turnover -- already priced into the
            # result via commission/slippage on every trade.
            for symbol in list(trader.portfolio.positions):
                position = trader.portfolio.positions[symbol]
                trader.place_order(
                    client_order_id=f"{symbol}-{date.isoformat()}-REBAL-SELL",
                    symbol=symbol,
                    side="SELL",
                    quantity=position["quantity"],
                    price=prices_today[symbol],
                    strategy="Momentum_Rotation",
                    reasoning="rebalance: rotated out",
                )

            if target:
                # Buys fill at price*(1+slippage) plus commission on top, so
                # a naive capital/len(target) split overshoots the actual
                # cost by that fraction on every symbol -- exhausting
                # capital before the last 1-2 buys, which then get rejected.
                # Reserve that headroom up front.
                cost_headroom = (1 + settings.slippage_rate) * (1 + settings.commission_rate)
                allocation = trader.portfolio.capital / len(target) / cost_headroom
                for symbol in target:
                    price = prices_today[symbol]
                    # Floor, not round -- rounding up would spend slightly
                    # more than this symbol's allocation, starving whatever
                    # buys later in the same rebalance loop.
                    qty = math.floor(allocation / price * 10_000) / 10_000
                    if qty > 0:
                        trader.place_order(
                            client_order_id=f"{symbol}-{date.isoformat()}-REBAL-BUY",
                            symbol=symbol,
                            side="BUY",
                            quantity=qty,
                            price=price,
                            strategy="Momentum_Rotation",
                            reasoning=f"rebalance: top momentum {momentum_today[symbol]:+.2%}",
                        )

            num_rebalances += 1

        equity_curve.append(trader.portfolio.total_value)
        dates.append(date)

    final_value = trader.portfolio.total_value
    total_return_pct = (final_value - initial_capital) / initial_capital * 100

    days = max((dates[-1] - dates[0]).days, 1)
    years = days / 365.25
    cagr_pct = ((final_value / initial_capital) ** (1 / years) - 1) * 100 if years > 0 and final_value > 0 else 0.0

    # Benchmark: equal-weight buy-and-hold of the same universe over the
    # same window -- the fair comparison for a rotation strategy, not a
    # single index, since the rotation strategy is itself drawn from
    # this basket.
    start_prices = price_df.iloc[lookback]
    end_prices = price_df.iloc[-1]
    per_symbol_capital = initial_capital / len(price_df.columns)
    benchmark_final = sum(
        (per_symbol_capital / start_prices[symbol]) * end_prices[symbol] for symbol in price_df.columns
    )
    benchmark_return_pct = (benchmark_final - initial_capital) / initial_capital * 100

    equity = np.array(equity_curve)
    running_max = np.maximum.accumulate(equity)
    drawdowns = (equity - running_max) / running_max * 100
    max_drawdown_pct = float(drawdowns.min())

    daily_returns = np.diff(equity) / equity[:-1] if len(equity) > 1 else np.array([0.0])
    sharpe_ratio = (
        float(np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252))
        if len(daily_returns) > 1 and np.std(daily_returns) > 0
        else 0.0
    )

    result = RotationBacktestResult(
        universe_name=universe_name,
        start_date=str(dates[0].date()),
        end_date=str(dates[-1].date()),
        initial_capital=initial_capital,
        final_value=final_value,
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        benchmark_return_pct=benchmark_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        num_rebalances=num_rebalances,
        num_trades=len(trader.orders),
    )
    logger.info(result.summary())
    return result

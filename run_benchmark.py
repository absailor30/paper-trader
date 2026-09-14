"""
Benchmark backtest runner across US and Indian universe
Runs all 5 strategies on 3-year historical data.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.data_fetcher import DataFetcher
from src.strategies import (
    CANSLIMStrategy,
    SEPAStrategy,
    StageAnalysisStrategy,
    MomentumRLStrategy,
    MeanReversionStrategy,
)
from src.execution.backtester import Backtester
from loguru import logger
import pandas as pd

def run_benchmark():
    fetcher = DataFetcher()
    backtester = Backtester(
        initial_capital=10000.0,
        commission_pct=0.001,
        slippage_pct=0.0005,
        max_position_pct=0.15
    )

    test_symbols = [
        ("NVDA", "US"),
        ("XOM", "US"),
        ("AAPL", "US"),
        ("RELIANCE", "INDIA"),
        ("HDFCBANK", "INDIA"),
        ("SHRIRAMFIN", "INDIA")
    ]

    strategies = [
        CANSLIMStrategy(),
        SEPAStrategy(),
        StageAnalysisStrategy(),
        MomentumRLStrategy(),
        MeanReversionStrategy()
    ]

    records = []

    print("\n" + "=" * 65)
    print("STARTING MULTI-MARKET HISTORICAL STRATEGY BENCHMARK (3-YEAR)")
    print("=" * 65)

    for symbol, market in test_symbols:
        print(f"\nFetching data for {symbol} ({market})...")
        if market == "US":
            df = fetcher.fetch_us_stock_data(symbol, start_date="2023-01-01")
        else:
            df = fetcher.fetch_india_stock_data(symbol, start_date="2023-01-01")

        if df.empty or len(df) < 160:
            print(f"Skipping {symbol} (insufficient bars)")
            continue

        for strat in strategies:
            res = backtester.run(strat, df, symbol=symbol, warmup_bars=150)
            records.append({
                "Market": market,
                "Symbol": symbol,
                "Strategy": strat.name,
                "Net Return %": round(res.total_net_return_pct, 2),
                "Benchmark %": round(res.benchmark_return_pct, 2),
                "Sharpe": round(res.sharpe_ratio, 2),
                "Max DD %": round(res.max_drawdown_pct, 2),
                "Trades": res.total_trades,
                "Win Rate %": round(res.win_rate_pct, 1),
                "Profit Factor": round(res.profit_factor, 2),
            })
            print(f"  {strat.name:<18} | Net Ret: {res.total_net_return_pct:>6.2f}% | Max DD: {res.max_drawdown_pct:>5.2f}% | Trades: {res.total_trades:>3} | WR: {res.win_rate_pct:>5.1f}%")

    results_df = pd.DataFrame(records)
    print("\n" + "=" * 65)
    print("BENCHMARK RESULTS SUMMARY (SORTED BY SHARPE)")
    print("=" * 65)
    if not results_df.empty:
        sorted_df = results_df.sort_values(by="Sharpe", ascending=False)
        print(sorted_df.to_string(index=False))
        os.makedirs("logs", exist_ok=True)
        sorted_df.to_csv("logs/benchmark_results.csv", index=False)
        print("\nSaved benchmark results to logs/benchmark_results.csv")

if __name__ == "__main__":
    run_benchmark()

"""
Diagnostic tool to inspect indicators and entry criteria across Indian universe
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data.data_fetcher import DataFetcher
from src.strategies import (
    CANSLIMStrategy,
    SEPAStrategy,
    StageAnalysisStrategy,
    MomentumRLStrategy,
    MeanReversionStrategy,
)
from src.strategies.indicators import sma, rsi, bollinger_bands

def diagnose_indian_universe():
    fetcher = DataFetcher()
    symbols = [
        "SHRIRAMFIN", "HDFCBANK", "RELIANCE", "DRREDDY", "TECHM", "KOTAKBANK",
        "TCS", "INFY", "ICICIBANK", "SBIN", "BHARTIARTL", "LT", "AXISBANK",
        "BAJFINANCE", "NTPC", "TITAN", "HDFCLIFE", "WIPRO", "INDIGO", "ITC",
        "HINDUNILVR", "SUNPHARMA"
    ]

    strategies = [
        CANSLIMStrategy(),
        SEPAStrategy(),
        StageAnalysisStrategy(),
        MomentumRLStrategy(),
        MeanReversionStrategy(),
    ]

    print("=" * 70)
    print("DIAGNOSING INDIAN STOCKS ENTRY CRITERIA")
    print("=" * 70)

    for sym in symbols:
        df = fetcher.fetch_india_stock_data(sym, start_date="2024-01-01")
        if df.empty or len(df) < 50:
            print(f"{sym}: Insufficient data ({len(df)} bars)")
            continue

        close = df['close'].iloc[-1]
        rsi_val = rsi(df['close'], 14).iloc[-1]
        avg_vol = df['volume'].tail(20).mean()
        curr_vol = df['volume'].iloc[-1]
        vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 0

        print(f"\n--- {sym} | Price: {close:.2f} | RSI: {rsi_val:.1f} | Vol Ratio: {vol_ratio:.2f}x ---")

        signals_found = 0
        for strat in strategies:
            sigs = strat.generate_signals(df)
            if sigs:
                signals_found += len(sigs)
                for s in sigs:
                    print(f"  --> TRIGGERED {strat.name}: {s.signal_type.value} @ {s.price:.2f}")

        if signals_found == 0:
            # Show why SEPA / Stage / Momentum didn't trigger
            sma_50 = sma(df['close'], 50).iloc[-1] if len(df) >= 50 else 0
            sma_150 = sma(df['close'], 150).iloc[-1] if len(df) >= 150 else 0
            print(f"  [No Signal] 50-SMA: {sma_50:.1f}, 150-SMA: {sma_150:.1f}")
            print(f"  [Condition Audit] Price > 50-SMA: {close > sma_50}, Price > 150-SMA: {close > sma_150}, Vol Surge (>1.3x): {vol_ratio >= 1.3}")

if __name__ == "__main__":
    diagnose_indian_universe()

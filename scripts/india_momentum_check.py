"""Why does each India stock (not) qualify for the live momentum entry?

Live rule (paper_trader/strategy/momentum_trend.py): 126-day return >= +10%
AND close > SMA50. Prints both numbers per stock plus the verdict. Needs real
market data, so run via the india-momentum-check workflow, not the sandbox.
"""
from datetime import datetime, timedelta

from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.strategy.indicators import sma
from paper_trader.strategy.momentum_trend import MomentumTrend

LOOKBACK, MIN_RET, SMA_N = 126, 0.10, 50

fx = DataFetcher()
strategy = MomentumTrend(LOOKBACK, MIN_RET, SMA_N)
start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
qualified = 0
print(f"INDIA live momentum check (need {LOOKBACK}d return >= {MIN_RET:.0%} and close > SMA{SMA_N})")
for sym in settings.india_stocks:
    df = fx.fetch(sym, start_date=start, india=True)
    if df.empty or len(df) <= LOOKBACK + 2:
        print(f"{sym:12s} no/too little data")
        continue
    close = df["close"]
    ret = close.iloc[-1] / close.iloc[-1 - LOOKBACK] - 1
    vs_sma = close.iloc[-1] / sma(close, SMA_N).iloc[-1] - 1
    ok = strategy.generate_signal(df) is not None
    qualified += ok
    print(f"{sym:12s} 126d ret={ret * 100:+7.2f}% (need >=10)  vs SMA50={vs_sma * 100:+7.2f}% (need >0)  "
          f"last bar {df.index[-1].date()}  -> {'QUALIFIES' if ok else 'no'}")
print(f"\n{qualified}/{len(settings.india_stocks)} stocks qualify today")

"""Print every symbol's distance to its Donchian entry-channel high (how close each is to a breakout signal). Needs real market data, so run via the breakout-distance workflow, not the sandbox."""
from datetime import datetime, timedelta
from paper_trader.config import settings
from paper_trader.data.binance_fetcher import BinanceFetcher
from paper_trader.strategy.indicators import donchian_high, sma
from paper_trader.data.fetcher import DataFetcher

def row(sym, df, n, tf, cap=None):
    c = df["close"].iloc[-1]
    ch = donchian_high(df["high"], n).iloc[-1]
    s = f"{sym:12s} close={c:10.2f} {n}d-high={ch:10.2f} to_breakout={(ch/c-1)*100:6.2f}%"
    if tf:
        t = sma(df["close"], tf).iloc[-1]
        s += f" | vs SMA{tf}={(c/t-1)*100:6.2f}%"
    if cap:
        s += f" | 1 share = {c/cap*100:5.1f}% of capital"
    print(s)

start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
n = settings.donchian_entry_period
print(f"STOCKS entry={n} trendSMA=100")
fx = DataFetcher()
for mkt, syms, india in (("US", settings.us_stocks, False), ("INDIA", settings.india_stocks, True)):
    print("--", mkt)
    for s in syms:
        try:
            df = fx.fetch(s, start_date=start, india=india)
            row(s, df, n, 100, cap=settings.india_capital if india else None)
        except Exception as e:
            print(s, "ERR", e)
print("CRYPTO entry=55")
f = BinanceFetcher(market="spot")
for s, df in f.fetch_many(settings.crypto_pairs, start_date=start).items():
    row(s, df, 55, None)

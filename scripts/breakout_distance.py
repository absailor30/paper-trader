"""Print every symbol's distance to its Donchian entry-channel high (how close each is to a breakout signal). Needs real market data, so run via the breakout-distance workflow, not the sandbox."""
from datetime import datetime, timedelta
from paper_trader.config import settings
from paper_trader.data.binance_fetcher import BinanceFetcher
from paper_trader.strategy.indicators import donchian_high, sma
import yfinance as yf

def row(sym, df, n, tf):
    c = df["close"].iloc[-1]
    ch = donchian_high(df["high"], n).iloc[-1]
    s = f"{sym:12s} close={c:10.2f} {n}d-high={ch:10.2f} to_breakout={(ch/c-1)*100:6.2f}%"
    if tf:
        t = sma(df["close"], tf).iloc[-1]
        s += f" | vs SMA{tf}={(c/t-1)*100:6.2f}%"
    print(s)

start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
n = settings.donchian_entry_period
print(f"STOCKS entry={n} trendSMA=100")
for mkt, syms in (("US", settings.us_stocks), ("INDIA", settings.india_stocks)):
    print("--", mkt)
    for s in syms:
        try:
            df = yf.Ticker(s).history(start=start, auto_adjust=False)
            df.columns = [x.lower() for x in df.columns]
            row(s, df, n, 100)
        except Exception as e:
            print(s, "ERR", e)
print("CRYPTO entry=55")
f = BinanceFetcher(market="spot")
for s, df in f.fetch_many(settings.crypto_pairs, start_date=start).items():
    row(s, df, 55, None)

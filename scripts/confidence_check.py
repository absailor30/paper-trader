"""Does the confidence score mean anything? On ~10y of real data, replay the LIVE strategies per market
(US Donchian+SMA100, India momentum, crypto Donchian 20/10), score every signal with rule_confidence at entry,
follow the trade to its strategy exit, and compare outcomes by confidence bucket and confidence-weighted vs flat sizing.
Needs real market data, so run via the confidence-check workflow."""
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

from paper_trader.config import settings
from paper_trader.confidence import rule_confidence, size_fraction
from paper_trader.data.binance_fetcher import BinanceFetcher
from paper_trader.data.fetcher import DataFetcher
from paper_trader.strategy.base import Position
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy
from paper_trader.strategy.momentum_trend import MomentumTrend

STRATS = {
    "US": lambda: DonchianBreakoutStrategy(trend_filter_period=100),
    "INDIA": lambda: MomentumTrend(126, 0.10, 50),
    "CRYPTO": lambda: DonchianBreakoutStrategy(20, 10, None, name="Donchian_Crypto_20_10"),
}
DATA: dict = {}


def trades_for(task):
    market, symbol = task
    df, strat = DATA[(market, symbol)], STRATS[market]()
    out, i = [], max(settings.slow_sma, settings.atr_period) + 2
    cost = 2 * settings.commission_rate + settings.slippage_rate * 2
    while i < len(df) - 1:
        window = df.iloc[: i + 1]
        sig = strat.generate_signal(window)
        if sig is None:
            i += 1
            continue
        conf = rule_confidence(window).score
        j = i + 1
        while j < len(df) - 1:
            price = float(df["close"].iloc[j])
            pos = Position(symbol, 1.0, sig.price, price, df.index[i], strat.name, sig.stop_loss, sig.take_profit)
            if strat.should_exit(pos, df.iloc[: j + 1]):
                break
            j += 1
        exit_price = float(df["close"].iloc[j])
        out.append({"market": market, "symbol": symbol, "conf": conf, "ret": exit_price / sig.price - 1 - cost,
                    "days": j - i, "date": str(df.index[i].date())})
        i = j + 1
    return out


def main():
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    start = (datetime.now() - timedelta(days=365 * 10)).strftime("%Y-%m-%d")
    fx, bx = DataFetcher(), BinanceFetcher(market="spot")
    tasks = []
    for market, symbols in (("US", settings.us_stocks), ("INDIA", settings.india_stocks), ("CRYPTO", settings.crypto_pairs)):
        for s in symbols:
            df = bx.fetch(s, start_date=start) if market == "CRYPTO" else fx.fetch(s, start_date=start, india=(market == "INDIA"))
            if not df.empty:
                DATA[(market, s)] = df
                tasks.append((market, s))
    with ProcessPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
        trades = [t for batch in pool.map(trades_for, tasks, chunksize=1) for t in batch]
    df = pd.DataFrame(trades)
    print(f"\n{len(df)} signals across {df['symbol'].nunique()} symbols, "
          f"{df['date'].min()} to {df['date'].max()}\n")
    report(df, "ALL MARKETS")
    for m in ("US", "INDIA", "CRYPTO"):
        if (df["market"] == m).sum() >= 15:
            report(df[df["market"] == m], m)


def report(df, label):
    print(f"=== {label}: n={len(df)}  win rate {100 * (df['ret'] > 0).mean():.1f}%  avg {100 * df['ret'].mean():+.2f}%  "
          f"median {100 * df['ret'].median():+.2f}%")
    if len(df) < 15:
        return
    rho = df["conf"].rank().corr(df["ret"].rank())  # Spearman = Pearson on ranks (no scipy needed)
    print(f"    Spearman(confidence, return) = {rho:+.3f}   (0 = no relation; +ve = higher confidence did better)")
    df = df.assign(bucket=pd.qcut(df["conf"], 3, labels=["low third", "middle third", "high third"], duplicates="drop"))
    for b, g in df.groupby("bucket", observed=True):
        print(f"    {b:13s} conf {g['conf'].min():.2f}-{g['conf'].max():.2f}  n={len(g):4d}  win {100 * (g['ret'] > 0).mean():5.1f}%  "
              f"avg {100 * g['ret'].mean():+6.2f}%  median {100 * g['ret'].median():+6.2f}%")
    f = df["conf"].map(size_fraction)
    kept = df[f > 0]
    flat = kept["ret"].mean()
    weighted = (kept["ret"] * f[kept.index]).sum() / f[kept.index].sum() if len(kept) else float("nan")
    print(f"    signals skipped by confidence_min: {(f == 0).sum()} of {len(df)};  avg return per $ deployed: "
          f"flat sizing {100 * flat:+.2f}%  vs confidence-weighted {100 * weighted:+.2f}%\n")


if __name__ == "__main__":
    main()

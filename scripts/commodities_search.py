"""Which rule (if any) works on the 8 commodity funds? Each rule is scored in THREE separate time periods
across ~10 years of real data (about 2016-19, 2019-23, 2023-26); a rule only counts as robust if it is
positive in all three, which is much harder to pass by luck than one in-sample/out-of-sample split.
Reuses the engine/runner from scripts/india_strategy_search.py. Needs real market data, so run via the
commodities-search workflow, not the sandbox."""
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta

from loguru import logger

import scripts.india_strategy_search as base
from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy
from paper_trader.strategy.mean_reversion import MeanReversionStrategy
from paper_trader.strategy.momentum_trend import MomentumTrend
from paper_trader.strategy.trend_following import TrendFollowingStrategy

PERIODS = ("P1", "P2", "P3")
MIN_TRADES = 15


def variants() -> dict:
    def d(e, x, t, n):
        return lambda: DonchianBreakoutStrategy(e, x, t, name=n)

    return {
        "Donchian 10/5": d(10, 5, None, "D10_5"),
        "Donchian 20/10": d(20, 10, None, "D20_10"),
        "Donchian 30/15": d(30, 15, None, "D30_15"),
        "Donchian 55/20": d(55, 20, None, "D55_20"),
        "Donchian 100/50": d(100, 50, None, "D100_50"),
        "Donchian 20/10 + SMA100": d(20, 10, 100, "D20_10_t100"),
        "Donchian 55/20 + SMA200": d(55, 20, 200, "D55_20_t200"),
        "Momentum 63d>=5% + SMA50": lambda: MomentumTrend(63, 0.05, 50),
        "Momentum 126d>=10% + SMA50": lambda: MomentumTrend(126, 0.10, 50),
        "Momentum 252d>=10% + SMA100": lambda: MomentumTrend(252, 0.10, 100),
        "Trend following SMA50/200": TrendFollowingStrategy,
        "RSI dip-buying": MeanReversionStrategy,
    }


def slice_periods(symbol, df):
    n = len(df)
    edges = [0, n // 3, 2 * n // 3, n]
    for k, name in enumerate(PERIODS):
        lo, hi = edges[k], edges[k + 1]
        start = max(0, lo - base.MIN_BARS)  # warm-up bars so trading starts exactly at `lo`
        if hi - start > base.MIN_BARS + 20:
            base.SLICES[(symbol, name)] = df.iloc[start:hi]


def run_all():
    tasks = [(v, sym, per) for v in base.VARIANTS for (sym, per) in base.SLICES]
    with ProcessPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
        return [r for r in pool.map(base._run, tasks, chunksize=1) if r]


def report(results) -> None:
    print(f"\n=== COMMODITIES, {len(settings.commodities)} funds, per-fund {base.CAPITAL:,.0f}, {settings.max_position_size:.0%} position ===")
    bh = {p: base.summarize([r for r in results if r[2] == p and r[0] == next(iter(base.VARIANTS))])["avg_bh"] for p in PERIODS}
    print("Buy-and-hold per fund by period: " + "  ".join(f"{p} {bh[p]:+.1f}% (= {bh[p] * settings.max_position_size:+.1f}% at 12% exposure)" for p in PERIODS))
    robust = []
    for v in base.VARIANTS:
        sums = {p: base.summarize([r for r in results if r[0] == v and r[2] == p]) for p in PERIODS}
        print(f"\n{v}")
        for p in PERIODS:
            print(f"  {p}: {base.fmt(sums[p])}")
        if all(s["avg_ret"] > 0 and s["med_pf"] > 1 and s["trades"] >= MIN_TRADES for s in sums.values()):
            robust.append((min(s["avg_ret"] for s in sums.values()), v))
    print("\n=== ROBUST: positive avg return, median PF > 1 and >= 15 trades in ALL THREE periods ===")
    for worst, v in sorted(robust, reverse=True):
        print(f"  {v}: worst-period avg return {worst:+.2f}%")
    if not robust:
        print("  NONE")
    print("\n=== Per fund, return %/trades in P1 | P2 | P3 for the robust rules (or the 3 best by worst period if none) ===")
    shown = [v for _, v in sorted(robust, reverse=True)] or [
        v for _, v in sorted(((min(base.summarize([r for r in results if r[0] == v and r[2] == p])["avg_ret"] for p in PERIODS), v)
                              for v in base.VARIANTS), reverse=True)[:3]]
    for v in shown:
        print(v)
        for sym in settings.commodities:
            cells = []
            for p in PERIODS:
                r = [x for x in results if x[0] == v and x[1] == sym and x[2] == p]
                cells.append(f"{r[0][3]:+6.1f}%/{r[0][6]:2d}t" if r else "   n/a   ")
            print(f"  {sym:5s} " + " | ".join(cells))


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    base.VARIANTS.clear()
    base.VARIANTS.update(variants())
    start = (datetime.now() - timedelta(days=365 * 10 + 30)).strftime("%Y-%m-%d")
    fx = DataFetcher()
    for sym in settings.commodities:
        df = fx.fetch(sym, start_date=start)
        if df.empty:
            print(f"{sym}: no data, skipped")
            continue
        print(f"{sym}: {len(df)} bars {df.index[0].date()} -> {df.index[-1].date()}")
        slice_periods(sym, df)
    report(run_all())


if __name__ == "__main__":
    main()

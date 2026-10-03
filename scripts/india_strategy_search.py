"""Backtest looser-trend-filter Donchian variants and alternative strategies on the India universe.

Each variant is scored twice on real data: in-sample (everything before the
last 3 years) and out-of-sample (the last 3 years). A variant only counts as
a candidate if it is positive in BOTH, because picking the best of many
variants on one period just finds noise. Needs real market data, so run via
the india-strategy-search workflow, not the sandbox.
"""
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

from paper_trader.backtest.engine import run_backtest
from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy
from paper_trader.strategy.mean_reversion import MeanReversionStrategy
from paper_trader.strategy.momentum_trend import MomentumTrend

CAPITAL = 10_000.0
OOS_YEARS = 3
MIN_BARS = max(settings.slow_sma, settings.atr_period) + 2


def build_variants() -> dict:
    v = {}
    for entry, exit_ in ((20, 10), (10, 5), (55, 20)):
        for tf in (None, 100, 50, 20):
            name = f"Donchian_{entry}_{exit_}_tf{tf or 'none'}"
            v[name] = (lambda e=entry, x=exit_, t=tf, n=name: DonchianBreakoutStrategy(e, x, t, name=n))
    for lb, mr, sn in ((126, 0.10, 50), (63, 0.05, 50), (126, 0.0, 100)):
        s = MomentumTrend(lb, mr, sn)
        v[s.name] = (lambda a=lb, b=mr, c=sn: MomentumTrend(a, b, c))
    v["Mean_Reversion_RSI"] = MeanReversionStrategy
    return v


VARIANTS = build_variants()
SLICES: dict = {}


def split_slices(symbol: str, df: pd.DataFrame) -> None:
    cutoff_ts = df.index[-1] - pd.Timedelta(days=365 * OOS_YEARS)
    cut = int(df.index.searchsorted(cutoff_ts))
    if cut - MIN_BARS > MIN_BARS:
        SLICES[(symbol, "IS")] = df.iloc[:cut]
    if cut >= MIN_BARS:
        SLICES[(symbol, "OOS")] = df.iloc[cut - MIN_BARS:]


def _run(task):
    variant, symbol, period = task
    try:
        r = run_backtest(VARIANTS[variant](), SLICES[(symbol, period)], CAPITAL)
        pf = min(r.profit_factor, 10.0)
        return (variant, symbol, period, r.total_return_pct, r.benchmark_return_pct,
                r.max_drawdown_pct, r.num_trades, r.win_rate, pf)
    except Exception as e:
        print(f"ERR {variant} {symbol} {period}: {e}", file=sys.stderr)
        return None


def summarize(rows: list) -> dict:
    if not rows:
        return {"n": 0, "trades": 0, "prof": 0, "med_pf": float("nan"), "avg_ret": float("nan"),
                "avg_bh": float("nan"), "avg_dd": float("nan"), "wr": float("nan")}
    trades = sum(r[6] for r in rows)
    pfs = [r[8] for r in rows if r[6] >= 3]
    return {
        "n": len(rows), "trades": trades, "prof": sum(1 for r in rows if r[3] > 0),
        "med_pf": statistics.median(pfs) if pfs else float("nan"),
        "avg_ret": statistics.mean(r[3] for r in rows), "avg_bh": statistics.mean(r[4] for r in rows),
        "avg_dd": statistics.mean(r[5] for r in rows),
        "wr": (sum(r[7] * r[6] for r in rows) / trades) if trades else float("nan"),
    }


def fmt(s: dict) -> str:
    return (f"n={s['n']:2d} trades={s['trades']:4d} prof={s['prof']:2d}/{s['n']:<2d} "
            f"medPF={s['med_pf']:5.2f} ret={s['avg_ret']:+7.2f}% (B&H {s['avg_bh']:+7.2f}%) "
            f"DD={s['avg_dd']:6.2f}% WR={s['wr']:5.1f}%")


def evaluate(label: str = "INDIA") -> None:
    tasks = [(v, sym, per) for v in VARIANTS for (sym, per) in SLICES]
    with ProcessPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
        results = [r for r in pool.map(_run, tasks, chunksize=1) if r]

    print(f"\n=== {label} results: IS = before last {OOS_YEARS}y, OOS = last {OOS_YEARS}y; "
          f"capital {CAPITAL:,.0f}/symbol, {settings.max_position_size:.0%} position ===")
    candidates = []
    for v in VARIANTS:
        is_s = summarize([r for r in results if r[0] == v and r[2] == "IS"])
        oos_s = summarize([r for r in results if r[0] == v and r[2] == "OOS"])
        print(f"\n{v}\n  IS : {fmt(is_s)}\n  OOS: {fmt(oos_s)}")
        if is_s["avg_ret"] > 0 and oos_s["avg_ret"] > 0 and is_s["med_pf"] > 1 and oos_s["med_pf"] > 1 \
                and oos_s["trades"] >= 15:
            candidates.append((v, oos_s["avg_ret"], oos_s["med_pf"]))
    print("\n=== Positive in BOTH periods (avg return>0, median PF>1, OOS trades>=15) ===")
    for v, ret, pf in sorted(candidates, key=lambda c: -c[1]):
        print(f"  {v}: OOS avg ret {ret:+.2f}%, OOS median PF {pf:.2f}")
    if not candidates:
        print("  NONE")


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    start = (datetime.now() - timedelta(days=365 * 10 + 30)).strftime("%Y-%m-%d")
    fx = DataFetcher()
    for sym in settings.india_stocks:
        df = fx.fetch(sym, start_date=start, india=True)
        if df.empty:
            print(f"{sym}: no data, skipped")
            continue
        print(f"{sym}: {len(df)} bars {df.index[0].date()} -> {df.index[-1].date()}")
        split_slices(sym, df)
    evaluate()


if __name__ == "__main__":
    main()

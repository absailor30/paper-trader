"""Portfolio-level commodity tests the per-fund engine cannot express: cross-sectional rotation,
volatility-scaled Donchian, and ATR-channel (Keltner) breakout. Same three time periods as
commodities_search.py. Every rule, including the Donchian 55/20 baseline and equal-weight
buy-and-hold, runs through ONE simple simulator (channel exits only, no ATR stop/target) so they are
comparable with each other (not with the per-fund engine numbers). Signals use bar t, returns start t+1.
Needs real data: run via the commodities-portfolio-search workflow."""
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from loguru import logger

from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.strategy.indicators import atr

COST = settings.commission_rate + settings.slippage_rate  # per side, fraction of traded value
BASE_W = settings.max_position_size
MIN_ENTRIES = 15


def _state_machine(enter: pd.Series, exit_: pd.Series, size: pd.Series) -> pd.Series:
    out, held = np.zeros(len(enter)), 0.0
    for i, (e, x, s) in enumerate(zip(enter.values, exit_.values, size.values)):
        if held and x:
            held = 0.0
        elif not held and e and s > 0:
            held = s
        out[i] = held
    return pd.Series(out, index=enter.index)


def realized_vol(close: pd.DataFrame, n: int = 60) -> pd.DataFrame:
    return close.pct_change().rolling(n).std() * np.sqrt(252)


def donchian_weights(close, high, low, entry=55, exit_=20, vol_target=None) -> pd.DataFrame:
    vol = realized_vol(close)
    w = {}
    for s in close.columns:
        hh = high[s].rolling(entry).max().shift(1)
        ll = low[s].rolling(exit_).min().shift(1)
        if vol_target:
            size = (BASE_W * vol_target / vol[s]).clip(0.03, 0.20).fillna(0.0)
        else:
            size = pd.Series(BASE_W, index=close.index)
        w[s] = _state_machine(close[s] > hh, close[s] < ll, size)
    return pd.DataFrame(w)


def keltner_weights(close, high, low, span=20, atr_n=10, k=2.0) -> pd.DataFrame:
    w = {}
    for s in close.columns:
        mid = close[s].ewm(span=span, adjust=False).mean()
        upper = mid + k * atr(high[s], low[s], close[s], atr_n)
        w[s] = _state_machine(close[s] > upper, close[s] < mid, pd.Series(BASE_W, index=close.index))
    return pd.DataFrame(w)


def rotation_weights(close, top=3, lookback=126, trend=200) -> pd.DataFrame:
    """Month-end: hold the `top` funds by lookback return that are up AND above their SMA(trend)."""
    mom = close / close.shift(lookback) - 1
    ok = (mom > 0) & (close > close.rolling(trend).mean())
    month_end = close.index.to_series().groupby([close.index.year, close.index.month]).transform("max") == close.index.to_series()
    w = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for t in close.index[month_end.values]:
        pick = mom.loc[t].where(ok.loc[t]).dropna().nlargest(top).index
        w.loc[t] = 0.0
        w.loc[t, pick] = BASE_W
    return w.ffill().fillna(0.0)


def hold_weights(close) -> pd.DataFrame:
    return pd.DataFrame(BASE_W, index=close.index, columns=close.columns)


def simulate(close: pd.DataFrame, weights: pd.DataFrame, lo: int, hi: int) -> dict:
    """Account return over bars (lo, hi]: weights decided at bar t earn bar t+1's return."""
    r = close.pct_change().fillna(0.0)
    w = weights.shift(1).fillna(0.0)  # weight held DURING bar t = decided at t-1
    turnover = (w - w.shift(1).fillna(0.0)).abs().sum(axis=1)
    pnl = (w * r).sum(axis=1) - COST * turnover
    pnl = pnl.iloc[lo + 1:hi]
    equity = (1 + pnl).cumprod()
    entries = int(((w > 0) & (w.shift(1).fillna(0.0) == 0)).iloc[lo + 1:hi].sum().sum())
    return {
        "ret": float(equity.iloc[-1] - 1) * 100 if len(equity) else 0.0,
        "dd": float((equity / equity.cummax() - 1).min()) * 100 if len(equity) else 0.0,
        "entries": entries,
        "exposure": float(w.iloc[lo + 1:hi].sum(axis=1).mean()) * 100,
    }


def rules(close, high, low) -> dict:
    return {
        "Buy & hold, 12% each (all 8)": hold_weights(close),
        "Donchian 55/20 flat 12% (baseline)": donchian_weights(close, high, low),
        "Donchian 55/20 vol-scaled": donchian_weights(close, high, low, vol_target=0.15),
        "Keltner EMA20 +2xATR10": keltner_weights(close, high, low, 20, 10, 2.0),
        "Keltner EMA50 +3xATR20": keltner_weights(close, high, low, 50, 20, 3.0),
        "Rotation top3, 126d, SMA200": rotation_weights(close, 3, 126, 200),
        "Rotation top2, 126d, SMA200": rotation_weights(close, 2, 126, 200),
    }


def periods(n: int) -> dict:
    e = [0, n // 3, 2 * n // 3, n]
    return {f"P{k + 1}": (e[k], e[k + 1]) for k in range(3)}


def evaluate(close, high, low) -> dict:
    per = periods(len(close))
    return {name: {p: simulate(close, w, lo, hi) for p, (lo, hi) in per.items()}
            for name, w in rules(close, high, low).items()}


def is_robust(res: dict) -> bool:
    return all(v["ret"] > 0 and v["entries"] >= MIN_ENTRIES for v in res.values())


def report(results: dict, close: pd.DataFrame) -> None:
    per = periods(len(close))
    print("Periods: " + "  ".join(f"{p} {close.index[lo].date()}->{close.index[hi - 1].date()}" for p, (lo, hi) in per.items()))
    print("Account return % (maxDD %, entries, avg exposure %). ROBUST = positive in all 3 with >= 15 entries each.\n")
    for name, res in results.items():
        cells = " | ".join(f"{res[p]['ret']:+6.1f}% ({res[p]['dd']:5.1f}, {res[p]['entries']:3d}, {res[p]['exposure']:4.0f})" for p in per)
        print(f"{name:36s} {cells}  {'ROBUST' if is_robust(res) else ''}")
    print("\nReturn per 1% of average exposure (is the rule better than just holding the same exposure?):")
    for name, res in results.items():
        print(f"{name:36s} " + " | ".join(f"{res[p]['ret'] / max(res[p]['exposure'], 1e-9):+6.3f}" for p in per))


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    start = (datetime.now() - timedelta(days=365 * 10 + 30)).strftime("%Y-%m-%d")
    fx, frames = DataFetcher(), {}
    for sym in settings.commodities:
        df = fx.fetch(sym, start_date=start)
        if df.empty:
            print(f"{sym}: no data, skipped")
            continue
        print(f"{sym}: {len(df)} bars {df.index[0].date()} -> {df.index[-1].date()}")
        frames[sym] = df
    close = pd.DataFrame({s: d["close"] for s, d in frames.items()}).dropna()
    high = pd.DataFrame({s: d["high"] for s, d in frames.items()}).reindex(close.index)
    low = pd.DataFrame({s: d["low"] for s, d in frames.items()}).reindex(close.index)
    print(f"Common history: {len(close)} bars {close.index[0].date()} -> {close.index[-1].date()}\n")
    report(evaluate(close, high, low), close)


if __name__ == "__main__":
    main()

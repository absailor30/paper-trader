"""Does long/short trend following work on futures-style markets? Five groups (US index futures, India index proxy, commodity
futures, crypto via spot proxy, forex), three time periods each, same simulator as commodities_portfolio_search.py.
Costs 0.05% per side (futures/FX are cheaper than stocks; stated, not tuned). Robust = positive account return in ALL THREE
periods with >= 15 entries each. Caveats printed at the end. Needs real data: run via the futures-search workflow."""
import sys
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

import scripts.commodities_portfolio_search as cps
from paper_trader.config import settings
from paper_trader.data.binance_fetcher import BinanceFetcher
from paper_trader.data.fetcher import DataFetcher
from paper_trader.strategy.long_short_trend import ls_states

COST = 0.0005
VARIANTS = [("L/S Donchian 20/10", 20, 10, True), ("L/S Donchian 55/20", 55, 20, True),
            ("L/S Donchian 100/50", 100, 50, True), ("Long-only 55/20 (baseline)", 55, 20, False)]


def groups() -> dict:
    return {"US index futures": ("yf", settings.futures_us), "India index (proxy)": ("yf", settings.futures_india),
            "Commodity futures": ("yf", settings.futures_commodities), "Crypto (spot proxy)": ("bn", settings.futures_crypto),
            "Forex": ("yf", settings.forex_pairs)}


def frames_to_panels(frames: dict):
    close = pd.DataFrame({s: d["close"] for s, d in frames.items()}).sort_index().ffill(limit=5)
    return close


def weights_for(frames: dict, index, entry, exit_, allow_short) -> pd.DataFrame:
    w = {}
    for s, d in frames.items():
        st = ls_states(d["close"], d["high"], d["low"], entry, exit_, allow_short)
        w[s] = st.reindex(index).ffill().fillna(0.0) * cps.BASE_W
    return pd.DataFrame(w)


def evaluate_group(frames: dict) -> dict:
    close = frames_to_panels(frames)
    per = cps.periods(len(close))
    out = {"Buy & hold 12% each": {p: cps.simulate(close, cps.hold_weights(close), lo, hi, COST) for p, (lo, hi) in per.items()}}
    for name, entry, exit_, shorts in VARIANTS:
        w = weights_for(frames, close.index, entry, exit_, shorts)
        out[name] = {p: cps.simulate(close, w, lo, hi, COST) for p, (lo, hi) in per.items()}
    return out, close


def report_group(title: str, frames: dict) -> None:
    res, close = evaluate_group(frames)
    per = cps.periods(len(close))
    print(f"\n=== {title}: {len(frames)} instruments {list(frames)}; {close.index[0].date()} -> {close.index[-1].date()} ===")
    print("Periods: " + "  ".join(f"{p} {close.index[lo].date()}->{close.index[hi - 1].date()}" for p, (lo, hi) in per.items()))
    for name, r in res.items():
        cells = " | ".join(f"{r[p]['ret']:+6.1f}% (dd {r[p]['dd']:5.1f}, {r[p]['entries']:3d} ent, {r[p]['exposure']:3.0f}% exp)" for p in per)
        print(f"{name:28s} {cells}  {'ROBUST' if cps.is_robust(r) and not name.startswith('Buy') else ''}")


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    start = (datetime.now() - timedelta(days=365 * 10 + 30)).strftime("%Y-%m-%d")
    yf, bn = DataFetcher(), BinanceFetcher(market="spot")
    for title, (src, symbols) in groups().items():
        frames = {}
        for sym in symbols:
            df = (yf.fetch(sym, start_date=start) if src == "yf" else bn.fetch(sym, start_date=start))
            if df is None or df.empty:
                print(f"{title}: {sym} no data, skipped")
                continue
            frames[sym] = df
        if len(frames) >= 1:
            report_group(title, frames)
    print("\nCaveats: free continuous futures (=F) are unadjusted front-month series with small roll jumps; India uses the index "
          "(no free NSE futures); crypto uses spot as a perpetual proxy (no funding costs); FX ignores swap/carry; flat 12% notional per "
          "instrument, 0.05%/side costs; 4 variants x 5 groups x 3 periods = multiple-comparison risk.")


if __name__ == "__main__":
    main()

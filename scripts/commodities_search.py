"""Commodities-only test: the 4 configured funds (GLD, SLV, USO, UNG) plus 4 broad commodity funds
(DBC, DBA, CPER, PPLT) added only to get enough trades to mean something. Same in-sample vs last-3-years
scoring as the India and crypto searches (scripts/india_strategy_search.py). Needs real market data,
so run via the commodities-search workflow, not the sandbox."""
import sys
from datetime import datetime, timedelta

from loguru import logger

import scripts.india_strategy_search as base
from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy
from paper_trader.strategy.mean_reversion import MeanReversionStrategy
from paper_trader.strategy.momentum_trend import MomentumTrend

EXTRA = ["DBC", "DBA", "CPER", "PPLT"]


def variants() -> dict:
    v = {
        "Donchian_20_10_tf100 (US live rule)": lambda: DonchianBreakoutStrategy(20, 10, 100, name="D20_10_tf100"),
        "Donchian_20_10_tfnone": lambda: DonchianBreakoutStrategy(20, 10, None, name="D20_10_none"),
        "Donchian_55_20_tfnone": lambda: DonchianBreakoutStrategy(55, 20, None, name="D55_20_none"),
        "Donchian_10_5_tfnone": lambda: DonchianBreakoutStrategy(10, 5, None, name="D10_5_none"),
        "Momentum_126d_ret10_sma50": lambda: MomentumTrend(126, 0.10, 50),
        "Mean_Reversion_RSI": MeanReversionStrategy,
    }
    return v


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    base.VARIANTS.clear()
    base.VARIANTS.update(variants())
    start = (datetime.now() - timedelta(days=365 * 10 + 30)).strftime("%Y-%m-%d")
    fx = DataFetcher()
    for sym in list(settings.commodities) + EXTRA:
        df = fx.fetch(sym, start_date=start)
        if df.empty:
            print(f"{sym}: no data, skipped")
            continue
        print(f"{sym}: {len(df)} bars {df.index[0].date()} -> {df.index[-1].date()}"
              f"{'' if sym in settings.commodities else '  (added for sample size)'}")
        base.split_slices(sym, df)
    results = base.evaluate("COMMODITIES")
    print("\n=== Per-symbol, last 3 years (return % / trades), by variant ===")
    for v in base.VARIANTS:
        rows = sorted((r for r in results if r[0] == v and r[2] == "OOS"), key=lambda r: r[1])
        print(f"{v}: " + "  ".join(f"{r[1]} {r[3]:+.1f}%/{r[6]}t" for r in rows))
    print("\n=== Buy-and-hold reference, same last 3 years: see 'B&H' column above (avg per symbol) ===")


if __name__ == "__main__":
    main()

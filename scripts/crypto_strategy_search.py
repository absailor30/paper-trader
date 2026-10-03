"""Backtest faster-entry Donchian variants on the large-cap crypto universe, in-sample vs last 3 years.

Reuses the India search's engine/scoring (scripts/india_strategy_search.py).
The live crypto strategy is Donchian 55/20, no trend filter. Needs real
market data, so run via the crypto-strategy-search workflow, not the sandbox.
"""
import sys
from datetime import datetime, timedelta

from loguru import logger

import scripts.india_strategy_search as base
from paper_trader.config import settings
from paper_trader.data.binance_fetcher import BinanceFetcher
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy


def crypto_variants() -> dict:
    v = {}
    for entry, exit_, tf in ((55, 20, None), (40, 20, None), (30, 15, None), (20, 10, None), (10, 5, None),
                             (30, 15, 100), (20, 10, 100)):
        name = f"Donchian_{entry}_{exit_}_tf{tf or 'none'}" + ("_LIVE" if (entry, exit_, tf) == (55, 20, None) else "")
        v[name] = (lambda e=entry, x=exit_, t=tf, n=name: DonchianBreakoutStrategy(e, x, t, name=n))
    return v


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    base.VARIANTS.clear()
    base.VARIANTS.update(crypto_variants())
    base.CAPITAL = settings.crypto_capital
    start = (datetime.now() - timedelta(days=365 * 10)).strftime("%Y-%m-%d")
    fetcher = BinanceFetcher(market="spot")
    for sym in settings.crypto_pairs:
        df = fetcher.fetch(sym, start_date=start)
        if df.empty:
            print(f"{sym}: no data, skipped")
            continue
        print(f"{sym}: {len(df)} bars {df.index[0].date()} -> {df.index[-1].date()}")
        base.split_slices(sym, df)
    base.evaluate("CRYPTO")


if __name__ == "__main__":
    main()

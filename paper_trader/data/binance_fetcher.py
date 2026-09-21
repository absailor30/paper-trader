"""
Binance market data fetcher (public REST endpoints, no API key needed for
OHLCV). Covers spot (api.binance.com) and USD-M perpetual futures
(fapi.binance.com) -- the two markets the crypto strategies/backtests
target. COIN-M futures are out of scope (niche product, different margin
math); add a third base URL here if that's ever needed.

Returns OHLCV with the same lowercase-column/DatetimeIndex shape as
DataFetcher (paper_trader/data/fetcher.py), so every downstream strategy
and the backtest engine work unmodified against crypto data.
"""
from typing import Dict, List, Optional

import pandas as pd
import requests
from loguru import logger

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")

BASE_URLS = {
    "spot": "https://api.binance.com",
    "futures": "https://fapi.binance.com",
}
# Public, read-only market-data mirror Binance runs specifically for callers
# geo-blocked (HTTP 451) on api.binance.com -- confirmed the live failure
# mode on both this sandbox and GitHub Actions runners (see CHECKPOINT.md,
# "Crypto fetches 451 from GitHub Actions runners"). Spot-only; there is no
# equivalent mirror for the futures klines endpoint.
FALLBACK_BASE_URLS = {
    "spot": "https://data-api.binance.vision",
}
KLINES_PATH = {
    "spot": "/api/v3/klines",
    "futures": "/fapi/v1/klines",
}
MAX_LIMIT = 1000  # Binance klines endpoint page size cap


def _to_millis(date_str: str) -> int:
    return int(pd.Timestamp(date_str, tz="UTC").timestamp() * 1000)


def normalize(raw: List[list], symbol: str) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(
        raw,
        columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ],
    )
    df["date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in REQUIRED_COLUMNS:
        df[col] = df[col].astype(float)
    df = df.set_index("date")[list(REQUIRED_COLUMNS)]
    df["symbol"] = symbol
    return df


class BinanceFetcher:
    """
    Usage:
        BinanceFetcher().fetch("BTCUSDT", start_date="2023-01-01", interval="1d")
        BinanceFetcher(market="futures").fetch("BTCUSDT", start_date="2023-01-01")
    """

    def __init__(self, market: str = "spot", session: Optional[requests.Session] = None):
        if market not in BASE_URLS:
            raise ValueError(f"market must be one of {list(BASE_URLS)}, got {market!r}")
        self.market = market
        self.session = session or requests.Session()

    def fetch(
        self,
        symbol: str,
        start_date: str,
        end_date: Optional[str] = None,
        interval: str = "1d",
    ) -> pd.DataFrame:
        candidates = [BASE_URLS[self.market]]
        if self.market in FALLBACK_BASE_URLS:
            candidates.append(FALLBACK_BASE_URLS[self.market])

        last_error: Optional[Exception] = None
        for i, base_url in enumerate(candidates):
            try:
                df = self._fetch_from(base_url, symbol, start_date, end_date, interval)
                if i > 0:
                    logger.info(f"{symbol}: fetched via fallback host {base_url} after primary was blocked")
                return df
            except Exception as e:
                last_error = e
                logger.warning(f"{symbol}: {base_url} failed ({e}), {'trying fallback' if i + 1 < len(candidates) else 'no more hosts to try'}")

        logger.error(f"Failed to fetch {self.market} data for {symbol}: {last_error}")
        return pd.DataFrame()

    def _fetch_from(
        self,
        base_url: str,
        symbol: str,
        start_date: str,
        end_date: Optional[str],
        interval: str,
    ) -> pd.DataFrame:
        url = base_url + KLINES_PATH[self.market]
        start_ms = _to_millis(start_date)
        end_ms = _to_millis(end_date) if end_date else int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)

        all_rows: List[list] = []
        cursor = start_ms
        while cursor < end_ms:
            resp = self.session.get(
                url,
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": MAX_LIMIT,
                },
                timeout=15,
            )
            resp.raise_for_status()
            page = resp.json()
            if not page:
                break
            all_rows.extend(page)
            last_open_time = page[-1][0]
            if len(page) < MAX_LIMIT or last_open_time <= cursor:
                break
            cursor = last_open_time + 1
        return normalize(all_rows, symbol)

    def fetch_many(
        self,
        symbols: List[str],
        start_date: str,
        end_date: Optional[str] = None,
        interval: str = "1d",
    ) -> Dict[str, pd.DataFrame]:
        results = {}
        for symbol in symbols:
            df = self.fetch(symbol, start_date, end_date, interval=interval)
            if not df.empty:
                results[symbol] = df
            else:
                logger.warning(f"No data for {symbol}")
        return results

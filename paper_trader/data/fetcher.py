"""
Market data fetcher (yfinance-backed). Returns OHLCV with lowercase
columns and a DatetimeIndex, the format every downstream module expects.
"""
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf
from loguru import logger

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def normalize(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).lower() for c in df.columns]

    keep = [c for c in REQUIRED_COLUMNS if c in df.columns]
    df = df[keep].dropna(subset=["close"])
    df["symbol"] = symbol
    df.index.name = "date"
    return df


class DataFetcher:
    def fetch(
        self,
        symbol: str,
        start_date: str,
        end_date: Optional[str] = None,
        india: bool = False,
    ) -> pd.DataFrame:
        ticker = symbol if not india or symbol.endswith((".NS", ".BO")) else f"{symbol}.NS"
        try:
            raw = yf.download(ticker, start=start_date, end=end_date, progress=False, auto_adjust=True)
            return normalize(raw, symbol)
        except Exception as e:
            logger.error(f"Failed to fetch data for {symbol}: {e}")
            return pd.DataFrame()

    def fetch_many(
        self,
        symbols: List[str],
        start_date: str,
        end_date: Optional[str] = None,
        india: bool = False,
    ) -> Dict[str, pd.DataFrame]:
        results = {}
        for symbol in symbols:
            df = self.fetch(symbol, start_date, end_date, india=india)
            if not df.empty:
                results[symbol] = df
            else:
                logger.warning(f"No data for {symbol}")
        return results

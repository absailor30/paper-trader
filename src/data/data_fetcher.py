"""
Market data fetcher (yfinance-backed).

Provides OHLCV history for US and Indian equities in the lowercase-column,
DatetimeIndex format expected by src/strategies/* and src/execution/backtester.py.
"""
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf
from loguru import logger


class DataFetcher:
    """Fetches historical OHLCV data for US and Indian equities via yfinance."""

    def _normalize(self, raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()

        df = raw.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [str(c).lower() for c in df.columns]

        keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
        df = df[keep].dropna(subset=["close"])
        df["symbol"] = symbol
        df.index.name = "date"
        return df

    def fetch_us_stock_data(
        self,
        symbol: str,
        start_date: str,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        try:
            raw = yf.download(
                symbol,
                start=start_date,
                end=end_date,
                progress=False,
                auto_adjust=True,
            )
            return self._normalize(raw, symbol)
        except Exception as e:
            logger.error(f"Failed to fetch US data for {symbol}: {e}")
            return pd.DataFrame()

    def fetch_india_stock_data(
        self,
        symbol: str,
        start_date: str,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        ticker = symbol if symbol.endswith((".NS", ".BO")) else f"{symbol}.NS"
        try:
            raw = yf.download(
                ticker,
                start=start_date,
                end=end_date,
                progress=False,
                auto_adjust=True,
            )
            # Symbol is recorded without the exchange suffix so it matches
            # the tickers used elsewhere (config.india_stocks, portfolio keys).
            return self._normalize(raw, symbol)
        except Exception as e:
            logger.error(f"Failed to fetch India data for {symbol}: {e}")
            return pd.DataFrame()

    def fetch_multiple_stocks(
        self,
        symbols: List[str],
        market: str,
        start_date: str,
        end_date: Optional[str] = None,
    ) -> Dict[str, pd.DataFrame]:
        fetch_one = self.fetch_us_stock_data if market == "US" else self.fetch_india_stock_data

        results: Dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            df = fetch_one(symbol, start_date, end_date)
            if not df.empty:
                results[symbol] = df
            else:
                logger.warning(f"No data returned for {symbol} ({market})")
        return results

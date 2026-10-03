from unittest.mock import patch

import pandas as pd

from paper_trader.data.fetcher import DataFetcher, normalize


def _fake_yf_frame():
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {"Open": [1.0, 2.0, 3.0], "High": [1.1, 2.1, 3.1], "Low": [0.9, 1.9, 2.9],
         "Close": [1.0, 2.0, 3.0], "Volume": [100, 200, 300]},
        index=dates,
    )


def test_fetch_defaults_to_daily_interval():
    with patch("paper_trader.data.fetcher.yf.download", return_value=_fake_yf_frame()) as mock_dl:
        DataFetcher().fetch("AAPL", start_date="2024-01-01")
        assert mock_dl.call_args.kwargs["interval"] == "1d"


def test_fetch_passes_through_custom_interval():
    with patch("paper_trader.data.fetcher.yf.download", return_value=_fake_yf_frame()) as mock_dl:
        DataFetcher().fetch("AAPL", start_date="2024-01-01", interval="1h")
        assert mock_dl.call_args.kwargs["interval"] == "1h"


def test_fetch_many_passes_through_interval():
    with patch("paper_trader.data.fetcher.yf.download", return_value=_fake_yf_frame()) as mock_dl:
        DataFetcher().fetch_many(["AAPL"], start_date="2024-01-01", interval="1h")
        assert mock_dl.call_args.kwargs["interval"] == "1h"


def test_normalize_empty_input_returns_empty_frame():
    assert normalize(pd.DataFrame(), "AAPL").empty

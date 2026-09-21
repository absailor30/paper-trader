import pandas as pd

from paper_trader.data.binance_fetcher import BinanceFetcher, normalize


def _kline_row(open_time_ms, price):
    return [
        open_time_ms, str(price), str(price * 1.01), str(price * 0.99), str(price),
        "1000.0", open_time_ms + 86_399_999, "1000000.0", 500,
        "500.0", "500000.0", "0",
    ]


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    """Serves one page of klines then an empty page, so fetch() stops
    without needing real pagination across the full date range."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, params))
        if self.calls == [self.calls[0]]:
            return FakeResponse(self.rows)
        return FakeResponse([])


def test_normalize_produces_expected_columns_and_index():
    rows = [_kline_row(1700000000000, 100.0), _kline_row(1700086400000, 105.0)]
    df = normalize(rows, "BTCUSDT")

    assert list(df.columns) == ["open", "high", "low", "close", "volume", "symbol"]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df["close"].tolist() == [100.0, 105.0]
    assert (df["symbol"] == "BTCUSDT").all()


def test_normalize_empty_input_returns_empty_frame():
    assert normalize([], "BTCUSDT").empty


def test_fetch_spot_hits_spot_base_url_and_returns_parsed_frame():
    rows = [_kline_row(1700000000000, 30000.0)]
    session = FakeSession(rows)
    fetcher = BinanceFetcher(market="spot", session=session)

    df = fetcher.fetch("BTCUSDT", start_date="2023-11-14", end_date="2023-11-15")

    assert not df.empty
    assert df["close"].iloc[0] == 30000.0
    url, params = session.calls[0]
    assert url == "https://api.binance.com/api/v3/klines"
    assert params["symbol"] == "BTCUSDT"


def test_fetch_futures_hits_futures_base_url():
    session = FakeSession([_kline_row(1700000000000, 30000.0)])
    fetcher = BinanceFetcher(market="futures", session=session)

    fetcher.fetch("BTCUSDT", start_date="2023-11-14", end_date="2023-11-15")

    url, _ = session.calls[0]
    assert url == "https://fapi.binance.com/fapi/v1/klines"


def test_invalid_market_raises():
    import pytest
    with pytest.raises(ValueError):
        BinanceFetcher(market="options")


def test_fetch_returns_empty_frame_on_request_exception():
    class BlowUpSession:
        def get(self, *a, **k):
            raise ConnectionError("no network")

    fetcher = BinanceFetcher(market="spot", session=BlowUpSession())
    df = fetcher.fetch("BTCUSDT", start_date="2023-01-01")
    assert df.empty


def test_fetch_spot_falls_back_to_data_vision_host_when_primary_blocked():
    class GeoBlockedThenOkSession:
        """Simulates api.binance.com returning 451 (geo-block), then
        data-api.binance.vision succeeding -- the real failure mode hit on
        both this sandbox and GitHub Actions runners."""

        def __init__(self, rows):
            self.rows = rows
            self.calls = []

        def get(self, url, params, timeout):
            self.calls.append((url, params))
            if url.startswith("https://api.binance.com"):
                raise Exception("451 Client Error: for url: " + url)
            if len(self.calls) == 2:
                return FakeResponse(self.rows)
            return FakeResponse([])

    rows = [_kline_row(1700000000000, 30000.0)]
    session = GeoBlockedThenOkSession(rows)
    fetcher = BinanceFetcher(market="spot", session=session)

    df = fetcher.fetch("BTCUSDT", start_date="2023-11-14", end_date="2023-11-15")

    assert not df.empty
    assert df["close"].iloc[0] == 30000.0
    assert session.calls[0][0] == "https://api.binance.com/api/v3/klines"
    assert session.calls[1][0] == "https://data-api.binance.vision/api/v3/klines"


def test_fetch_futures_has_no_fallback_and_returns_empty_on_block():
    class AlwaysBlockedSession:
        def get(self, *a, **k):
            raise Exception("451 Client Error")

    fetcher = BinanceFetcher(market="futures", session=AlwaysBlockedSession())
    df = fetcher.fetch("BTCUSDT", start_date="2023-11-14")
    assert df.empty


def test_fetch_many_skips_symbols_with_no_data():
    class EmptySession:
        def get(self, *a, **k):
            return FakeResponse([])

    fetcher = BinanceFetcher(market="spot", session=EmptySession())
    results = fetcher.fetch_many(["BTCUSDT", "ETHUSDT"], start_date="2023-01-01")
    assert results == {}

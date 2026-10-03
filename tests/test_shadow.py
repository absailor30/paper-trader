from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import paper_trader.persistence.state_store as state_store
import paper_trader.shadow as shadow
from paper_trader.config import settings
from paper_trader.shadow import STATE_KEY, CryptoShadowRun, IndiaShadowRun
from tests.conftest import _make_ohlcv


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'shadow.db'}")
    state_store.Base.metadata.create_all(engine)
    monkeypatch.setattr(state_store, "_engine", engine)
    monkeypatch.setattr(state_store, "_Session", sessionmaker(bind=engine))
    monkeypatch.setattr(settings, "india_stocks", ["RELIANCE"])
    monkeypatch.setattr(settings, "crypto_pairs", ["BTCUSDT"])
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")


class FakeFetcher:
    def __init__(self, df):
        self.df = df

    def fetch_many(self, symbols, start_date, end_date=None, india=False, interval="1d"):
        assert india is True
        return {s: self.df for s in symbols}


def _rising():
    return _make_ohlcv(np.linspace(100, 160, 260), "RELIANCE")


def _rising_then_crash():
    close = np.concatenate([np.linspace(100, 160, 260), np.linspace(160, 110, 15)])
    return _make_ohlcv(close, "RELIANCE")


def test_opens_hypothetical_position_on_signal_and_never_executes():
    result = IndiaShadowRun(fetcher=FakeFetcher(_rising())).run()
    assert result["executed"] is False
    assert [o["symbol"] for o in result["opened_today"]] == ["RELIANCE"]
    assert "RELIANCE" in result["open_positions"]
    # live portfolio state must be untouched
    assert state_store.load_state("india_portfolio") is None
    assert state_store.load_state(STATE_KEY) is not None


def test_same_bar_rerun_is_idempotent():
    df = _rising()
    IndiaShadowRun(fetcher=FakeFetcher(df)).run()
    second = IndiaShadowRun(fetcher=FakeFetcher(df)).run()
    assert second["opened_today"] == [] and second["closed_today"] == []
    assert list(second["open_positions"]) == ["RELIANCE"]


def test_closes_on_sma_break_with_net_return_and_no_same_bar_reentry():
    IndiaShadowRun(fetcher=FakeFetcher(_rising())).run()
    result = IndiaShadowRun(fetcher=FakeFetcher(_rising_then_crash())).run()
    assert [t["symbol"] for t in result["closed_today"]] == ["RELIANCE"]
    assert result["open_positions"] == {}
    assert result["opened_today"] == []
    assert result["closed_trades"] == 1
    trade = result["closed_today"][0]
    # exited well below entry: net return must be negative and include costs
    assert trade["net_return_pct"] < 0
    gross = (trade["exit_price"] / trade["entry_price"] - 1) * 100
    assert trade["net_return_pct"] < gross


def test_no_signal_leaves_state_empty():
    flat = _make_ohlcv(np.full(260, 100.0), "RELIANCE")
    result = IndiaShadowRun(fetcher=FakeFetcher(flat)).run()
    assert result["opened_today"] == [] and result["open_positions"] == {}
    assert result["win_rate_pct"] is None


def test_sends_shadow_notification_on_entry():
    with patch.object(shadow, "notify_shadow") as mock_notify:
        IndiaShadowRun(fetcher=FakeFetcher(_rising())).run()
    mock_notify.assert_called_once()
    assert mock_notify.call_args[0][1:3] == ("BUY", "RELIANCE")


def test_net_return_includes_costs():
    assert shadow._net_return_pct(100.0, 100.0) < 0


class FakeCryptoFetcher:
    def __init__(self, df):
        self.df = df

    def fetch_many(self, symbols, start_date, end_date=None, interval="1d"):
        return {s: self.df for s in symbols}


def _crypto_breakout(end=None):
    flat = 100 - np.linspace(0, 2, 150)
    rally = flat[-1] + np.linspace(0, 40, 40)
    df = _make_ohlcv(np.concatenate([flat, rally]), "BTCUSDT")
    if end is not None:
        df.index = pd.date_range(end=end, periods=len(df), freq="D", tz="UTC")
    return df


def test_crypto_shadow_opens_on_breakout_and_never_touches_live_state():
    run = CryptoShadowRun(fetcher=FakeCryptoFetcher(_crypto_breakout()))
    result = run.run()
    assert result["executed"] is False
    assert [o["symbol"] for o in result["opened_today"]] == ["BTCUSDT"]
    assert state_store.load_state("crypto_portfolio") is None
    assert state_store.load_state(run.state_key) is not None
    assert run.state_key == "crypto_shadow_Donchian_20_10_shadow"


def test_crypto_shadow_drops_in_progress_candle():
    today = pd.Timestamp.now(tz="UTC").normalize()
    result = CryptoShadowRun(fetcher=FakeCryptoFetcher(_crypto_breakout(end=today))).run()
    entry = result["open_positions"]["BTCUSDT"]["entry_date"]
    assert entry == str((today - pd.Timedelta(days=1)).date())


def test_crypto_shadow_same_bar_rerun_is_idempotent():
    df = _crypto_breakout()
    CryptoShadowRun(fetcher=FakeCryptoFetcher(df)).run()
    second = CryptoShadowRun(fetcher=FakeCryptoFetcher(df)).run()
    assert second["opened_today"] == [] and list(second["open_positions"]) == ["BTCUSDT"]


def test_india_and_crypto_shadow_ledgers_are_separate():
    IndiaShadowRun(fetcher=FakeFetcher(_rising())).run()
    CryptoShadowRun(fetcher=FakeCryptoFetcher(_crypto_breakout())).run()
    assert state_store.load_state(STATE_KEY)["open"].keys() == {"RELIANCE"}
    assert state_store.load_state("crypto_shadow_Donchian_20_10_shadow")["open"].keys() == {"BTCUSDT"}

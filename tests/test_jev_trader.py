from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import paper_trader.jev_trader as jt
import paper_trader.orchestrator as orchestrator
import paper_trader.persistence.state_store as state_store
from paper_trader.config import settings
from tests.conftest import _make_ohlcv


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'jt.db'}")
    state_store.Base.metadata.create_all(engine)
    monkeypatch.setattr(state_store, "_engine", engine)
    monkeypatch.setattr(state_store, "_Session", sessionmaker(bind=engine))
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")
    monkeypatch.setattr(settings, "auto_execute", True)
    monkeypatch.setattr(settings, "typesafe_api_key", "k")
    monkeypatch.setitem(orchestrator.MARKETS, "US", {"symbols": ["AAA", "BBB", "CCC"], "capital": 1000.0, "india": False})
    monkeypatch.setitem(orchestrator.MARKETS, "INDIA", {"symbols": ["RELIANCE"], "capital": 10_000.0, "india": True})


class FakeNoul:
    def __init__(self, instructions):
        self.instructions = instructions


class FakeClient:
    """buy_p / sell_p: dict symbol -> probability (default 0.1); a None value simulates a failed call."""

    def __init__(self, buy_p=None, sell_p=None):
        self.buy_p, self.sell_p, self.states = buy_p or {}, sell_p or {}, []

    def system_one(self, state, questions):
        q = questions["followthrough"].instructions
        self.states.append(state)
        symbol = state.split("symbol: ")[1].split(";")[0]
        table = self.sell_p if q == jt.SELL_QUESTION else self.buy_p
        p = table.get(symbol, 0.1)
        if p is None:
            raise RuntimeError("jev down")
        return SimpleNamespace(answers={"followthrough": SimpleNamespace(noul=p)})


class FakeFetcher:
    def __init__(self, dfs):
        self.dfs = dfs

    def fetch_many(self, symbols, start_date, end_date=None, india=False, interval="1d"):
        return {s: self.dfs[s] for s in symbols if s in self.dfs}


def _df(symbol, n=260, start=100.0, end=130.0):
    return _make_ohlcv(np.linspace(start, end, n), symbol)


def _trader(client, dfs):
    return jt.JevTrader(client=client, noul_cls=FakeNoul, fetcher=FakeFetcher(dfs))


def test_disabled_without_key_does_nothing(monkeypatch):
    monkeypatch.setattr(settings, "typesafe_api_key", "")
    out = jt.JevTrader(fetcher=FakeFetcher({})).run_market("US")
    assert "disabled" in out and state_store.load_state("jev_us_portfolio") is None


def test_buys_only_above_threshold_and_never_touches_live_accounts():
    dfs = {s: _df(s) for s in ("AAA", "BBB", "CCC")}
    out = _trader(FakeClient(buy_p={"AAA": 0.9, "BBB": 0.5}), dfs).run_market("US")
    assert out["open_positions"] == ["AAA"]
    assert [a["action"] for a in out["actions"]] == ["EXECUTED"]
    assert state_store.load_state("jev_us_portfolio") is not None
    assert state_store.load_state("us_portfolio") is None  # live rule-based account untouched


def test_highest_conviction_first_and_max_positions(monkeypatch):
    monkeypatch.setattr(settings, "jev_max_positions", 2)
    dfs = {s: _df(s) for s in ("AAA", "BBB", "CCC")}
    out = _trader(FakeClient(buy_p={"AAA": 0.7, "BBB": 0.95, "CCC": 0.8}), dfs).run_market("US")
    assert out["open_positions"] == ["BBB", "CCC"]


def test_failed_jev_answer_means_hold():
    dfs = {s: _df(s) for s in ("AAA", "BBB", "CCC")}
    out = _trader(FakeClient(buy_p={"AAA": None, "BBB": None, "CCC": None}), dfs).run_market("US")
    assert out["actions"] == [] and out["failed_asks"] == 3 and out["open_positions"] == []


def test_sells_when_jev_says_close_and_records_track_record_for_next_question():
    dfs = {s: _df(s) for s in ("AAA", "BBB", "CCC")}
    _trader(FakeClient(buy_p={"AAA": 0.9}), dfs).run_market("US")
    client = FakeClient(sell_p={"AAA": 0.8})
    # next bar so idempotent client_order_ids differ
    dfs["AAA"] = _make_ohlcv(np.linspace(100, 131, 261), "AAA")
    out = _trader(client, dfs).run_market("US")
    assert out["open_positions"] == [] and out["actions"][0]["side"] == "SELL"
    # a later question must now carry the closed trade
    client2 = FakeClient(buy_p={"AAA": 0.1})
    dfs["AAA"] = _make_ohlcv(np.linspace(100, 132, 262), "AAA")
    _trader(client2, dfs).run_market("US")
    assert any("1 closed trades" in s for s in client2.states)


def test_holds_when_jev_says_keep():
    dfs = {s: _df(s) for s in ("AAA", "BBB", "CCC")}
    _trader(FakeClient(buy_p={"AAA": 0.9}), dfs).run_market("US")
    dfs["AAA"] = _make_ohlcv(np.linspace(100, 131, 261), "AAA")
    out = _trader(FakeClient(sell_p={"AAA": 0.2}), dfs).run_market("US")
    assert out["open_positions"] == ["AAA"] and out["actions"] == []


def test_hard_stop_sells_without_asking_jev():
    dfs = {s: _df(s) for s in ("AAA", "BBB", "CCC")}
    _trader(FakeClient(buy_p={"AAA": 0.9}), dfs).run_market("US")
    crash = np.concatenate([np.linspace(100, 130, 260), [20.0]])
    dfs["AAA"] = _make_ohlcv(crash, "AAA")
    out = _trader(FakeClient(sell_p={"AAA": 0.0}), dfs).run_market("US")
    assert out["open_positions"] == [] and "guardrail" in out["actions"][0]["reasoning"]


def test_propose_only_places_no_orders(monkeypatch):
    monkeypatch.setattr(settings, "auto_execute", False)
    dfs = {s: _df(s) for s in ("AAA", "BBB", "CCC")}
    out = _trader(FakeClient(buy_p={"AAA": 0.9}), dfs).run_market("US")
    assert out["open_positions"] == [] and out["actions"][0]["action"] == "PROPOSED_BUY"


def test_same_bar_rerun_is_idempotent():
    dfs = {s: _df(s) for s in ("AAA", "BBB", "CCC")}
    _trader(FakeClient(buy_p={"AAA": 0.9}), dfs).run_market("US")
    again = _trader(FakeClient(buy_p={"AAA": 0.9}), dfs).run_market("US")
    assert again["open_positions"] == ["AAA"] and again["actions"] == []


def test_dust_cash_is_not_traded():
    dfs = {s: _df(s) for s in ("AAA", "BBB", "CCC")}
    _trader(FakeClient(buy_p={"AAA": 0.9}), dfs).run_market("US")
    saved = state_store.load_state("jev_us_portfolio")
    saved["capital"] = 0.01  # nearly out of cash, rest sits in the AAA position
    state_store.save_state("jev_us_portfolio", saved)
    out = _trader(FakeClient(buy_p={"BBB": 0.99}), dfs).run_market("US")
    assert "BBB" not in out["open_positions"]


def test_india_buys_whole_shares_only():
    dfs = {"RELIANCE": _df("RELIANCE", start=100, end=160)}
    out = _trader(FakeClient(buy_p={"RELIANCE": 0.9}), dfs).run_market("INDIA")
    qty = out["actions"][0]["quantity"]
    assert qty == int(qty) and qty >= 1


def test_circuit_breaker_blocks_new_buys(monkeypatch):
    dfs = {s: _df(s) for s in ("AAA", "BBB", "CCC")}
    _trader(FakeClient(buy_p={"AAA": 0.9}), dfs).run_market("US")
    monkeypatch.setattr(settings, "max_drawdown", -1.0)  # any return counts as breached
    out = _trader(FakeClient(buy_p={"BBB": 0.99}), dfs).run_market("US")
    assert out["circuit_breaker"] is True and "BBB" not in out["open_positions"]


def test_crypto_drops_in_progress_candle():
    today = pd.Timestamp.now(tz="UTC").normalize()
    df = _df("BTCUSDT")
    df.index = pd.date_range(end=today, periods=len(df), freq="D", tz="UTC")

    class Crypto:
        def fetch_many(self, symbols, start_date, end_date=None, interval="1d"):
            return {s: df for s in symbols}

    jtr = jt.JevTrader(client=FakeClient(buy_p={"BTCUSDT": 0.9}), noul_cls=FakeNoul, crypto_fetcher=Crypto())
    import paper_trader.config as cfg
    settings.crypto_pairs = ["BTCUSDT"]
    try:
        out = jtr.run_market("CRYPTO")
    finally:
        settings.crypto_pairs = cfg.Settings().crypto_pairs
    assert f"{(today - pd.Timedelta(days=1)).date()}" in out["actions"][0]["client_order_id"]

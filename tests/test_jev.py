from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import paper_trader.jev as jev
import paper_trader.orchestrator as orchestrator
import paper_trader.persistence.state_store as state_store
from paper_trader.config import settings
from paper_trader.orchestrator import TradingBot
from tests.conftest import _make_ohlcv
from tests.test_orchestrator import _breakout_data


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'jev.db'}")
    state_store.Base.metadata.create_all(engine)
    monkeypatch.setattr(state_store, "_engine", engine)
    monkeypatch.setattr(state_store, "_Session", sessionmaker(bind=engine))
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")


class FakeNoul:
    def __init__(self, instructions):
        self.instructions = instructions


class FakeClient:
    def __init__(self, p=0.7, boom=False):
        self.p, self.boom, self.calls = p, boom, []

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        if self.boom:
            raise RuntimeError("jev down")
        return SimpleNamespace(answers={"followthrough": SimpleNamespace(noul=self.p)})


def _signal(price=100.0, stop=90.0, tp=115.0):
    return SimpleNamespace(price=price, stop_loss=stop, take_profit=tp, reasoning="breakout")


def _df(n=80):
    return _make_ohlcv(np.full(n, 100.0), "AAPL")


def test_observe_logs_probability_and_is_idempotent():
    client = FakeClient(0.7)
    df = _df()
    jev.observe("US", "AAPL", "Donchian", _signal(), df, client=client, noul_cls=FakeNoul)
    jev.observe("US", "AAPL", "Donchian", _signal(), df, client=client, noul_cls=FakeNoul)
    records = state_store.load_state(jev.STATE_KEY)["records"]
    assert len(records) == 1 and records[0]["p_yes"] == 0.7 and records[0]["outcome"] is None
    assert len(client.calls) == 1
    assert "stop-loss" in client.calls[0][0] and "AAPL" in client.calls[0][0]


def test_disabled_without_key_does_nothing(monkeypatch):
    monkeypatch.setattr(settings, "typesafe_api_key", "")
    jev.observe("US", "AAPL", "Donchian", _signal(), _df())
    assert state_store.load_state(jev.STATE_KEY) is None


def test_failing_client_logs_nothing_and_never_raises():
    jev.observe("US", "AAPL", "Donchian", _signal(), _df(), client=FakeClient(boom=True), noul_cls=FakeNoul)
    assert state_store.load_state(jev.STATE_KEY) is None


def _rec(**kw):
    base = {"id": "US:AAPL:x", "market": "US", "symbol": "AAPL", "strategy": "s", "entry": 100.0,
            "stop": 90.0, "take_profit": 115.0, "p_yes": 0.6, "outcome": None}
    base.update(kw)
    return base


def _bars(highs, lows, start="2023-02-01"):
    idx = pd.bdate_range(start=start, periods=len(highs))
    return pd.DataFrame({"high": highs, "low": lows, "close": 100.0, "open": 100.0}, index=idx)


def test_resolve_win_loss_same_bar_loss_open_and_timeout():
    rec = _rec(bar_date="2023-01-31")
    assert jev._resolve(rec, _bars([101, 116], [99, 99])) == "win"
    assert jev._resolve(rec, _bars([101, 101], [99, 89])) == "loss"
    assert jev._resolve(rec, _bars([120], [80])) == "loss"  # both on one bar: conservative loss
    assert jev._resolve(rec, _bars([101] * 5, [99] * 5)) is None  # still open
    assert jev._resolve(rec, _bars([101] * 25, [99] * 25)) == "timeout"


def test_update_resolves_only_matching_market(monkeypatch):
    monkeypatch.setattr(settings, "typesafe_api_key", "k")
    state_store.save_state(jev.STATE_KEY, {"records": [
        _rec(id="a", bar_date="2023-01-31"), _rec(id="b", market="INDIA", bar_date="2023-01-31")]})
    jev.update("US", {"AAPL": _bars([101, 116], [99, 99])})
    recs = {r["id"]: r for r in state_store.load_state(jev.STATE_KEY)["records"]}
    assert recs["a"]["outcome"] == "win" and recs["b"]["outcome"] is None


def test_report_scores_calibration_and_warns_when_thin(monkeypatch):
    state_store.save_state(jev.STATE_KEY, {"records": [
        _rec(id="1", p_yes=0.9, outcome="win"), _rec(id="2", p_yes=0.2, outcome="loss"),
        _rec(id="3", p_yes=0.8, outcome="win"), _rec(id="4", p_yes=0.1, outcome="timeout")]})
    r = jev.report()
    assert r["resolved"] == 4 and r["base_rate_win"] == 0.5
    assert r["brier_jev"] < r["brier_constant_base_rate"]
    assert "insufficient" in r["verdict"]


def test_report_with_nothing_resolved():
    assert jev.report()["verdict"] == "no resolved signals yet"


def test_broken_jev_never_changes_a_live_trade(monkeypatch):
    """Key set but SDK missing: the AAPL breakout must still execute exactly as before."""
    monkeypatch.setattr(settings, "typesafe_api_key", "k")
    monkeypatch.setattr(settings, "auto_execute", True)
    monkeypatch.setattr(jev, "_load_sdk", lambda: None)
    monkeypatch.setitem(orchestrator.MARKETS, "US", {"symbols": ["AAPL"], "capital": 10_000.0, "india": False})
    bot = TradingBot()
    monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})

    actions = bot.run_market_cycle("US")

    assert [a["action"] for a in actions] == ["EXECUTED"]
    assert state_store.load_state(jev.STATE_KEY) is None

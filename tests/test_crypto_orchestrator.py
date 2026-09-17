import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import paper_trader.persistence.state_store as state_store
from paper_trader.crypto_orchestrator import CryptoTradingBot
from paper_trader.config import settings
from tests.conftest import _make_ohlcv


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_crypto.db"
    engine = create_engine(f"sqlite:///{db_path}")
    state_store.Base.metadata.create_all(engine)
    monkeypatch.setattr(state_store, "_engine", engine)
    monkeypatch.setattr(state_store, "_Session", sessionmaker(bind=engine))


@pytest.fixture(autouse=True)
def small_universe(monkeypatch):
    # Keep tests fast and deterministic: one symbol instead of the full
    # 8-pair settings.crypto_pairs list.
    monkeypatch.setattr(settings, "crypto_pairs", ["BTCUSDT"])


def _breakout_data():
    flat = 100 - np.linspace(0, 2, 150)
    rally = flat[-1] + np.linspace(0, 40, 40)
    close = np.concatenate([flat, rally])
    return _make_ohlcv(close, "BTCUSDT")


def test_propose_only_by_default(monkeypatch):
    monkeypatch.setattr(settings, "auto_execute", False)
    bot = CryptoTradingBot()
    monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": _breakout_data()})

    actions = bot.run_cycle()

    assert len(actions) >= 1
    assert all(a["action"] == "PROPOSED_BUY" for a in actions)
    assert bot.trader.portfolio.positions == {}


def test_auto_execute_places_real_order(monkeypatch):
    monkeypatch.setattr(settings, "auto_execute", True)
    bot = CryptoTradingBot()
    monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": _breakout_data()})

    actions = bot.run_cycle()

    assert any(a["action"] == "EXECUTED" for a in actions)
    assert "BTCUSDT" in bot.trader.portfolio.positions


def test_state_persists_across_bot_instances(monkeypatch):
    monkeypatch.setattr(settings, "auto_execute", True)
    bot = CryptoTradingBot()
    monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": _breakout_data()})
    bot.run_cycle()

    bot2 = CryptoTradingBot()
    assert "BTCUSDT" in bot2.trader.portfolio.positions


def test_no_data_produces_no_actions(monkeypatch):
    bot = CryptoTradingBot()
    monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {})

    actions = bot.run_cycle()

    assert actions == []

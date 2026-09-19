import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import paper_trader.persistence.state_store as state_store
import paper_trader.orchestrator as orchestrator
from paper_trader.orchestrator import TradingBot
from paper_trader.config import settings
from tests.conftest import _make_ohlcv


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_orchestrator.db"
    engine = create_engine(f"sqlite:///{db_path}")
    state_store.Base.metadata.create_all(engine)
    monkeypatch.setattr(state_store, "_engine", engine)
    monkeypatch.setattr(state_store, "_Session", sessionmaker(bind=engine))


@pytest.fixture(autouse=True)
def small_universe(monkeypatch):
    # MARKETS is baked from settings at import time, so patch it directly
    # rather than settings.us_stocks/us_capital (which TradingBot would
    # never see after import).
    monkeypatch.setitem(orchestrator.MARKETS, "US", {"symbols": ["AAPL"], "capital": 10_000.0, "india": False})
    monkeypatch.setitem(orchestrator.MARKETS, "INDIA", {"symbols": ["RELIANCE"], "capital": 10_000.0, "india": True})


def _breakout_data():
    flat = 100 - np.linspace(0, 2, 150)
    rally = flat[-1] + np.linspace(0, 40, 40)
    close = np.concatenate([flat, rally])
    return _make_ohlcv(close, "AAPL")


def test_uses_donchian_strategy_not_trend_following():
    bot = TradingBot()
    assert bot.strategy.name.startswith("Donchian")


def test_propose_only_by_default(monkeypatch):
    monkeypatch.setattr(settings, "auto_execute", False)
    bot = TradingBot()
    monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})

    actions = bot.run_market_cycle("US")

    assert len(actions) >= 1
    assert all(a["action"] == "PROPOSED_BUY" for a in actions)
    assert bot.traders["US"].portfolio.positions == {}


def test_auto_execute_places_real_order(monkeypatch):
    monkeypatch.setattr(settings, "auto_execute", True)
    bot = TradingBot()
    monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})

    actions = bot.run_market_cycle("US")

    assert any(a["action"] == "EXECUTED" for a in actions)
    assert "AAPL" in bot.traders["US"].portfolio.positions


def test_state_persists_across_bot_instances(monkeypatch):
    monkeypatch.setattr(settings, "auto_execute", True)
    bot = TradingBot()
    monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})
    bot.run_market_cycle("US")

    bot2 = TradingBot()
    assert "AAPL" in bot2.traders["US"].portfolio.positions

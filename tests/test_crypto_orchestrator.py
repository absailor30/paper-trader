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


class TestCheckStopsOnly:
    """CryptoTradingBot.check_stops_only() -- the more-frequent companion
    to run_cycle() added for CHECKPOINT.md's 'Intraday stop monitoring'.
    Must never open a position, must only act via Strategy.check_stop_only
    (price vs stop/target), and must share state with run_cycle() rather
    than diverging."""

    def test_no_open_positions_produces_no_actions_and_no_fetch(self, monkeypatch):
        bot = CryptoTradingBot()
        fetch_called = []
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: fetch_called.append(1) or {})

        actions = bot.check_stops_only()

        assert actions == []
        assert fetch_called == [], "should not even fetch data when there's nothing open to check"

    def test_price_above_stop_produces_no_action(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = CryptoTradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": _breakout_data()})
        bot.run_cycle()
        assert "BTCUSDT" in bot.trader.portfolio.positions
        position = bot.trader.portfolio.positions["BTCUSDT"]
        stop_loss = position["stop_loss"]
        take_profit = position["take_profit"]

        # Price strictly between stop and target -- neither should fire.
        safe_price = (stop_loss + take_profit) / 2
        safe_price_data = _make_ohlcv(np.array([safe_price, safe_price]), "BTCUSDT")
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": safe_price_data})

        actions = bot.check_stops_only()

        assert actions == []
        assert "BTCUSDT" in bot.trader.portfolio.positions

    def test_price_below_stop_proposes_sell_when_not_auto_execute(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = CryptoTradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": _breakout_data()})
        bot.run_cycle()
        stop_loss = bot.trader.portfolio.positions["BTCUSDT"]["stop_loss"]

        # Now simulate propose-only mode for the intraday check itself.
        monkeypatch.setattr(settings, "auto_execute", False)
        breach_data = _make_ohlcv(np.array([stop_loss * 0.9, stop_loss * 0.9]), "BTCUSDT")
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": breach_data})

        actions = bot.check_stops_only()

        assert len(actions) == 1
        assert actions[0]["action"] == "PROPOSED_SELL"
        # Propose-only must not actually close the position.
        assert "BTCUSDT" in bot.trader.portfolio.positions

    def test_price_below_stop_executes_sell_when_auto_execute(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = CryptoTradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": _breakout_data()})
        bot.run_cycle()
        stop_loss = bot.trader.portfolio.positions["BTCUSDT"]["stop_loss"]

        breach_data = _make_ohlcv(np.array([stop_loss * 0.9, stop_loss * 0.9]), "BTCUSDT")
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": breach_data})

        actions = bot.check_stops_only()

        assert len(actions) == 1
        assert actions[0]["action"] == "EXECUTED"
        assert "BTCUSDT" not in bot.trader.portfolio.positions

    def test_never_opens_a_new_position(self, monkeypatch):
        """No open positions and a fresh breakout signal in the data --
        check_stops_only() must not act on it. Only run_cycle() enters."""
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = CryptoTradingBot()
        assert bot.trader.portfolio.positions == {}
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": _breakout_data()})

        actions = bot.check_stops_only()

        assert actions == []
        assert bot.trader.portfolio.positions == {}

    def test_state_shared_with_run_cycle_across_bot_instances(self, monkeypatch):
        """A stop hit by check_stops_only() in one process must be visible
        to a fresh CryptoTradingBot instance (i.e. what run_cycle() would
        see next) -- same crypto_portfolio state, not a separate one."""
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = CryptoTradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": _breakout_data()})
        bot.run_cycle()
        stop_loss = bot.trader.portfolio.positions["BTCUSDT"]["stop_loss"]

        breach_data = _make_ohlcv(np.array([stop_loss * 0.9, stop_loss * 0.9]), "BTCUSDT")
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": breach_data})
        bot.check_stops_only()
        assert "BTCUSDT" not in bot.trader.portfolio.positions

        bot2 = CryptoTradingBot()
        assert "BTCUSDT" not in bot2.trader.portfolio.positions

    def test_repeated_same_day_breach_does_not_double_sell(self, monkeypatch):
        """place_order()'s idempotent client_order_id guarantee must still
        hold if check_stops_only() somehow ran twice in one day (e.g. a
        retried Actions run) -- no double-fill."""
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = CryptoTradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": _breakout_data()})
        bot.run_cycle()
        stop_loss = bot.trader.portfolio.positions["BTCUSDT"]["stop_loss"]

        breach_data = _make_ohlcv(np.array([stop_loss * 0.9, stop_loss * 0.9]), "BTCUSDT")
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date: {"BTCUSDT": breach_data})

        first = bot.check_stops_only()
        assert len(first) == 1
        # Position already closed -- a second call has nothing open to check.
        second = bot.check_stops_only()
        assert second == []

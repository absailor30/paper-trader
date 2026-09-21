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


class TestCheckStopsOnly:
    """TradingBot.check_stops_only() -- the more-frequent companion to
    run_market_cycle(), mirroring CryptoTradingBot.check_stops_only().
    Must never open a position, must only act via
    Strategy.check_stop_only (price vs stop/target), and must share state
    with run_market_cycle() rather than diverging."""

    def test_no_open_positions_produces_no_actions_and_no_fetch(self, monkeypatch):
        bot = TradingBot()
        fetch_called = []
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: fetch_called.append(1) or {})

        actions = bot.check_stops_only("US")

        assert actions == []
        assert fetch_called == [], "should not even fetch data when there's nothing open to check"

    def test_price_above_stop_produces_no_action(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = TradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})
        bot.run_market_cycle("US")
        position = bot.traders["US"].portfolio.positions["AAPL"]
        stop_loss = position["stop_loss"]
        take_profit = position["take_profit"]

        safe_price = (stop_loss + take_profit) / 2
        safe_price_data = _make_ohlcv(np.array([safe_price, safe_price]), "AAPL")
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": safe_price_data})

        actions = bot.check_stops_only("US")

        assert actions == []
        assert "AAPL" in bot.traders["US"].portfolio.positions

    def test_price_below_stop_proposes_sell_when_not_auto_execute(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = TradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})
        bot.run_market_cycle("US")
        stop_loss = bot.traders["US"].portfolio.positions["AAPL"]["stop_loss"]

        monkeypatch.setattr(settings, "auto_execute", False)
        breach_data = _make_ohlcv(np.array([stop_loss * 0.9, stop_loss * 0.9]), "AAPL")
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": breach_data})

        actions = bot.check_stops_only("US")

        assert len(actions) == 1
        assert actions[0]["action"] == "PROPOSED_SELL"
        assert "AAPL" in bot.traders["US"].portfolio.positions

    def test_price_below_stop_executes_sell_when_auto_execute(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = TradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})
        bot.run_market_cycle("US")
        stop_loss = bot.traders["US"].portfolio.positions["AAPL"]["stop_loss"]

        breach_data = _make_ohlcv(np.array([stop_loss * 0.9, stop_loss * 0.9]), "AAPL")
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": breach_data})

        actions = bot.check_stops_only("US")

        assert len(actions) == 1
        assert actions[0]["action"] == "EXECUTED"
        assert "AAPL" not in bot.traders["US"].portfolio.positions

    def test_never_opens_a_new_position(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = TradingBot()
        assert bot.traders["US"].portfolio.positions == {}
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})

        actions = bot.check_stops_only("US")

        assert actions == []
        assert bot.traders["US"].portfolio.positions == {}

    def test_state_shared_with_run_market_cycle_across_bot_instances(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = TradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})
        bot.run_market_cycle("US")
        stop_loss = bot.traders["US"].portfolio.positions["AAPL"]["stop_loss"]

        breach_data = _make_ohlcv(np.array([stop_loss * 0.9, stop_loss * 0.9]), "AAPL")
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": breach_data})
        bot.check_stops_only("US")
        assert "AAPL" not in bot.traders["US"].portfolio.positions

        bot2 = TradingBot()
        assert "AAPL" not in bot2.traders["US"].portfolio.positions

    def test_repeated_same_day_breach_does_not_double_sell(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = TradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})
        bot.run_market_cycle("US")
        stop_loss = bot.traders["US"].portfolio.positions["AAPL"]["stop_loss"]

        breach_data = _make_ohlcv(np.array([stop_loss * 0.9, stop_loss * 0.9]), "AAPL")
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": breach_data})

        first = bot.check_stops_only("US")
        assert len(first) == 1
        second = bot.check_stops_only("US")
        assert second == []


class TestPositionSizing:
    """Real production bug (2026-09-21): a $100-capital account got a real
    Donchian buy signal on a ~$560 stock and _position_size skipped it
    entirely, even though fractional shares are supported end-to-end
    (place_order takes qty as-is). Reproduces that exact scenario."""

    def test_expensive_stock_against_small_account_gets_fractional_shares_not_skipped(self, monkeypatch):
        monkeypatch.setitem(orchestrator.MARKETS, "US", {"symbols": ["AAPL"], "capital": 100.0, "india": False})
        bot = TradingBot()

        qty = bot._position_size(bot.traders["US"], price=559.82)

        assert qty > 0
        # sized up to the concentration ceiling (50% of $100), not a whole share
        assert qty * 559.82 <= 100.0 * settings.concentration_ceiling + 1e-6

    def test_normal_target_allocation_unaffected(self, monkeypatch):
        monkeypatch.setitem(orchestrator.MARKETS, "US", {"symbols": ["AAPL"], "capital": 10_000.0, "india": False})
        bot = TradingBot()

        qty = bot._position_size(bot.traders["US"], price=100.0)

        assert qty == round(10_000.0 * settings.max_position_size / 100.0, 4)

    def test_zero_cash_still_skips(self, monkeypatch):
        monkeypatch.setitem(orchestrator.MARKETS, "US", {"symbols": ["AAPL"], "capital": 100.0, "india": False})
        bot = TradingBot()
        bot.traders["US"].portfolio.capital = 0.0

        assert bot._position_size(bot.traders["US"], price=559.82) == 0.0

    def test_non_positive_price_returns_zero(self):
        bot = TradingBot()
        assert bot._position_size(bot.traders["US"], price=0.0) == 0.0
        assert bot._position_size(bot.traders["US"], price=-5.0) == 0.0

    def test_india_never_returns_fractional_shares(self, monkeypatch):
        # NSE/BSE brokers only fill whole shares, unlike US -- this is a
        # real market-structure difference the user flagged, not a config
        # choice. Every India quantity must be a whole number.
        monkeypatch.setitem(orchestrator.MARKETS, "INDIA", {"symbols": ["RELIANCE"], "capital": 10_000.0, "india": True})
        bot = TradingBot()

        # normal target-allocation path
        qty = bot._position_size(bot.traders["INDIA"], price=333.0, india=True)
        assert qty == float(int(qty))
        assert qty >= 1

        # below-target fallback path (mirrors the $559.82 US scenario)
        monkeypatch.setitem(orchestrator.MARKETS, "INDIA", {"symbols": ["RELIANCE"], "capital": 100.0, "india": True})
        bot_small = TradingBot()
        qty_small = bot_small._position_size(bot_small.traders["INDIA"], price=559.82, india=True)
        assert qty_small == float(int(qty_small))

    def test_india_skips_when_even_one_whole_share_unaffordable(self, monkeypatch):
        monkeypatch.setitem(orchestrator.MARKETS, "INDIA", {"symbols": ["RELIANCE"], "capital": 10.0, "india": True})
        bot = TradingBot()

        qty = bot._position_size(bot.traders["INDIA"], price=559.82, india=True)

        assert qty == 0.0

    def test_us_still_gets_fractional_shares_by_default(self, monkeypatch):
        # india defaults to False -- existing US call sites are unaffected.
        monkeypatch.setitem(orchestrator.MARKETS, "US", {"symbols": ["AAPL"], "capital": 100.0, "india": False})
        bot = TradingBot()

        qty = bot._position_size(bot.traders["US"], price=559.82)

        assert qty > 0
        assert qty < 1  # fractional -- not forced up to a whole share

from datetime import datetime

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

        trader = bot.traders["US"]
        effective_price = 100.0 * (1 + trader.slippage_rate) * (1 + trader.commission_rate)
        assert qty == round(10_000.0 * settings.max_position_size / effective_price, 4)

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

    def test_sized_quantity_never_gets_rejected_for_insufficient_capital(self, monkeypatch):
        """Real production bug (2026-09-21): QQQ was sized to fit the exact
        remaining cash, then place_order REJECTED it anyway ("need $50.00,
        have $49.90") because sizing ignored the slippage+commission
        place_order adds on top of raw price. Reproduces the exact
        low-cash-after-a-prior-fill scenario and asserts the order fills."""
        monkeypatch.setitem(orchestrator.MARKETS, "US", {"symbols": ["QQQ"], "capital": 100.0, "india": False})
        bot = TradingBot()
        trader = bot.traders["US"]
        trader.portfolio.capital = 49.90  # cash left after a prior same-cycle fill

        qty = bot._position_size(trader, price=736.2999877929688)
        assert qty > 0

        order = trader.place_order(
            "QQQ:test:2026-09-21:BUY", "QQQ", "BUY", qty, 736.2999877929688, "test",
        )
        assert order["status"] == "FILLED"

    def test_rounding_never_produces_a_quantity_costing_more_than_allocated(self, monkeypatch):
        """Real production bug, round 2 (2026-09-21): the slippage/commission
        headroom fix above still got rejected for a DIFFERENT QQQ price
        ("need $49.93, have $49.90") because round(shares, 4) can round UP
        (0.067657 -> 0.0677), producing a quantity whose real fill cost
        exceeds what it was sized against. Must floor, not round."""
        monkeypatch.setitem(orchestrator.MARKETS, "US", {"symbols": ["QQQ"], "capital": 100.0, "india": False})
        bot = TradingBot()
        trader = bot.traders["US"]
        trader.portfolio.capital = 49.90

        qty = bot._position_size(trader, price=736.4401245117188)
        assert qty > 0

        order = trader.place_order(
            "QQQ:test:2026-09-21:BUY:RETRY", "QQQ", "BUY", qty, 736.4401245117188, "test",
        )
        assert order["status"] == "FILLED"


class TestRetryEntry:
    """retry_entry() lets a REJECTED same-day BUY (e.g. one rejected by a
    sizing bug since fixed) be re-attempted without waiting for tomorrow's
    cycle -- run_market_cycle's own client_order_id dedup would otherwise
    just return the cached rejection forever for that day."""

    def test_uses_a_distinct_client_order_id_not_the_original(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = TradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})

        result = bot.retry_entry("US", "AAPL")

        assert result["action"] == "EXECUTED"
        assert result["client_order_id"].endswith(":RETRY1")
        assert "AAPL" in bot.traders["US"].portfolio.positions

    def test_second_same_day_retry_uses_a_new_id_not_the_first_retrys_cache(self, monkeypatch):
        """Real production bug: a fixed :RETRY suffix meant a second retry
        today just replayed the first retry's own cached (rejected)
        result verbatim, even after the underlying bug was fixed."""
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = TradingBot()
        trader = bot.traders["US"]
        today = datetime.now().strftime("%Y-%m-%d")
        first_retry_id = f"AAPL:{bot.strategy.name}:{today}:BUY:RETRY1"
        # Simulate a first retry that was itself rejected (e.g. before a
        # follow-up bug fix landed).
        trader.place_order(first_retry_id, "AAPL", "BUY", 999_999.0, 100.0, bot.strategy.name)
        assert trader._order_results[first_retry_id]["status"] == "REJECTED"

        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})
        result = bot.retry_entry("US", "AAPL")

        assert result["client_order_id"] == f"AAPL:{bot.strategy.name}:{today}:BUY:RETRY2"
        assert result["action"] == "EXECUTED"
        assert trader._order_results[first_retry_id]["status"] == "REJECTED"  # untouched

    def test_does_not_touch_the_original_rejected_order(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = TradingBot()
        trader = bot.traders["US"]
        today = datetime.now().strftime("%Y-%m-%d")
        original_id = f"AAPL:{bot.strategy.name}:{today}:BUY"
        # Simulate the original same-day rejection (e.g. from the sizing bug).
        trader.place_order(original_id, "AAPL", "BUY", 999_999.0, 100.0, bot.strategy.name)
        assert trader._order_results[original_id]["status"] == "REJECTED"

        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})
        result = bot.retry_entry("US", "AAPL")

        assert result["action"] == "EXECUTED"
        assert trader._order_results[original_id]["status"] == "REJECTED"  # untouched

    def test_skips_when_already_an_open_position(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = TradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})
        bot.run_market_cycle("US")
        assert "AAPL" in bot.traders["US"].portfolio.positions

        result = bot.retry_entry("US", "AAPL")

        assert result == {"action": "SKIPPED", "reason": "already an open position"}

    def test_skips_when_no_signal(self, monkeypatch):
        bot = TradingBot()
        flat = _make_ohlcv(np.full(200, 100.0), "AAPL")
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": flat})

        result = bot.retry_entry("US", "AAPL")

        assert result == {"action": "SKIPPED", "reason": "no signal"}

    def test_propose_only_when_auto_execute_false(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", False)
        bot = TradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})

        result = bot.retry_entry("US", "AAPL")

        assert result["action"] == "PROPOSED_BUY"
        assert bot.traders["US"].portfolio.positions == {}


class TestMarkToMarketAndStatus:
    """Real bug found while wiring P&L into the dashboard: current_price
    was only ever set once, at fill time, and never refreshed --
    total_value/total_return_pct (and get_status()'s unrealized P&L)
    silently stayed at the entry price forever. run_market_cycle() and
    check_stops_only() must now mark every open position to the latest
    fetched close before anything else."""

    def test_run_market_cycle_marks_open_position_to_latest_close(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = TradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})
        bot.run_market_cycle("US")
        entry_price = bot.traders["US"].portfolio.positions["AAPL"]["current_price"]

        higher = _make_ohlcv(np.full(2, entry_price * 1.10), "AAPL")
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": higher})
        bot.run_market_cycle("US")

        assert bot.traders["US"].portfolio.positions["AAPL"]["current_price"] == pytest.approx(entry_price * 1.10)

    def test_check_stops_only_marks_to_market_and_persists_even_without_a_breach(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = TradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})
        bot.run_market_cycle("US")
        entry_price = bot.traders["US"].portfolio.positions["AAPL"]["current_price"]

        # A small price move (well inside stop_loss/take_profit either
        # way) -- should still mark to market without triggering a sell.
        up = _make_ohlcv(np.full(2, entry_price * 1.001), "AAPL")
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": up})
        actions = bot.check_stops_only("US")

        assert actions == []  # no stop breach, nothing executed
        assert bot.traders["US"].portfolio.positions["AAPL"]["current_price"] == pytest.approx(up["close"].iloc[-1])

        bot2 = TradingBot()  # reload from persisted state
        assert bot2.traders["US"].portfolio.positions["AAPL"]["current_price"] == pytest.approx(up["close"].iloc[-1])

    def test_get_status_reports_unrealized_pnl(self, monkeypatch):
        monkeypatch.setattr(settings, "auto_execute", True)
        bot = TradingBot()
        monkeypatch.setattr(bot.fetcher, "fetch_many", lambda symbols, start_date, india=False: {"AAPL": _breakout_data()})
        bot.run_market_cycle("US")
        position = bot.traders["US"].portfolio.positions["AAPL"]
        position["current_price"] = position["entry_price"] * 2  # simulate a fresh, favorable mark

        status = bot.get_status("US")

        assert status["market"] == "US"
        assert status["num_positions"] == 1
        pos = status["positions"][0]
        assert pos["symbol"] == "AAPL"
        assert pos["unrealized_pnl"] == pytest.approx(position["entry_price"] * position["quantity"])
        assert pos["unrealized_pnl_pct"] == pytest.approx(100.0)
        assert pos["invested"] == pytest.approx(position["entry_price"] * position["quantity"])
        assert pos["current_value"] == pytest.approx(position["current_price"] * position["quantity"])

    def test_get_status_with_no_positions(self):
        bot = TradingBot()
        status = bot.get_status("US")
        assert status["positions"] == []
        assert status["num_positions"] == 0

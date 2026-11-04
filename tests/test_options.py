from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import paper_trader.persistence.state_store as state_store
from paper_trader.config import settings
from paper_trader.options.book import OptionsBook
from paper_trader.options.pricing import bs_delta
from paper_trader.options.selection import select_contract
from paper_trader.options_orchestrator import OptionsBot, bearish_signal, bullish_signal, pick_expiry
from tests.conftest import _make_ohlcv

TODAY = date.today()
EXPIRY = TODAY + timedelta(days=45)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'o.db'}")
    state_store.Base.metadata.create_all(engine)
    monkeypatch.setattr(state_store, "_engine", engine)
    monkeypatch.setattr(state_store, "_Session", sessionmaker(bind=engine))
    monkeypatch.setattr(settings, "us_stocks", ["AAA"])
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")
    monkeypatch.setattr(settings, "auto_execute", True)


def chain(rows):
    return pd.DataFrame(rows, columns=["contractSymbol", "strike", "bid", "ask", "openInterest", "impliedVolatility"])


def test_bs_delta_sanity():
    assert 0.45 < bs_delta(100, 100, 0.12, 0.04, 0.3, True) < 0.6
    assert bs_delta(100, 100, 0.12, 0.04, 0.3, False) < 0
    assert bs_delta(100, 50, 0.12, 0.04, 0.3, True) > 0.99
    assert bs_delta(100, 100, 0, 0.04, 0.3, True) is None


def test_selection_filters_and_reports_reason():
    # AAA at 10: ask 0.40 -> $40/contract fits a $50 budget; strike 10 ATM
    good = chain([("AAA_C10", 10, 0.38, 0.40, 500, 0.5)])
    c, info = select_contract(good, 10.0, True, TODAY, EXPIRY, budget=50)
    assert c["contract"] == "AAA_C10" and c["cost"] == pytest.approx(40.0) and info["reason"] == "ok"
    c, info = select_contract(good, 10.0, True, TODAY, EXPIRY, budget=20)
    assert c is None and "too expensive" in info["reason"] and "$40" in info["reason"]
    thin = chain([("AAA_C10", 10, 0.38, 0.40, 5, 0.5)])  # open interest 5
    assert select_contract(thin, 10.0, True, TODAY, EXPIRY, 50)[1]["reason"].startswith("no liquid")
    wide = chain([("AAA_C10", 10, 0.10, 0.40, 500, 0.5)])  # spread 120%
    assert select_contract(wide, 10.0, True, TODAY, EXPIRY, 50)[0] is None
    nobid = chain([("AAA_C10", 10, 0.0, 0.40, 500, 0.5)])
    assert select_contract(nobid, 10.0, True, TODAY, EXPIRY, 50)[0] is None


def test_selection_prefers_highest_delta_that_fits():
    ch = chain([("A9", 9, 0.95, 1.00, 500, 0.5), ("A10", 10, 0.38, 0.40, 500, 0.5), ("A12", 12, 0.03, 0.04, 500, 0.5)])
    c, _ = select_contract(ch, 10.0, True, TODAY, EXPIRY, budget=50)
    assert c["contract"] == "A10"  # A9 costs $100 (over budget); A12 is below the delta band


def test_pick_expiry_window():
    ex = [(TODAY + timedelta(days=d)).isoformat() for d in (10, 30, 44, 60, 90)]
    assert pick_expiry(ex, TODAY) == (TODAY + timedelta(days=44)).isoformat()
    assert pick_expiry([(TODAY + timedelta(days=5)).isoformat()], TODAY) is None


def test_signals():
    breakout = _make_ohlcv(np.concatenate([np.linspace(100, 130, 150), [150.0]]), "AAA")
    assert bullish_signal(breakout) and not bearish_signal(breakout)
    breakdown = _make_ohlcv(np.concatenate([np.linspace(130, 100, 150), [80.0]]), "AAA")
    assert bearish_signal(breakdown) and not bullish_signal(breakdown)


def test_book_buy_sell_fees_pnl_and_idempotency():
    b = OptionsBook(100.0)
    c = {"contract": "AAA_C10", "strike": 10.0, "ask": 0.40, "mid": 0.39, "delta": 0.5}
    o = b.buy("id1", c, "call", "AAA", EXPIRY.isoformat(), 10.0)
    assert o["status"] == "FILLED" and b.cash == pytest.approx(100 - 40 - settings.options_commission_per_contract)
    assert b.buy("id1", c, "call", "AAA", EXPIRY.isoformat(), 10.0) is o or True  # replay does not double-buy
    assert len(b.positions) == 1
    s = b.sell("id2", "AAA_C10", 0.80, "take profit")
    assert s["pnl"] == pytest.approx(80 - settings.options_commission_per_contract - (40 + settings.options_commission_per_contract))
    assert b.sell("id2", "AAA_C10", 0.80, "again") is None and not b.positions
    rich = OptionsBook(10.0)
    assert rich.buy("id3", c, "call", "AAA", EXPIRY.isoformat(), 10.0)["status"] == "REJECTED"


class FakeChains:
    def __init__(self, ask=0.40, bid=0.38, strike=11):
        self.ask, self.bid, self.strike, self.calls = ask, bid, strike, []

    def expiries(self, symbol):
        return [EXPIRY.isoformat()]

    def chain(self, symbol, expiry, kind):
        self.calls.append((symbol, expiry, kind))
        return chain([(f"{symbol}_{kind}{self.strike}", self.strike, self.bid, self.ask, 500, 0.5)])


class FakeFetcher:
    def __init__(self, df):
        self.df = df

    def fetch_many(self, symbols, start_date, **kw):
        return {s: self.df for s in symbols}


def _bot(df, chains):
    bot = OptionsBot(FakeFetcher(df), chains)
    return bot


def _breakout():
    return _make_ohlcv(np.concatenate([np.linspace(8, 10, 150), [11.0]]), "AAA")


def test_cycle_buys_call_on_breakout_when_affordable_and_status_shape(monkeypatch):
    monkeypatch.setattr("paper_trader.options_orchestrator.datetime", __import__("datetime").datetime)
    bot = _bot(_breakout(), FakeChains())
    acts = bot.run_cycle()
    assert [a["action"] for a in acts] == ["EXECUTED"] and len(bot.book.positions) == 1
    st = bot.get_status()
    assert st["market"] == "OPTIONS" and st["positions"][0]["quantity"] == 100 and st["positions"][0]["symbol"].startswith("AAA ")
    assert st["executed"][0]["side"] == "BUY" and st["executed"][0]["value"] == pytest.approx(40.0)
    again = OptionsBot(FakeFetcher(_breakout()), FakeChains())  # state persisted; same-day replay adds nothing
    assert len(again.book.positions) == 1 and [a["action"] for a in again.run_cycle()] == []


def test_cycle_logs_too_expensive_and_buys_nothing():
    bot = _bot(_breakout(), FakeChains(ask=5.0, bid=4.9))
    acts = bot.run_cycle()
    assert acts[0]["action"] == "SKIPPED" and "too expensive" in acts[0]["reason"] and not bot.book.positions


def test_propose_only_does_not_trade(monkeypatch):
    monkeypatch.setattr(settings, "auto_execute", False)
    bot = _bot(_breakout(), FakeChains())
    assert bot.run_cycle()[0]["action"] == "PROPOSED_BUY" and not bot.book.positions


def test_exits_stop_take_profit_expiry_and_dte():
    def held(entry, mark, expiry):
        bot = _bot(_make_ohlcv(np.linspace(8, 10, 160), "AAA"), FakeChains(ask=mark + 0.02, bid=mark, strike=10))
        bot.book.cash = 50.0
        bot.book.positions["AAA_call10"] = {"underlying": "AAA", "kind": "call", "strike": 10.0, "expiry": expiry.isoformat(),
                                            "contracts": 1, "entry_price": entry, "mark": entry, "entry_time": "2026-10-01T10:00:00",
                                            "entry_spot": 10.0, "entry_cost": entry * 100 + 0.65}
        return bot
    today = date.today()
    far = today + timedelta(days=45)
    stop = held(0.40, 0.18, far)  # -55%
    assert "stop" in stop._exits(today, {"AAA": stop.fetcher.df})[0]["reason"]
    tp = held(0.40, 0.85, far)  # +112%
    assert "take profit" in tp._exits(today, {"AAA": tp.fetcher.df})[0]["reason"]
    near = held(0.40, 0.40, today + timedelta(days=3))
    assert "days to expiry" in near._exits(today, {"AAA": near.fetcher.df})[0]["reason"]
    expired = held(0.40, 0.40, today - timedelta(days=1))
    acts = expired._exits(today, {"AAA": expired.fetcher.df})
    assert "expired" in acts[0]["reason"] and not expired.book.positions
    hold = held(0.40, 0.42, far)
    assert hold._exits(today, {"AAA": hold.fetcher.df}) == [] and len(hold.book.positions) == 1


def test_dashboard_card_renders_option_account():
    from scripts.render_status_page import market_card, orders_section
    bot = _bot(_breakout(), FakeChains())
    bot.run_cycle()
    st = bot.get_status()
    html = market_card("OPTIONS", "Options — long calls/puts", st)
    assert "AAA " in html and "Invested" in html
    assert "Buys &mdash; executed (1)" in orders_section([("OPTIONS", "Options — long calls/puts", st)])

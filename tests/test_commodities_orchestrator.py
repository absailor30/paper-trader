import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import paper_trader.persistence.state_store as state_store
import scripts.commodities_portfolio_search as cps
from paper_trader.commodities_orchestrator import CommoditiesBot
from paper_trader.config import settings
from paper_trader.strategy.commodity_rotation import last_month_end, rotation_targets

FUNDS = ["UPA", "UPB", "FLAT", "DOWN"]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}")
    state_store.Base.metadata.create_all(engine)
    monkeypatch.setattr(state_store, "_engine", engine)
    monkeypatch.setattr(state_store, "_Session", sessionmaker(bind=engine))
    monkeypatch.setattr(settings, "commodities", FUNDS)
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")


def _close(end="2026-10-14", n=330):
    idx = pd.bdate_range(end=end, periods=n)
    t = np.arange(n)
    return pd.DataFrame({
        "UPA": 100 * 1.003 ** t, "UPB": 100 * 1.001 ** t,
        "FLAT": np.full(n, 100.0), "DOWN": 100 * 0.999 ** t}, index=idx)


def _frames(close):
    out = {}
    for s in close:
        df = pd.DataFrame({"open": close[s], "high": close[s] * 1.001, "low": close[s] * 0.999,
                           "close": close[s], "volume": 1000.0})
        df["symbol"] = s
        out[s] = df
    return out


class FakeFetcher:
    def __init__(self, close):
        self.close = close

    def fetch_many(self, symbols, start_date, **kw):
        return {s: f for s, f in _frames(self.close).items() if s in symbols}


def test_rotation_picks_top_uptrending_only():
    assert rotation_targets(_close(), top=3) == ["UPA", "UPB"]  # FLAT/DOWN fail momentum


def test_live_selection_matches_backtested_rotation():
    close = _close(n=400)
    t = last_month_end(close.index)
    live = set(rotation_targets(close.loc[:t], 3, 126, 200))
    bt = cps.rotation_weights(close, 3, 126, 200).loc[t]
    assert live == set(bt[bt > 0].index)


def test_last_month_end_is_last_bar_of_previous_month():
    close = _close(end="2026-10-14")
    assert last_month_end(close.index) == pd.Timestamp("2026-09-30")


def test_propose_only_places_nothing(monkeypatch):
    monkeypatch.setattr(settings, "auto_execute", False)
    bot = CommoditiesBot(FakeFetcher(_close()))
    acts = bot.run_cycle()
    assert acts and all(a["action"] == "PROPOSED_BUY" for a in acts)
    assert bot.trader.portfolio.positions == {} and bot.meta["last_rebalance"] is None


def test_executes_top_two_at_12pct_and_is_idempotent_within_month(monkeypatch):
    monkeypatch.setattr(settings, "auto_execute", True)
    bot = CommoditiesBot(FakeFetcher(_close()))
    acts = bot.run_cycle()
    assert {a["symbol"] for a in acts if a["action"] == "EXECUTED"} == {"UPA", "UPB"}
    for pos in bot.trader.portfolio.positions.values():
        assert pos["quantity"] * pos["entry_price"] == pytest.approx(12.0, rel=0.01)
    assert bot.run_cycle() == []  # same month: nothing more
    again = CommoditiesBot(FakeFetcher(_close()))  # state persisted
    assert set(again.trader.portfolio.positions) == {"UPA", "UPB"} and again.run_cycle() == []


def test_new_month_sells_dropouts_and_keeps_winners(monkeypatch):
    monkeypatch.setattr(settings, "auto_execute", True)
    bot = CommoditiesBot(FakeFetcher(_close()))
    bot.run_cycle()
    nxt = _close(end="2026-11-10", n=345)
    nxt["UPB"] = nxt["UPB"] * np.where(np.arange(len(nxt)) > 300, 0.5, 1.0)  # UPB collapses
    bot2 = CommoditiesBot(FakeFetcher(nxt))
    acts = bot2.run_cycle()
    sells = {a["symbol"] for a in acts if a["side"] == "SELL"}
    assert sells == {"UPB"} and set(bot2.trader.portfolio.positions) == {"UPA"}
    assert any(o["pnl"] < 0 for o in bot2.get_status()["closed_trades"])


def test_no_data_does_nothing():
    class Empty:
        def fetch_many(self, *a, **k):
            return {}
    assert CommoditiesBot(Empty()).run_cycle() == []


def test_status_shape_for_dashboard(monkeypatch):
    monkeypatch.setattr(settings, "auto_execute", True)
    bot = CommoditiesBot(FakeFetcher(_close()))
    bot.run_cycle()
    s = bot.get_status()
    assert s["market"] == "COMMODITIES" and len(s["positions"]) == 2 and s["last_rebalance"] == "2026-09"

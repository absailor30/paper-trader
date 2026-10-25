import numpy as np
import pandas as pd

from paper_trader import watch
from scripts.render_status_page import watch_section
from tests.conftest import _make_ohlcv


def _df(close):
    return _make_ohlcv(np.asarray(close, dtype=float), "X")


def test_donchian_state_breakout_vs_distance():
    up = _df(np.concatenate([np.full(119, 100.0), [110.0]]))
    assert watch.donchian_state(up, 20, None) == "BREAKOUT"
    flat = _df(np.concatenate([np.linspace(100, 130, 100), np.linspace(130, 120, 20)]))
    assert watch.donchian_state(flat, 20, None).startswith("needs +")
    below = _df(np.concatenate([np.linspace(160, 100, 110), np.linspace(100, 110, 10)]))
    assert "below SMA100" in watch.donchian_state(below, 20, 100)


def test_momentum_state_reasons():
    from paper_trader.strategy.momentum_trend import MomentumTrend
    m = MomentumTrend(126, 0.10, 50)
    assert watch.momentum_state(_df(np.linspace(100, 160, 200)), m.lookback, m.min_ret, m.sma_n) == "QUALIFIES"
    s = watch.momentum_state(_df(np.linspace(160, 100, 200)), m.lookback, m.min_ret, m.sma_n)
    assert "below SMA50" in s and "< 10%" in s


def test_build_marks_held_first_and_commodity_rank():
    n = 330
    t = np.arange(n)
    data = {"UP": _df(100 * 1.003 ** t), "FLAT": _df(np.full(n, 100.0))}
    rows = watch.build("COMMODITIES", data, {"FLAT"})
    assert rows[0]["symbol"] == "FLAT" and rows[0]["held"]
    sig = {r["symbol"]: r["signal"] for r in rows}
    assert sig["UP"].startswith("in today's top") and sig["FLAT"].startswith("not eligible")


def test_digest_and_dashboard_render():
    n = 130
    rows = watch.build("US", {"AAA": _df(np.concatenate([np.full(n - 1, 100.0), [110.0]]))}, {"AAA"},
                       __import__("paper_trader.strategy.donchian_breakout", fromlist=["x"]).DonchianBreakoutStrategy(20, 10, None))
    w = {"generated": "2026-10-23 22:25 UTC", "markets": {"US": {"rows": rows, "as_of": rows[0]["bar_date"]}}}
    assert "signal now: AAA" in watch.digest_text(w)
    html = watch_section(w)
    assert "★ AAA" in html and "Market watch" in html
    assert watch_section(None) == ""


def _watch(sig, price, date="2026-10-01"):
    return {"markets": {"US": {"rows": [{"symbol": "AAA", "signal": sig, "price": price, "bar_date": date,
                                          "held": False, "d1": 0.0, "d5": 0.0}], "as_of": date}}}


def test_signal_logged_once_per_streak_and_scoreboard_measures_forward_return():
    log = watch.log_signals(_watch("BREAKOUT", 100.0, "2026-10-01"), None)
    log = watch.log_signals(_watch("BREAKOUT", 103.0, "2026-10-02"), log)  # same streak: not logged again
    assert len(log["entries"]) == 1
    log = watch.log_signals(_watch("needs +2.0% to break 20d high", 101.0, "2026-10-03"), log)
    log = watch.log_signals(_watch("BREAKOUT", 104.0, "2026-10-04"), log)  # new streak
    assert len(log["entries"]) == 2
    sb = watch.scoreboard(log, _watch("BREAKOUT", 110.0, "2026-10-11"))["US"]
    assert sb["signals"] == 2 and sb["pct_positive"] == 100.0
    assert abs(sb["avg_ret"] - ((110 / 100 - 1) + (110 / 104 - 1)) * 50) < 1e-9
    assert sb["avg_days"] == (10 + 7) / 2


def test_scoreboard_renders_on_dashboard():
    w = _watch("BREAKOUT", 110.0, "2026-10-11")
    log = watch.log_signals(_watch("BREAKOUT", 100.0), None)
    w["scoreboard"] = watch.scoreboard(log, w)
    assert "Signal scoreboard" in watch_section(w)

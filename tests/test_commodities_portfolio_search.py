import numpy as np
import pandas as pd

import scripts.commodities_portfolio_search as cps


def _frames(n=400, drift=0.002):
    idx = pd.bdate_range("2020-01-01", periods=n)
    up = pd.Series(100 * np.cumprod(1 + np.full(n, drift)), index=idx)
    flat = pd.Series(100.0, index=idx)
    close = pd.DataFrame({"UP": up, "FLAT": flat})
    return close, close * 1.001, close * 0.999


def test_no_lookahead_weight_applies_next_bar():
    close, _, _ = _frames()
    w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    w.iloc[100, 0] = 0.12  # decided at bar 100 -> earns bar 101 only
    r = cps.simulate(close, w, 50, 200)
    expected = 0.12 * (close["UP"].iloc[101] / close["UP"].iloc[100] - 1) * 100
    assert abs(r["ret"] - expected) < 0.2  # minus two sides of costs
    assert r["entries"] == 1


def test_costs_reduce_return():
    close, _, _ = _frames()
    w = cps.hold_weights(close)
    gross = 0.12 * (close["UP"].iloc[-1] / close["UP"].iloc[1] - 1) * 100
    assert cps.simulate(close, w, 0, len(close))["ret"] < gross + 1e-9


def test_rotation_holds_only_top_uptrending_and_never_the_flat_fund():
    close, _, _ = _frames()
    w = cps.rotation_weights(close, top=2, lookback=60, trend=100)
    assert (w["FLAT"] == 0).all()
    assert w["UP"].iloc[-1] == cps.BASE_W


def test_donchian_enters_uptrend_and_vol_scaling_changes_size():
    close, high, low = _frames()
    flat = cps.donchian_weights(close, high, low)
    assert flat["UP"].iloc[-1] == cps.BASE_W and (flat["FLAT"] == 0).all()
    scaled = cps.donchian_weights(close, high, low, vol_target=0.15)
    assert scaled["UP"].iloc[-1] != cps.BASE_W  # constant-drift series has ~0 vol -> clipped to 0.20 cap


def test_keltner_enters_strong_uptrend():
    close, high, low = _frames()
    assert cps.keltner_weights(close, high, low)["UP"].iloc[-1] == cps.BASE_W


def test_robust_needs_entries_in_every_period():
    ok = {p: {"ret": 1.0, "entries": 20} for p in ("P1", "P2", "P3")}
    assert cps.is_robust(ok)
    ok["P2"]["entries"] = 3
    assert not cps.is_robust(ok)


def test_decision_frequency_masks():
    idx = pd.bdate_range("2026-01-01", periods=60)
    d, w, m = (cps.period_end_mask(idx, f) for f in "DWM")
    assert d.all() and m.sum() == 3 and w.sum() == 13 and not (m & ~w).any()  # month-ends are week-ends
    assert idx[w][0].dayofweek == 4  # Fridays


def test_daily_rotation_reacts_faster_than_monthly():
    close, _, _ = _frames()
    close["FLAT"] = np.where(np.arange(len(close)) > 350, 100 * 1.02 ** (np.arange(len(close)) - 350), 100.0)
    daily = cps.rotation_weights(close, 3, 60, 100, "D")
    monthly = cps.rotation_weights(close, 3, 60, 100, "M")
    assert (daily != monthly).any().any() and (daily.diff().abs().sum().sum() >= monthly.diff().abs().sum().sum())

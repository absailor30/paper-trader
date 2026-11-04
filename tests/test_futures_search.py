import numpy as np
import pandas as pd

import scripts.futures_search as fs
from tests.conftest import _make_ohlcv


def _frames(n=500):
    up = _make_ohlcv(np.concatenate([np.full(80, 100.0), np.linspace(100, 220, n - 80)]), "UP")
    down = _make_ohlcv(np.concatenate([np.full(80, 100.0), np.linspace(100, 40, n - 80)]), "DOWN")
    return {"UP": up, "DOWN": down}


def test_shorts_make_money_in_a_downtrend_that_long_only_cannot():
    res, close = fs.evaluate_group(_frames())
    ls, lo = res["L/S Donchian 55/20"], res["Long-only 55/20 (baseline)"]
    total = lambda r: sum(r[p]["ret"] for p in r)
    assert total(ls) > total(lo)  # the DOWN instrument only pays when shorting is allowed
    assert all(lo[p]["exposure"] <= ls[p]["exposure"] + 1e-9 for p in ls)


def test_signed_weights_and_flip_entries_counted():
    close = pd.DataFrame({"A": [100.0] * 5 + [110, 90, 80, 70, 60]})
    w = pd.DataFrame({"A": [0, 0, 0, 0.12, 0.12, 0.12, -0.12, -0.12, 0, 0.0]}, index=close.index)
    import scripts.commodities_portfolio_search as cps
    r = cps.simulate(close, w.shift(-1).fillna(0), 0, len(close))  # weights decided at t earn t+1
    assert r["entries"] >= 2  # a long entry and a long->short flip each count


def test_report_runs_and_marks_baseline_not_robust(capsys):
    fs.report_group("Test group", _frames())
    out = capsys.readouterr().out
    assert "Test group" in out and "L/S Donchian 55/20" in out and "Buy & hold" in out
    line = [l for l in out.splitlines() if l.startswith("Buy & hold")][0]
    assert "ROBUST" not in line

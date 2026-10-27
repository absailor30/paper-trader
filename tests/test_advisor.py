from paper_trader import advisor
from scripts.render_status_page import advisor_section


def _watch():
    row = lambda s, held, sig, price=100.0: {"symbol": s, "held": held, "signal": sig, "price": price, "bar_date": "2026-10-26", "d1": 0, "d5": 0}
    return {"markets": {
        "US": {"rows": [row("AAA", False, "BREAKOUT"), row("BBB", True, "needs +3.0% to break 20d high"), row("CCC", False, "x")]},
        "INDIA": {"rows": [row("RELIANCE", False, "QUALIFIES")]},
        "CRYPTO": {"rows": [row("BTCUSDT", True, "BREAKOUT")]},
        "COMMODITIES": {"rows": [row("GLD", False, "not eligible: below SMA200")]}}}


def test_ticker_mapping():
    assert advisor.ticker_for("INDIA", "TCS") == "TCS.NS"
    assert advisor.ticker_for("CRYPTO", "BTCUSDT") == "BTC-USD"
    assert advisor.ticker_for("US", "AAPL") == "AAPL"


def test_select_held_first_round_robin_and_cap():
    plan = advisor.select(_watch(), max_n=4)
    assert [p["symbol"] for p in plan] == ["BBB", "RELIANCE", "BTCUSDT", "AAA"]  # one per market first, held before signal
    assert all(p["symbol"] != "CCC" and p["symbol"] != "GLD" for p in advisor.select(_watch(), 10))
    assert len(advisor.select(_watch(), 2)) == 2


def test_parse_rating():
    assert advisor.parse_rating("**Rating**: Underweight\n...") == "Underweight"
    assert advisor.parse_rating(" Buy") == "Buy"
    assert advisor.parse_rating("garbage") is None
    assert advisor.parse_rating("") is None


def test_record_dedupes_skips_errors_and_scoreboard_measures_forward_return():
    res = [{"market": "US", "symbol": "AAA", "decision": "Buy", "price": 100.0, "held": False, "rule_signal": "BREAKOUT", "summary": "s"},
           {"market": "US", "symbol": "BBB", "decision": "Sell", "price": 100.0, "held": True, "rule_signal": "x"},
           {"market": "US", "symbol": "CCC", "error": "boom"}]
    log = advisor.record(None, res, "2026-10-26")
    log = advisor.record(log, res, "2026-10-26")  # same day again: no duplicates
    assert [e["symbol"] for e in log["entries"]] == ["AAA", "BBB"]
    w = _watch()
    w["markets"]["US"]["rows"][0]["price"] = 110.0
    sb = advisor.scoreboard(log, w)
    assert sb["bullish"]["calls"] == 1 and abs(sb["bullish"]["avg_ret"] - 10.0) < 1e-9
    assert sb["bearish"]["calls"] == 1 and sb["bearish"]["avg_ret"] == 0.0 and sb["neutral"]["calls"] == 0


def test_agreement_and_dashboard_card():
    log = advisor.record(None, [{"market": "US", "symbol": "AAA", "decision": "Buy", "price": 100.0,
                                 "rule_signal": "BREAKOUT"}], "2026-10-26")
    assert advisor.agrees(log["entries"][0]) == "agrees with rule"
    html = advisor_section(advisor.view(log, _watch()))
    assert "TradingAgents advisor" in html and "AAA" in html and "log-only" in html and "agrees with rule" in html
    assert advisor_section(advisor.view(None, None)) == ""


def test_dashboard_script_runs_standalone_like_the_status_workflow(tmp_path):
    """Regression (2026-10-27): status.yml runs `python scripts/render_status_page.py`, where `paper_trader` is NOT importable;
    an import inside advisor_section crashed the job and froze the dashboard for a day. Run it exactly that way."""
    import json
    import subprocess
    import sys
    from pathlib import Path

    log = advisor.record(None, [{"market": "US", "symbol": "AAA", "decision": "Buy", "price": 100.0,
                                 "rule_signal": "BREAKOUT"}], "2026-10-26")
    pos = {"symbol": "AAA", "quantity": 1.0, "entry_price": 100.0, "current_price": 101.0, "invested": 100.0,
           "current_value": 101.0, "unrealized_pnl": 1.0, "unrealized_pnl_pct": 1.0}
    acct = {"total_value": 101.0, "total_return_pct": 1.0, "capital": 1.0, "positions_value": 100.0, "num_trades": 0,
            "win_rate": 0.0, "positions": [pos], "realized_pnl": 0.0, "num_closed": 0, "closed_trades": [], "recent_orders": []}
    status = {"US": acct, "ADVISOR": advisor.view(log, _watch()), "WATCH": _watch()}
    script = Path(__file__).resolve().parents[1] / "scripts" / "render_status_page.py"
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": ""}
    r = subprocess.run([sys.executable, str(script)], input=json.dumps(status).encode(), cwd=tmp_path, env=env,
                       capture_output=True)
    assert r.returncode == 0, r.stderr.decode()[-500:]
    assert "TradingAgents advisor" in (tmp_path / "public" / "index.html").read_text()

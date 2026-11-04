import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_status_page.py"
ACCT = {"total_value": 97.0, "total_return_pct": -3.0, "capital": 1.0, "positions_value": 96.0, "num_trades": 0, "win_rate": 0,
        "positions": [], "realized_pnl": 0.0, "num_closed": 0, "closed_trades": [], "recent_orders": []}


def _render(tmp_path, env=None):
    r = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps({"US": ACCT}).encode(), cwd=tmp_path,
                       env={"PATH": "/usr/bin:/bin", **(env or {})}, capture_output=True)
    assert r.returncode == 0, r.stderr.decode()[-400:]
    return (tmp_path / "public" / "index.html").read_text()


def test_refresh_button_age_and_repo_constants(tmp_path):
    html = _render(tmp_path, {"GITHUB_REPOSITORY": "someone/else", "GITHUB_REF_NAME": "main"})
    assert 'id="rf"' in html and 'id="age"' in html and 'data-ts="' in html
    assert 'var REPO="someone/else", REF="main"' in html
    # market data must be refreshed BEFORE the dashboard run (the page reads the saved market_watch state)
    assert html.index("dispatch('market-watch.yml'") < html.index("dispatch('status.yml'")


def test_no_token_ever_embedded_and_defaults(tmp_path):
    html = _render(tmp_path, {"SECRET_TOKEN": "ghp_SHOULD_NOT_APPEAR"})
    assert "ghp_" not in html and 'REPO="absailor30/paper-trader"' in html


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_script_is_valid_javascript(tmp_path):
    js = re.findall(r"<script>(.*?)</script>", _render(tmp_path), re.S)[0]
    f = tmp_path / "page.js"
    f.write_text(js)
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

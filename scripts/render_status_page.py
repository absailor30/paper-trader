"""
Renders the JSON from `python run.py status` (stdin) into a static HTML
dashboard at public/index.html for GitHub Pages. No Claude session
involved -- runs entirely inside status.yml on GitHub's own schedule,
so it can't be dropped when a Claude Code session restarts (the
failure mode that made the previous claude.ai-Artifact-based dashboard
unreliable).

Usage: python run.py status | python scripts/render_status_page.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

CCY = {"CRYPTO": "$", "US": "$", "INDIA": "₹"}


def money(ccy, n):
    if n is None:
        return "—"
    sign = "-" if n < 0 else ""
    return f"{sign}{ccy}{abs(n):,.2f}"


def pct(n):
    if n is None:
        return "—"
    return f"{'+' if n >= 0 else ''}{n:.2f}%"


def market_card(key, label, data):
    ccy = CCY[key]
    ret = data["total_return_pct"]
    ret_class = "good" if ret > 0 else ("bad" if ret < 0 else "")
    rows = "".join(
        f"<tr><td class='sym'>{p['symbol']}</td><td class='num'>{p['quantity']}</td>"
        f"<td class='num'>{money(ccy, p['invested'])}</td>"
        f"<td class='num'>{money(ccy, p['current_value'])}</td>"
        f"<td class='num {'good' if p['unrealized_pnl'] > 0 else ('bad' if p['unrealized_pnl'] < 0 else '')}'>"
        f"{money(ccy, p['unrealized_pnl'])} ({pct(p['unrealized_pnl_pct'])})</td></tr>"
        for p in data["positions"]
    ) or "<tr><td colspan='5' class='empty'>No open positions.</td></tr>"
    return f"""
    <div class="card">
      <h2>{label}</h2>
      <div class="hero">
        <div class="big">{money(ccy, data['total_value'])} <span class="{ret_class}">{pct(ret)}</span></div>
        <div class="sub">cash {money(ccy, data['capital'])} &middot; in positions {money(ccy, data['positions_value'])}
        &middot; {data['num_trades']} realized trades &middot; {data['win_rate']:.0f}% win rate</div>
      </div>
      <table><thead><tr><th>Symbol</th><th class="num">Qty</th><th class="num">Invested</th>
        <th class="num">Value Now</th><th class="num">Unrealized P&amp;L</th></tr></thead>
        <tbody>{rows}</tbody></table>
    </div>"""


def main():
    status = json.load(sys.stdin)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cards = "".join(
        market_card(k, label, status[k])
        for k, label in [("CRYPTO", "Crypto — Binance spot"), ("US", "US Stocks"), ("INDIA", "India Stocks")]
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Paper Trader Status</title>
<style>
:root{{color-scheme:dark light;--bg:#0b0f1a;--surface:#131a2b;--border:#252f47;
--text:#e7ebf5;--dim:#a3adc4;--good:#3ddc84;--bad:#ff6b6b;--mono:ui-monospace,monospace}}
body{{margin:0;background:var(--bg);color:var(--text);font:14px -apple-system,sans-serif;padding:24px 16px}}
.wrap{{max-width:900px;margin:0 auto}}
h1{{font-size:20px;margin:0 0 4px}}
.asof{{color:var(--dim);font-family:var(--mono);font-size:12px;margin-bottom:20px}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:14px}}
.card h2{{font-size:14px;margin:0 0 10px}}
.hero{{margin-bottom:12px}}
.big{{font-family:var(--mono);font-size:22px;font-weight:700}}
.sub{{color:var(--dim);font-size:12px;margin-top:4px}}
.good{{color:var(--good)}} .bad{{color:var(--bad)}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th{{text-align:left;color:var(--dim);font-weight:600;padding:0 6px 6px;border-bottom:1px solid var(--border)}}
td{{padding:6px;border-bottom:1px solid var(--border)}}
.num,th.num{{text-align:right;font-family:var(--mono)}}
.sym{{font-family:var(--mono);font-weight:700}}
.empty{{color:var(--dim);text-align:center;padding:16px}}
</style></head><body><div class="wrap">
<h1>Paper Trader — Status</h1>
<div class="asof">Last updated {now} · published by GitHub Actions, no Claude session required</div>
{cards}
</div></body></html>"""
    out = Path("public")
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(html)


if __name__ == "__main__":
    main()

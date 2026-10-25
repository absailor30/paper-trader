"""
Renders the JSON from `python run.py status` (stdin) into a static HTML
dashboard at public/index.html for GitHub Pages. No Claude session
involved -- runs entirely inside status.yml on GitHub's own schedule,
so it can't be dropped when a Claude Code session restarts (the
failure mode that made the previous claude.ai-Artifact-based dashboard
unreliable).

Usage: python run.py status | python scripts/render_status_page.py
"""
import html as _html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

CCY = {"CRYPTO": "$", "US": "$", "INDIA": "₹", "COMMODITIES": "$"}


def money(ccy, n):
    if n is None:
        return "—"
    sign = "-" if n < 0 else ""
    return f"{sign}{ccy}{abs(n):,.2f}"


def pct(n):
    if n is None:
        return "—"
    return f"{'+' if n >= 0 else ''}{n:.2f}%"


def _cls(n):
    return "good" if n and n > 0 else ("bad" if n and n < 0 else "")


def qty(q):
    return f"{q:,.4f}".rstrip("0").rstrip(".") if q < 1000 else f"{q:,.0f}"


def summary_tile(key, label, data):
    ccy = CCY[key]
    ret = data["total_return_pct"]
    return (f"<div class='tile'><div class='tl'>{label}</div>"
            f"<div class='tv'>{money(ccy, data['total_value'])} <span class='{_cls(ret)}'>{pct(ret)}</span></div>"
            f"<div class='ts'>{len(data['positions'])} open &middot; realized "
            f"<span class='{_cls(data.get('realized_pnl', 0.0))}'>{money(ccy, data.get('realized_pnl', 0.0))}</span></div></div>")


def market_card(key, label, data):
    ccy = CCY[key]
    ret = data["total_return_pct"]
    rows = "".join(
        f"<tr><td class='sym'>{p['symbol']}</td><td class='num'>{qty(p['quantity'])}</td>"
        f"<td class='num'>{p['entry_price']:,.2f} → <b>{p['current_price']:,.2f}</b></td>"
        f"<td class='num'>{money(ccy, p['current_value'])}</td>"
        f"<td class='num {_cls(p['unrealized_pnl'])}'>{money(ccy, p['unrealized_pnl'])} "
        f"<span class='dim'>{pct(p['unrealized_pnl_pct'])}</span></td></tr>"
        for p in data["positions"]
    ) or "<tr><td colspan='5' class='empty'>No open positions.</td></tr>"
    closed = data.get("closed_trades", [])
    asof = f" &middot; prices as of {_html.escape(str(data['prices_as_of']))}" if data.get("prices_as_of") else ""

    def closed_row(t):
        return (f"<tr><td>{_html.escape(t['exit_date'])}</td><td class='sym'>{_html.escape(t['symbol'])}</td>"
                f"<td class='num'>{t['entry_price']:,.2f} → {t['exit_price']:,.2f}</td>"
                f"<td class='num {_cls(t['pnl'])}'>{money(ccy, t['pnl'])} <span class='dim'>{pct(t['pnl_pct'])}</span></td>"
                f"<td class='dim'>{_html.escape(t['strategy'])}</td></tr>")

    closed_head = "<thead><tr><th>Sold</th><th>Symbol</th><th class='num'>Entry → Exit</th><th class='num'>Profit / loss</th><th>Strategy</th></tr></thead>"
    closed_rows = "".join(closed_row(t) for t in closed[:3]) or \
        "<tr><td colspan='5' class='empty'>No closed trades yet — nothing has been sold.</td></tr>"
    more_closed = (f"<details><summary>{len(closed) - 3} more closed trades</summary><table>{closed_head}<tbody>"
                   f"{''.join(closed_row(t) for t in closed[3:])}</tbody></table></details>") if len(closed) > 3 else ""
    orders = data.get("recent_orders", [])
    order_rows = "".join(
        f"<tr><td>{_html.escape(o['time'])}</td><td>{_html.escape(o['side'])}</td>"
        f"<td class='sym'>{_html.escape(o['symbol'])}</td>"
        f"<td class='num'>{qty(o['quantity'])} @ {o['price']:,.2f}</td>"
        f"<td class='{'good' if o['status'] == 'FILLED' else 'bad'}'>{_html.escape(o['status'])}"
        f"{(' — ' + _html.escape(str(o['reason']))) if o['status'] != 'FILLED' and o['reason'] else ''}</td></tr>"
        for o in orders
    ) or "<tr><td colspan='5' class='empty'>No orders yet.</td></tr>"
    realized = data.get("realized_pnl", 0.0)
    return f"""
    <div class="card">
      <div class="head"><h2>{label}</h2>
        <div class="big">{money(ccy, data['total_value'])} <span class="{_cls(ret)}">{pct(ret)}</span></div></div>
      <div class="sub">cash {money(ccy, data['capital'])} &middot; invested {money(ccy, data['positions_value'])}
        &middot; {data.get('num_closed', 0)} closed &middot; {data['win_rate']:.0f}% win{asof}</div>
      <table><thead><tr><th>Symbol</th><th class="num">Qty</th><th class="num">Entry → Now</th>
        <th class="num">Value</th><th class="num">Unrealized P&amp;L</th></tr></thead><tbody>{rows}</tbody></table>
      <h3>Closed trades &mdash; realized <span class="{_cls(realized)}">{money(ccy, realized)}</span></h3>
      <table>{closed_head}<tbody>{closed_rows}</tbody></table>{more_closed}
      <details><summary>Recent orders ({len(orders)})</summary><table><thead><tr><th>Time</th><th>Side</th><th>Symbol</th>
        <th class="num">Qty @ price</th><th>Status</th></tr></thead><tbody>{order_rows}</tbody></table></details>
    </div>"""


def watch_section(watch):
    if not watch or not watch.get("markets"):
        return ""
    labels = {"US": "US Stocks", "INDIA": "India Stocks", "CRYPTO": "Crypto", "COMMODITIES": "Commodities"}
    blocks = []
    for key, block in watch["markets"].items():
        ccy = CCY.get(key, "$")

        def cell(v):
            return "<td class='num dim'>—</td>" if v is None else f"<td class='num {_cls(v)}'>{pct(v)}</td>"

        rows = "".join(
            f"<tr><td class='sym'>{'★ ' if r['held'] else ''}{_html.escape(r['symbol'])}</td>"
            f"<td class='num'>{ccy}{r['price']:,.2f}</td>{cell(r['d1'])}{cell(r['d5'])}"
            f"<td class='sig {'good' if r['signal'] in ('BREAKOUT', 'QUALIFIES') or r['signal'].startswith('in today') else 'dim'}'>"
            f"{_html.escape(r['signal'])}</td></tr>"
            for r in block["rows"]
        ) or "<tr><td colspan='5' class='empty'>No data this run.</td></tr>"
        blocks.append(
            f"<div class='card'><div class='head'><h2>{labels.get(key, key)}</h2>"
            f"<span class='dim'>bars to {_html.escape(str(block.get('as_of')))}</span></div>"
            f"<table><thead><tr><th>Symbol (★ held)</th><th class='num'>Price</th><th class='num'>1d</th>"
            f"<th class='num'>5d</th><th>Rule status</th></tr></thead><tbody>{rows}</tbody></table></div>")
    sb = watch.get("scoreboard") or {}
    def sb_row(k, v):
        pos = "—" if v["pct_positive"] is None else "%.0f%%" % v["pct_positive"]
        age = "—" if v["avg_days"] is None else "%.0fd" % v["avg_days"]
        return (f"<tr><td class='sym'>{labels.get(k, k)}</td><td class='num'>{v['signals']}</td>"
                f"<td class='num {_cls(v['avg_ret'])}'>{pct(v['avg_ret'])}</td>"
                f"<td class='num'>{pos}</td><td class='num'>{age}</td></tr>")

    sb_rows = "".join(sb_row(k, v) for k, v in sb.items())
    scoreboard_html = (
        "<div class='card'><div class='head'><h2>Signal scoreboard (forward results since each signal fired)</h2></div>"
        "<table><thead><tr><th>Market</th><th class='num'>Signals</th><th class='num'>Avg return since</th>"
        "<th class='num'>% positive</th><th class='num'>Avg age</th></tr></thead>"
        f"<tbody>{sb_rows}</tbody></table></div>") if sb else ""
    return (f"<h1 class='sec'>Market watch &mdash; every symbol, held or not "
            f"<span class='dim'>(refreshed {_html.escape(str(watch.get('generated')))})</span></h1>"
            f"<div class='grid'>{scoreboard_html}{''.join(blocks)}</div>")


def main():
    status = json.load(sys.stdin)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    accounts = [(k, label, status[k]) for k, label in
                [("US", "US Stocks"), ("INDIA", "India Stocks"), ("CRYPTO", "Crypto — Binance spot"),
                 ("COMMODITIES", "Commodities — rotation top 3")] if k in status]
    accounts += [(k, f"Jev (AI) — {k}", data) for k, data in status.get("JEV", {}).items()]
    watch_html = watch_section(status.get("WATCH"))
    tiles = "".join(summary_tile(*a) for a in accounts)
    cards = "".join(market_card(*a) for a in accounts)
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Paper Trader Status</title>
<style>
:root{{color-scheme:dark light;--bg:#0b0f1a;--surface:#131a2b;--border:#252f47;
--text:#e7ebf5;--dim:#a3adc4;--good:#3ddc84;--bad:#ff6b6b;--mono:ui-monospace,monospace}}
body{{margin:0;background:var(--bg);color:var(--text);font:13px -apple-system,sans-serif;padding:14px 16px}}
.wrap{{max-width:1500px;margin:0 auto}}
h1{{font-size:17px;margin:0}}
.asof{{color:var(--dim);font-family:var(--mono);font-size:11px;margin:2px 0 10px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px;margin-bottom:10px}}
.tile{{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:8px 10px}}
.tl{{color:var(--dim);font-size:11px}} .tv{{font-family:var(--mono);font-size:16px;font-weight:700;margin:2px 0}}
.ts{{color:var(--dim);font-size:11px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:10px;align-items:start}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 12px}}
.head{{display:flex;justify-content:space-between;align-items:baseline;gap:8px}}
.card h2{{font-size:13px;margin:0}}
.card h3{{font-size:11.5px;margin:10px 0 4px;color:var(--dim)}}
.big{{font-family:var(--mono);font-size:15px;font-weight:700}}
.sub{{color:var(--dim);font-size:11px;margin:2px 0 6px}}
.good{{color:var(--good)}} .bad{{color:var(--bad)}} .dim{{color:var(--dim)}}
table{{width:100%;border-collapse:collapse;font-size:11.5px}}
th{{text-align:left;color:var(--dim);font-weight:600;padding:0 4px 3px;border-bottom:1px solid var(--border)}}
td{{padding:3px 4px;border-bottom:1px solid var(--border)}}
.num,th.num{{text-align:right;font-family:var(--mono)}}
.sym{{font-family:var(--mono);font-weight:700}}
.empty{{color:var(--dim);text-align:center;padding:6px}}
details{{margin-top:6px}} summary{{cursor:pointer;color:var(--dim);font-size:11.5px}}
h1.sec{{font-size:14px;margin:18px 0 8px}}
.sig{{font-size:11px}}
@media(max-width:480px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">
<h1>Paper Trader — Status</h1>
<div class="asof">Last updated {now} · published by GitHub Actions, no Claude session required</div>
<div class="tiles">{tiles}</div>
<div class="grid">{cards}</div>
{watch_html}
</div></body></html>"""
    out = Path("public")
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(html)


if __name__ == "__main__":
    main()

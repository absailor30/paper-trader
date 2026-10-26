"""
TradingAgents (TauricResearch) as a LOG-ONLY forward advisor. It never places an order and never changes a rule:
each day it reviews held symbols plus symbols with an active rule signal, and its rating is stored next to the rule
status and the price, so after weeks we can see whether its calls beat the rules' (forward results only, no backtest).
Pure functions here; the LLM run itself is scripts/advisor_run.py (isolated step: has the NVIDIA key, no DB access).
"""
from typing import Dict, List, Optional

import pandas as pd

from paper_trader.watch import is_active

STATE_KEY = "advisor_log"
FAMILY = {"buy": "bullish", "overweight": "bullish", "hold": "neutral", "underweight": "bearish", "sell": "bearish"}


def ticker_for(market: str, symbol: str) -> str:
    if market == "INDIA":
        return f"{symbol}.NS"
    if market == "CRYPTO":
        return symbol.removesuffix("USDT") + "-USD"
    return symbol


def select(watch: dict, max_n: int = 6) -> List[dict]:
    """Held symbols first, then active signals; round-robin across markets so one market cannot use the whole budget."""
    queues = []
    for market, block in watch.get("markets", {}).items():
        rows = [r for r in block["rows"] if r["held"] or is_active(r["signal"])]
        rows.sort(key=lambda r: (not r["held"], r["symbol"]))
        queues.append([{"market": market, "symbol": r["symbol"], "ticker": ticker_for(market, r["symbol"]),
                        "held": r["held"], "rule_signal": r["signal"], "price": r["price"],
                        "bar_date": r["bar_date"]} for r in rows])
    out = []
    while len(out) < max_n and any(queues):
        for q in queues:
            if q and len(out) < max_n:
                out.append(q.pop(0))
    return out


def parse_rating(decision: str) -> Optional[str]:
    """First recognised word of TradingAgents' decision ('Underweight', '**Rating**: Buy', ...)."""
    low = (decision or "").lower()
    best = None
    for word in FAMILY:
        i = low.find(word)
        if i != -1 and (best is None or i < best[0]):
            best = (i, word)
    return best[1].capitalize() if best else None


def record(log: Optional[dict], results: List[dict], today: str) -> dict:
    log = log or {"entries": []}
    seen = {(e["date"], e["market"], e["symbol"]) for e in log["entries"]}
    for r in results:
        if r.get("error") or (today, r["market"], r["symbol"]) in seen:
            continue
        rating = parse_rating(r.get("decision", ""))
        if rating:
            log["entries"].append({
                "date": today, "market": r["market"], "symbol": r["symbol"], "rating": rating,
                "family": FAMILY[rating.lower()], "price": r.get("price"), "held": r.get("held", False),
                "rule_signal": r.get("rule_signal", ""), "summary": (r.get("summary") or "")[:500]})
    log["entries"] = log["entries"][-3000:]
    return log


def scoreboard(log: Optional[dict], watch: dict) -> dict:
    """Return since each call, grouped by the advisor's stance (bullish / neutral / bearish)."""
    last = {(m, r["symbol"]): (r["price"], r["bar_date"]) for m, b in watch.get("markets", {}).items() for r in b["rows"]}
    groups: Dict[str, list] = {"bullish": [], "neutral": [], "bearish": []}
    for e in (log or {}).get("entries", []):
        cur = last.get((e["market"], e["symbol"]))
        if cur and e.get("price"):
            groups[e["family"]].append((cur[0] / e["price"] - 1) * 100)
    return {f: {"calls": len(v), "avg_ret": sum(v) / len(v) if v else None,
                "pct_positive": 100 * sum(1 for x in v if x > 0) / len(v) if v else None} for f, v in groups.items()}


def view(log: Optional[dict], watch: Optional[dict], recent: int = 10) -> dict:
    entries = (log or {}).get("entries", [])
    return {"recent": list(reversed(entries[-recent:])), "total": len(entries),
            "scoreboard": scoreboard(log, watch or {})}


def agrees(entry: dict) -> str:
    rule_on = is_active(entry.get("rule_signal", ""))
    bullish, bearish = entry["family"] == "bullish", entry["family"] == "bearish"
    if rule_on and bullish:
        return "agrees with rule"
    if rule_on and bearish:
        return "disagrees (rule says go)"
    if entry.get("held") and bearish:
        return "wants out (held)"
    return ""

"""
One-off rebalance of an existing account toward confidence-scaled position sizes.

Each HELD symbol's target = portfolio value * position_pct(confidence, market) (see confidence.py),
floored at the bottom of the size ramp (5%) so a rebalance NEVER closes a position. Over-weight positions are partly sold, under-weight ones topped up (SELLs
first so the cash exists), everything else stays as cash for new signals. Orders carry
deterministic ids so a re-run on the same day is a no-op. Dry-run by default.
"""
import math
from datetime import date
from typing import Any, Dict, List, Optional

from paper_trader.config import settings
from paper_trader.confidence import _ramp, position_pct
from paper_trader.execution.paper_trader import PaperTrader
from paper_trader.notify import notify_order

STRATEGY = "Rebalance"


def _floor4(x: float) -> float:
    return math.floor(x * 10_000) / 10_000


def plan(trader: PaperTrader, prices: Dict[str, float], confidences: Dict[str, float], india: bool = False,
         market: str = "US") -> Dict[str, Any]:
    trader.update_prices({s: p for s, p in prices.items() if s in trader.portfolio.positions})
    value = trader.portfolio.total_value
    slip, com = trader.slippage_rate, trader.commission_rate
    rows: List[Dict[str, Any]] = []
    for symbol, pos in trader.portfolio.positions.items():
        price = prices.get(symbol, pos["current_price"])
        frac = max(position_pct(confidences.get(symbol), market), _ramp(0.0))
        target = value * frac
        current = pos["quantity"] * price
        qty = 0.0
        if current > target:
            qty = (current - target) / (price * (1 - slip) * (1 - com))
            qty = math.floor(qty) if india else _floor4(qty)
            qty = min(qty, pos["quantity"] - (1 if india else 0.0001))  # never close the position
            side = "SELL"
        else:
            qty = (target - current) / (price * (1 + slip) * (1 + com))
            qty = math.floor(qty) if india else _floor4(qty)
            side = "BUY"
        if qty <= 0 or qty * price < settings.min_position_value:
            side, qty = "HOLD", 0.0
        rows.append({"symbol": symbol, "price": price, "confidence": confidences.get(symbol), "target_pct": frac,
                     "current_value": current, "target_value": target, "side": side, "quantity": qty})
    rows.sort(key=lambda r: {"SELL": 0, "BUY": 1, "HOLD": 2}[r["side"]])
    return {"portfolio_value": value, "cash_before": trader.portfolio.capital, "rows": rows}


def execute(trader: PaperTrader, rebalance_plan: Dict[str, Any], label: str, day: Optional[str] = None) -> List[dict]:
    day = day or date.today().isoformat()
    orders = []
    for r in rebalance_plan["rows"]:
        if r["side"] == "HOLD":
            continue
        qty = r["quantity"]
        if r["side"] == "BUY":
            cost_per_unit = r["price"] * (1 + trader.slippage_rate) * (1 + trader.commission_rate)
            qty = min(qty, _floor4(max(0.0, trader.portfolio.capital) / cost_per_unit))
            if qty <= 0 or qty * r["price"] < settings.min_position_value:
                continue
        order = trader.place_order(f"REBAL:{day}:{r['symbol']}:{r['side']}", r["symbol"], r["side"], qty, r["price"],
                                   STRATEGY, reasoning=f"rebalance to {r['target_pct']:.1%} of the account (confidence {r['confidence']:.2f})"
                                   if r["confidence"] is not None else "rebalance to the floor size")
        notify_order(label, order)
        orders.append(order)
    return orders

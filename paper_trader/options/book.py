"""Paper options account: cash, long option positions, orders, closed trades. Buys fill at the ask, sells at the bid, a per-contract
commission each side. Quantities are in CONTRACTS internally; the status view reports share-equivalents (x100) so the dashboard math works."""
from datetime import datetime
from typing import Dict, List, Optional

from paper_trader.config import settings
from paper_trader.options.selection import MULTIPLIER
from paper_trader.persistence.state_store import load_state, save_state

STATE_KEY = "options_portfolio"
STRATEGY = "Options_Long_On_Signal"


def label(symbol: str, pos: dict) -> str:
    kind = "C" if pos["kind"] == "call" else "P"
    strike = f"{pos['strike']:g}"
    return f"{pos['underlying']} {strike}{kind} {pos['expiry'][5:]}"


class OptionsBook:
    def __init__(self, capital: Optional[float] = None):
        self.initial = capital if capital is not None else settings.options_capital
        self.cash = self.initial
        self.positions: Dict[str, dict] = {}
        self.trades: List[dict] = []
        self.orders: List[dict] = []
        self.processed: set = set()

    # ---- persistence -------------------------------------------------------------------------
    def load(self) -> bool:
        st = load_state(STATE_KEY)
        if not st:
            return False
        self.cash, self.positions, self.trades = st["cash"], st["positions"], st["trades"]
        self.orders, self.processed = st["orders"], set(st["processed"])
        return True

    def save(self) -> None:
        save_state(STATE_KEY, {"cash": self.cash, "positions": self.positions, "trades": self.trades,
                               "orders": self.orders, "processed": sorted(self.processed)})

    # ---- accounting --------------------------------------------------------------------------
    @property
    def positions_value(self) -> float:
        return sum(p["contracts"] * p["mark"] * MULTIPLIER for p in self.positions.values())

    @property
    def total_value(self) -> float:
        return self.cash + self.positions_value

    def update_marks(self, marks: Dict[str, float]) -> None:
        for sym, m in marks.items():
            if sym in self.positions and m is not None and m > 0:
                self.positions[sym]["mark"] = float(m)

    def _order(self, order_id, side, symbol, contracts, price, commission, reason, status="FILLED"):
        o = {"client_order_id": order_id, "side": side, "symbol": symbol, "contracts": contracts, "price": price,
             "commission": commission, "reason": reason, "status": status, "timestamp": datetime.now().isoformat()}
        self.orders.append(o)
        return o

    def buy(self, order_id: str, c: dict, kind: str, underlying: str, expiry: str, spot: float, contracts: int = 1) -> dict:
        if order_id in self.processed:
            return next(o for o in self.orders if o["client_order_id"] == order_id)
        self.processed.add(order_id)
        commission = contracts * settings.options_commission_per_contract
        cost = contracts * c["ask"] * MULTIPLIER + commission
        if cost > self.cash + 1e-6:
            return self._order(order_id, "BUY", c["contract"], contracts, c["ask"], commission, "Insufficient capital", "REJECTED")
        self.cash -= cost
        self.positions[c["contract"]] = {
            "underlying": underlying, "kind": kind, "strike": c["strike"], "expiry": expiry, "contracts": contracts,
            "entry_price": c["ask"], "mark": c["mid"], "entry_time": datetime.now().isoformat(), "entry_spot": spot,
            "entry_cost": cost}
        return self._order(order_id, "BUY", c["contract"], contracts, c["ask"], commission,
                           f"{kind} on {underlying} signal, delta {c['delta']:.2f}")

    def sell(self, order_id: str, symbol: str, price: float, reason: str, commission: bool = True) -> Optional[dict]:
        if order_id in self.processed or symbol not in self.positions:
            return None
        self.processed.add(order_id)
        pos = self.positions.pop(symbol)
        comm = pos["contracts"] * settings.options_commission_per_contract if commission else 0.0
        proceeds = pos["contracts"] * price * MULTIPLIER - comm
        self.cash += proceeds
        pnl = proceeds - pos["entry_cost"]
        self.trades.append({"symbol": symbol, "label": label(symbol, pos), "entry_time": pos["entry_time"],
                            "exit_time": datetime.now().isoformat(), "entry_price": pos["entry_price"], "exit_price": price,
                            "contracts": pos["contracts"], "pnl": pnl, "pnl_pct": pnl / pos["entry_cost"] * 100 if pos["entry_cost"] else 0.0,
                            "reason": reason})
        o = self._order(order_id, "SELL", symbol, pos["contracts"], price, comm, reason)
        o["pnl"], o["pnl_pct"] = pnl, self.trades[-1]["pnl_pct"]
        o["label"] = label(symbol, pos)
        o["underlying"] = pos["underlying"]
        return o

    # ---- dashboard view (same shape the other accounts produce) -----------------------------------
    def status(self) -> dict:
        wins = [t for t in self.trades if t["pnl"] > 0]
        positions = []
        for sym, p in self.positions.items():
            shares = p["contracts"] * MULTIPLIER
            cur = p["contracts"] * p["mark"] * MULTIPLIER
            pnl = cur - p["entry_cost"]
            positions.append({"symbol": label(sym, p), "quantity": shares, "entry_price": p["entry_price"], "current_price": p["mark"],
                              "invested": p["entry_cost"], "current_value": cur, "unrealized_pnl": pnl,
                              "unrealized_pnl_pct": pnl / p["entry_cost"] * 100 if p["entry_cost"] else 0.0})
        # sells carry the label themselves; buys are looked up from open positions or the trade log
        names = {t["symbol"]: t["label"] for t in self.trades}
        names.update({s: label(s, p) for s, p in self.positions.items()})
        executed = []
        for o in reversed(self.orders):
            if o["status"] != "FILLED":
                continue
            shares = o["contracts"] * MULTIPLIER
            executed.append({"time": o["timestamp"][:16].replace("T", " "), "side": o["side"],
                             "symbol": o.get("label") or names.get(o["symbol"], o["symbol"]), "quantity": shares, "price": o["price"],
                             "value": shares * o["price"], "commission": o["commission"], "strategy": STRATEGY,
                             "pnl": o.get("pnl"), "pnl_pct": o.get("pnl_pct")})
        closed = [{"symbol": t["label"], "entry_date": t["entry_time"][:10], "exit_date": t["exit_time"][:10],
                   "entry_price": t["entry_price"], "exit_price": t["exit_price"], "quantity": t["contracts"] * MULTIPLIER,
                   "pnl": t["pnl"], "pnl_pct": t["pnl_pct"], "strategy": STRATEGY, "reason": t["reason"]}
                  for t in reversed(self.trades[-15:])]
        recent = [{"time": o["timestamp"][:16].replace("T", " "), "side": o["side"], "symbol": names.get(o["symbol"], o["symbol"]),
                   "quantity": o["contracts"] * MULTIPLIER, "price": o["price"], "status": o["status"], "reason": o["reason"]}
                  for o in reversed(self.orders[-15:])]
        return {"market": "OPTIONS", "total_value": self.total_value,
                "total_return_pct": (self.total_value - self.initial) / self.initial * 100, "capital": self.cash,
                "positions_value": self.positions_value, "num_trades": len(self.trades),
                "win_rate": 100 * len(wins) / len(self.trades) if self.trades else 0.0, "positions": positions,
                "closed_trades": closed, "realized_pnl": sum(t["pnl"] for t in self.trades), "num_closed": len(self.trades),
                "recent_orders": recent, "executed": executed[:300]}

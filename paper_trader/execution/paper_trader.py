"""
Paper trading engine. Every order is keyed by a caller-supplied
client_order_id; placing the same client_order_id twice is a no-op that
returns the original result, not a second fill. This is what "idempotent
by construction" means in practice — a retried cron run, a double-fired
webhook, or a crash-and-resume can never double-execute a trade.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from paper_trader.persistence.state_store import load_state, save_state


@dataclass
class Portfolio:
    capital: float
    positions: Dict[str, dict] = field(default_factory=dict)
    trade_history: List[dict] = field(default_factory=list)
    processed_order_ids: List[str] = field(default_factory=list)
    daily_pnl: float = 0.0

    @property
    def positions_value(self) -> float:
        return sum(p["quantity"] * p["current_price"] for p in self.positions.values())

    @property
    def total_value(self) -> float:
        return self.capital + self.positions_value


class PaperTrader:
    def __init__(self, initial_capital: float, commission_rate: float, slippage_rate: float):
        self.portfolio = Portfolio(capital=initial_capital)
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.orders: List[dict] = []
        self.daily_start_value = initial_capital
        self._order_results: Dict[str, dict] = {}

    def place_order(
        self,
        client_order_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        strategy: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        reasoning: str = "",
    ) -> dict:
        if client_order_id in self._order_results:
            logger.info(f"Order {client_order_id} already processed; returning cached result")
            return self._order_results[client_order_id]

        effective_price = price * (1 + self.slippage_rate) if side == "BUY" else price * (1 - self.slippage_rate)
        commission = quantity * effective_price * self.commission_rate

        order = {
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": effective_price,
            "raw_price": price,
            "commission": commission,
            "strategy": strategy,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reasoning": reasoning,
            "timestamp": datetime.now().isoformat(),
            "status": "FILLED",
        }

        if side == "BUY":
            total_cost = quantity * effective_price + commission
            if total_cost > self.portfolio.capital:
                order["status"] = "REJECTED"
                order["reason"] = "Insufficient capital"
                logger.warning(f"Insufficient capital for {symbol}: need {total_cost:.2f}, have {self.portfolio.capital:.2f}")
            else:
                self.portfolio.capital -= total_cost
                self.portfolio.positions[symbol] = {
                    "quantity": quantity,
                    "entry_price": effective_price,
                    "current_price": effective_price,
                    "highest_price": effective_price,
                    "entry_time": datetime.now().isoformat(),
                    "strategy": strategy,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                }

        elif side == "SELL":
            position = self.portfolio.positions.get(symbol)
            if position is None:
                order["status"] = "REJECTED"
                order["reason"] = "No position"
                logger.warning(f"No position in {symbol} to sell")
            else:
                gross_proceeds = quantity * effective_price
                net_proceeds = gross_proceeds - commission
                cost_basis = position["entry_price"] * quantity
                net_pnl = net_proceeds - cost_basis

                self.portfolio.capital += net_proceeds
                self.portfolio.daily_pnl += net_pnl

                self.portfolio.trade_history.append({
                    "symbol": symbol,
                    "entry_price": position["entry_price"],
                    "exit_price": effective_price,
                    "quantity": quantity,
                    "commission": commission,
                    "pnl": net_pnl,
                    "pnl_pct": (net_pnl / cost_basis * 100) if cost_basis > 0 else 0.0,
                    "strategy": strategy,
                    "entry_time": position["entry_time"],
                    "exit_time": datetime.now().isoformat(),
                    "reasoning": reasoning,
                })

                if quantity >= position["quantity"]:
                    del self.portfolio.positions[symbol]
                else:
                    position["quantity"] -= quantity

        self.orders.append(order)
        self.portfolio.processed_order_ids.append(client_order_id)
        self._order_results[client_order_id] = order
        logger.info(f"{side} {quantity} {symbol} @ {effective_price:.2f} - {order['status']} [{client_order_id}]")
        return order

    def update_prices(self, prices: Dict[str, float]):
        for symbol, price in prices.items():
            pos = self.portfolio.positions.get(symbol)
            if pos:
                pos["current_price"] = price
                pos["highest_price"] = max(pos.get("highest_price", price), price)

    def get_performance_metrics(self) -> dict:
        total_return = (self.portfolio.total_value - self.initial_capital) / self.initial_capital * 100
        daily_return = (self.portfolio.total_value - self.daily_start_value) / self.daily_start_value * 100

        trades = self.portfolio.trade_history
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] < 0]
        win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
        profit_factor = (
            abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses))
            if losses and sum(t["pnl"] for t in losses) != 0
            else 0.0
        )

        return {
            "total_value": self.portfolio.total_value,
            "capital": self.portfolio.capital,
            "positions_value": self.portfolio.positions_value,
            "total_return_pct": total_return,
            "daily_return_pct": daily_return,
            "daily_pnl": self.portfolio.daily_pnl,
            "num_positions": len(self.portfolio.positions),
            "num_trades": len(trades),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
        }

    def save(self, key: str) -> None:
        save_state(key, {
            "capital": self.portfolio.capital,
            "positions": self.portfolio.positions,
            "trade_history": self.portfolio.trade_history,
            "processed_order_ids": self.portfolio.processed_order_ids,
            "daily_pnl": self.portfolio.daily_pnl,
            "orders": self.orders,
        })

    def load(self, key: str) -> bool:
        """Returns True if state was found and loaded, False if this is a fresh start."""
        state = load_state(key)
        if state is None:
            return False
        self.portfolio.capital = state["capital"]
        self.portfolio.positions = state["positions"]
        self.portfolio.trade_history = state["trade_history"]
        self.portfolio.processed_order_ids = state["processed_order_ids"]
        self.portfolio.daily_pnl = state.get("daily_pnl", 0.0)
        self.orders = state["orders"]
        self._order_results = {o["client_order_id"]: o for o in self.orders}
        return True

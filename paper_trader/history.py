"""Trade journal view of a PaperTrader: every closed trade with its realized P&L,
plus recent orders (fills AND rejections), newest first. Read-only."""
from typing import Any, Dict

from paper_trader.execution.paper_trader import PaperTrader


def history_view(trader: PaperTrader, limit: int = 15) -> Dict[str, Any]:
    hist = trader.portfolio.trade_history
    wins = [t["pnl"] for t in hist if t["pnl"] > 0]
    losses = [t["pnl"] for t in hist if t["pnl"] < 0]
    closed = [{
        "symbol": t["symbol"], "entry_date": str(t["entry_time"])[:10], "exit_date": str(t["exit_time"])[:10],
        "entry_price": t["entry_price"], "exit_price": t["exit_price"], "quantity": t["quantity"],
        "pnl": t["pnl"], "pnl_pct": t["pnl_pct"], "strategy": t["strategy"], "reason": t.get("reasoning", ""),
    } for t in reversed(hist[-limit:])]
    orders = [{
        "time": str(o["timestamp"])[:16].replace("T", " "), "side": o["side"], "symbol": o["symbol"],
        "quantity": o["quantity"], "price": o["price"], "status": o["status"],
        "reason": o.get("reason") or o.get("reasoning", ""),
    } for o in reversed(trader.orders[-limit:])]
    return {
        "closed_trades": closed,
        "realized_pnl": sum(t["pnl"] for t in hist),
        "num_closed": len(hist),
        "avg_win": (sum(wins) / len(wins)) if wins else None,
        "avg_loss": (sum(losses) / len(losses)) if losses else None,
        "recent_orders": orders,
    }

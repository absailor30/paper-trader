"""Read-only plain-text report of every paper account: cash, open positions, closed trades, recent orders.
Never fetches prices, never trades (unlike `run.py status`, which also runs stop checks)."""
from paper_trader.crypto_orchestrator import CryptoTradingBot
from paper_trader.jev_trader import jev_status
from paper_trader.orchestrator import TradingBot


def show(name, st, ccy):
    print(f"\n=== {name}: total {ccy}{st['total_value']:,.2f} ({st['total_return_pct']:+.2f}%), cash {ccy}{st['capital']:,.2f}, "
          f"positions {ccy}{st['positions_value']:,.2f}, realized P&L {ccy}{st['realized_pnl']:+,.2f} over {st['num_closed']} closed trades")
    for p in st["positions"]:
        print(f"  OPEN  {p['symbol']:10s} qty {p['quantity']:<12} invested {ccy}{p['invested']:>9,.2f}  now {ccy}{p['current_value']:>9,.2f}  "
              f"({p['unrealized_pnl_pct']:+.2f}%)")
    for t in st["closed_trades"]:
        print(f"  SOLD  {t['symbol']:10s} {t['entry_date']} -> {t['exit_date']}  {t['entry_price']:,.2f} -> {t['exit_price']:,.2f}  "
              f"P&L {ccy}{t['pnl']:+,.2f} ({t['pnl_pct']:+.2f}%)  [{t['strategy']}]")
    for o in st["recent_orders"]:
        why = f" - {o['reason']}" if o["status"] != "FILLED" and o["reason"] else ""
        print(f"  ORDER {o['time']} {o['side']:4s} {o['symbol']:10s} {o['quantity']} @ {o['price']:,.2f} {o['status']}{why}")


bot = TradingBot()
show("US", bot.get_status("US"), "$")
show("INDIA", bot.get_status("INDIA"), "Rs")
show("CRYPTO", CryptoTradingBot().get_status(), "$")
for market, st in jev_status(["US", "INDIA", "CRYPTO"]).items():
    show(f"JEV {market}", st, "Rs" if market == "INDIA" else "$")

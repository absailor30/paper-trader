"""
Jev as a decision-maker: buy / sell / hold, with its OWN paper accounts.

Per market (US, INDIA, CRYPTO) Jev gets a separate paper portfolio funded like
the rule-based one (same capital, same commission/slippage, same engine), so
its results are directly comparable and the rule-based track record stays
clean. Each daily cycle, for every symbol it is asked one typed yes/no
question: held -> "close it now?", flat -> "open a long now?". Jev decides;
this module only executes and enforces guardrails that are NOT Jev's call:
hard ATR stop, daily-loss / drawdown circuit breaker, minimum position value,
max open positions, long-only, no leverage. Orders honour AUTO_EXECUTE.

"Learning": Jev's weights do not change. What it can do is condition on its own
history, so every question includes its track record (overall and for that
symbol) from the portfolio's closed trades. Any real fine-tuning would have to
come from TypeSafe's side; that is unverified.

Safety: no-ops without TYPESAFE_API_KEY; a failed/None answer means HOLD.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

from paper_trader import jev, orchestrator
from paper_trader.config import settings
from paper_trader.data.binance_fetcher import BinanceFetcher
from paper_trader.data.fetcher import DataFetcher
from paper_trader.execution.paper_trader import PaperTrader
from paper_trader.notify import notify_circuit_breaker, notify_order
from paper_trader.orchestrator import _floor4, size_position
from paper_trader.persistence.state_store import load_state, save_state
from paper_trader.shadow import _completed_bars
from paper_trader.strategy.indicators import atr, donchian_high, rsi, sma

LOG_KEY = "jev_trader_log"
LOG_CAP = 600
STRATEGY = "Jev_Decision"
BUY_QUESTION = (
    "You manage a small long-only paper portfolio and may hold for days to weeks. Based on the state "
    "below, should you OPEN a new long position in this symbol now?"
)
SELL_QUESTION = (
    "You manage a small long-only paper portfolio and currently HOLD this symbol (details below). "
    "Should you CLOSE the position now?"
)


def market_config(market: str) -> Dict[str, Any]:
    if market == "CRYPTO":
        return {"symbols": settings.crypto_pairs, "capital": settings.crypto_capital, "india": False}
    return orchestrator.MARKETS[market]


def _pct(a: float, b: float) -> str:
    return f"{(a / b - 1) * 100:+.1f}%" if b and not pd.isna(a) and not pd.isna(b) else "n/a"


def snapshot(market: str, symbol: str, df: pd.DataFrame) -> str:
    close = df["close"]
    price = float(close.iloc[-1])
    n = len(close)

    def back(k: int) -> str:
        return _pct(price, float(close.iloc[-1 - k])) if n > k else "n/a"

    def vs_sma(k: int) -> str:
        return _pct(price, float(sma(close, k).iloc[-1])) if n >= k else "n/a"

    atr_now = atr(df["high"], df["low"], close, settings.atr_period).iloc[-1] if n > settings.atr_period + 1 else float("nan")
    rsi_now = rsi(close, settings.rsi_period).iloc[-1] if n > settings.rsi_period + 1 else float("nan")
    hi20 = donchian_high(df["high"], 20).iloc[-1] if n > 21 else float("nan")
    hi55 = donchian_high(df["high"], 55).iloc[-1] if n > 56 else float("nan")
    vol20 = close.pct_change().tail(20).std() * 100 if n > 21 else float("nan")
    vol_ratio = (df["volume"].iloc[-1] / df["volume"].tail(20).mean()) if "volume" in df and n >= 20 and df["volume"].tail(20).mean() else float("nan")
    return "\n".join([
        f"Market: {market}; symbol: {symbol}; last completed bar: {df.index[-1].date()}; close: {price:.4f}",
        f"Returns: 5d {back(5)}, 20d {back(20)}, 60d {back(60)}, 126d {back(126)}",
        f"Price vs SMA20 {vs_sma(20)}, SMA50 {vs_sma(50)}, SMA100 {vs_sma(100)}, SMA200 {vs_sma(200)}",
        f"RSI14: {rsi_now:.0f}; ATR14: {atr_now / price * 100:.1f}% of price; 20d daily-return stdev: {vol20:.1f}%; "
        f"volume vs 20d avg: {vol_ratio:.2f}x",
        f"Distance to prior 20d high: {_pct(hi20, price)}; to prior 55d high: {_pct(hi55, price)}",
    ])


def track_record(trader: PaperTrader, symbol: str) -> str:
    hist = trader.portfolio.trade_history
    if not hist:
        return "Your track record: no closed trades yet."
    wins = [t for t in hist if t["pnl"] > 0]
    avg = sum(t["pnl_pct"] for t in hist) / len(hist)
    last = ", ".join(f"{t['symbol']} {t['pnl_pct']:+.1f}%" for t in hist[-5:])
    mine = [t for t in hist if t["symbol"] == symbol][-3:]
    per_symbol = "; ".join(f"{t['pnl_pct']:+.1f}%" for t in mine) or "none"
    return (f"Your track record: {len(hist)} closed trades, {len(wins) / len(hist) * 100:.0f}% winners, "
            f"avg net {avg:+.1f}% per trade. Last 5: {last}. Your past trades in {symbol}: {per_symbol}.")


def position_text(position: Dict[str, Any], price: float) -> str:
    try:
        days = (datetime.now() - datetime.fromisoformat(position["entry_time"])).days
    except Exception:
        days = -1
    return (f"You hold {position['quantity']} units, entry {position['entry_price']:.4f}, now {price:.4f} "
            f"({_pct(price, position['entry_price'])}), held ~{days} days, hard stop {position['stop_loss']:.4f}.")


class JevTrader:
    def __init__(self, client: Any = None, noul_cls: Any = None, fetcher: Optional[DataFetcher] = None,
                 crypto_fetcher: Optional[BinanceFetcher] = None):
        self.client, self.noul_cls = client, noul_cls
        self.fetcher = fetcher or DataFetcher()
        self.crypto_fetcher = crypto_fetcher or BinanceFetcher(market="spot")

    def active(self) -> bool:
        return jev.enabled() or self.client is not None

    def _fetch(self, market: str, cfg: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        start = (datetime.now() - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
        if market == "CRYPTO":
            data = self.crypto_fetcher.fetch_many(cfg["symbols"], start_date=start)
            data = {s: _completed_bars(df) for s, df in data.items()}
            return {s: df for s, df in data.items() if not df.empty}
        return self.fetcher.fetch_many(cfg["symbols"], start_date=start, india=cfg["india"])

    def _ask(self, state: str, question: str) -> Optional[float]:
        return jev.ask(state, client=self.client, noul_cls=self.noul_cls, question=question)

    def run_market(self, market: str) -> Dict[str, Any]:
        if not self.active():
            return {"market": market, "disabled": "TYPESAFE_API_KEY not set"}
        cfg = market_config(market)
        trader = PaperTrader(cfg["capital"], settings.commission_rate, settings.slippage_rate)
        key = f"jev_{market.lower()}_portfolio"
        trader.load(key)
        label = f"JEV {market}"
        data = self._fetch(market, cfg)
        trader.update_prices({s: float(df["close"].iloc[-1]) for s, df in data.items()})
        log = load_state(LOG_KEY) or {"decisions": []}
        actions: List[dict] = []
        asked = failed = 0

        def record(symbol, bar_date, kind, p, acted):
            log["decisions"].append({"ts": datetime.now(timezone.utc).isoformat(), "market": market, "symbol": symbol,
                                     "bar_date": bar_date, "kind": kind, "p": p, "acted": acted})

        def execute(symbol, side, qty, price, bar_date, reason, stop=None):
            if not settings.auto_execute:
                actions.append({"action": f"PROPOSED_{side}", "symbol": symbol, "price": price, "quantity": qty, "reason": reason})
                return None
            order = trader.place_order(f"JEV:{market}:{symbol}:{bar_date}:{side}", symbol, side, qty, price,
                                       STRATEGY, stop_loss=stop, reasoning=reason)
            notify_order(label, order)
            actions.append({"action": "EXECUTED", **order})
            return order

        for symbol, pos in list(trader.portfolio.positions.items()):
            df = data.get(symbol)
            if df is None or df.empty:
                continue
            price, bar_date = float(df["close"].iloc[-1]), str(df.index[-1].date())
            if pos.get("stop_loss") and price <= pos["stop_loss"]:
                record(symbol, bar_date, "hard_stop", None, True)
                execute(symbol, "SELL", pos["quantity"], price, bar_date, "hard ATR stop (guardrail, not Jev)")
                continue
            state = "\n".join([snapshot(market, symbol, df), position_text(pos, price), track_record(trader, symbol)])
            p = self._ask(state, SELL_QUESTION)
            asked += 1
            if p is None:
                failed += 1
                continue
            sell = p >= settings.jev_sell_threshold
            record(symbol, bar_date, "sell?", p, sell)
            if sell:
                execute(symbol, "SELL", pos["quantity"], price, bar_date, f"Jev p(close)={p:.2f}")

        metrics = trader.get_performance_metrics()
        breaker = (metrics["daily_return_pct"] < -settings.max_daily_loss * 100
                   or metrics["total_return_pct"] < -settings.max_drawdown * 100)
        if breaker:
            notify_circuit_breaker(label, "daily-loss/drawdown limit reached")
        elif len(trader.portfolio.positions) < settings.jev_max_positions:
            candidates = []
            for symbol, df in data.items():
                if symbol in trader.portfolio.positions or df.empty:
                    continue
                state = "\n".join([snapshot(market, symbol, df), "You are flat in this symbol.", track_record(trader, symbol)])
                p = self._ask(state, BUY_QUESTION)
                asked += 1
                if p is None:
                    failed += 1
                    continue
                bar_date = str(df.index[-1].date())
                record(symbol, bar_date, "buy?", p, False)
                if p >= settings.jev_buy_threshold:
                    candidates.append((p, symbol, df))
            for p, symbol, df in sorted(candidates, key=lambda c: -c[0]):
                if len(trader.portfolio.positions) >= settings.jev_max_positions:
                    break
                price, bar_date = float(df["close"].iloc[-1]), str(df.index[-1].date())
                qty = size_position(trader, price, india=cfg["india"])
                if not cfg["india"]:
                    conf = min(1.0, (p - settings.jev_buy_threshold) / max(1e-9, 1 - settings.jev_buy_threshold))
                    qty = _floor4(qty * (0.5 + 0.5 * conf))
                if qty <= 0 or qty * price < settings.min_position_value:
                    continue
                atr_now = atr(df["high"], df["low"], df["close"], settings.atr_period).iloc[-1]
                stop = price - settings.atr_stop_multiple * atr_now if not pd.isna(atr_now) else price * 0.85
                if stop <= 0 or stop >= price:
                    stop = price * 0.85
                record(symbol, bar_date, "buy", p, True)
                execute(symbol, "BUY", qty, price, bar_date, f"Jev p(open)={p:.2f}", stop=stop)

        log["decisions"] = log["decisions"][-LOG_CAP:]
        save_state(LOG_KEY, log)
        trader.save(key)
        m = trader.get_performance_metrics()
        return {"market": market, "executed": settings.auto_execute, "asked": asked, "failed_asks": failed,
                "circuit_breaker": breaker, "actions": actions, "open_positions": sorted(trader.portfolio.positions),
                "total_value": m.get("total_value"), "total_return_pct": m.get("total_return_pct")}

    def run(self, markets: List[str]) -> Dict[str, Any]:
        return {m: self.run_market(m) for m in markets}


def jev_status(markets: List[str]) -> Dict[str, Any]:
    """Saved Jev account snapshots (same shape as TradingBot.get_status) for the dashboard."""
    out: Dict[str, Any] = {}
    for market in markets:
        cfg = market_config(market)
        trader = PaperTrader(cfg["capital"], settings.commission_rate, settings.slippage_rate)
        if not trader.load(f"jev_{market.lower()}_portfolio"):
            continue
        positions = []
        for symbol, p in trader.portfolio.positions.items():
            positions.append({
                "symbol": symbol, "quantity": p["quantity"], "invested": p["entry_price"] * p["quantity"],
                "current_value": p["current_price"] * p["quantity"],
                "unrealized_pnl": (p["current_price"] - p["entry_price"]) * p["quantity"],
                "unrealized_pnl_pct": (p["current_price"] / p["entry_price"] - 1) * 100 if p["entry_price"] else 0.0,
            })
        out[market] = {**trader.get_performance_metrics(), "positions": positions}
    return out

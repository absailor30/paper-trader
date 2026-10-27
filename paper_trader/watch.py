"""
Market watch: what EVERY symbol in every universe is doing, held or not -- price, 1-day / 5-day move,
and how close it is to triggering that market's live rule. Read-only: never places an order.
`python run.py watch` fetches, saves the table under state key `market_watch` (the dashboard reads it
and the status job stays cheap), and with --digest sends one Telegram summary.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

from paper_trader.config import settings
from paper_trader.strategy.commodity_rotation import rotation_targets
from paper_trader.strategy.indicators import donchian_high, sma

STATE_KEY = "market_watch"
LABELS = {"US": "US Stocks", "INDIA": "India Stocks", "CRYPTO": "Crypto", "COMMODITIES": "Commodities"}


def _pct(a: float, b: float) -> Optional[float]:
    return (a / b - 1) * 100 if b else None


def base_row(symbol: str, df: pd.DataFrame, held: bool) -> dict:
    close = df["close"]
    price = float(close.iloc[-1])
    return {
        "symbol": symbol, "price": price, "held": held, "bar_date": str(df.index[-1].date()),
        "d1": _pct(price, float(close.iloc[-2])) if len(close) > 1 else None,
        "d5": _pct(price, float(close.iloc[-6])) if len(close) > 5 else None,
        "ret126": _pct(price, float(close.iloc[-127])) if len(close) > 126 else None,
    }


def donchian_state(df: pd.DataFrame, entry: int, trend: Optional[int]) -> str:
    if len(df) < max(entry, trend or 0) + 2:
        return "not enough history"
    price = float(df["close"].iloc[-1])
    high = float(donchian_high(df["high"], entry).iloc[-1])  # same channel the live strategy uses
    below_trend = bool(trend) and price <= float(sma(df["close"], trend).iloc[-1])
    if price > high:
        return f"breakout blocked: below SMA{trend}" if below_trend else "BREAKOUT"
    text = f"needs +{_pct(high, price):.1f}% to break {entry}d high"
    return text + f" · below SMA{trend}" if below_trend else text


def momentum_state(df: pd.DataFrame, lookback: int, min_ret: float, sma_n: int) -> str:
    if len(df) <= max(lookback, sma_n) + 1:
        return "not enough history"
    price = float(df["close"].iloc[-1])
    ret = price / float(df["close"].iloc[-1 - lookback]) - 1
    above = price > float(sma(df["close"], sma_n).iloc[-1])
    if ret >= min_ret and above:
        return "QUALIFIES"
    why = []
    if ret < min_ret:
        why.append(f"{lookback}d return {ret * 100:+.1f}% (< {min_ret * 100:.0f}%)")
    if not above:
        why.append(f"below SMA{sma_n}")
    return " · ".join(why)


def commodity_states(data: Dict[str, pd.DataFrame]) -> Dict[str, str]:
    close = pd.DataFrame({s: d["close"] for s, d in data.items()}).sort_index().ffill(limit=3)
    picks = rotation_targets(close)
    out = {}
    for s in close:
        ret = _pct(float(close[s].iloc[-1]), float(close[s].iloc[-127])) if len(close) > 126 else None
        above = len(close) > 200 and float(close[s].iloc[-1]) > float(close[s].rolling(200).mean().iloc[-1])
        if s in picks:
            out[s] = f"in today's top {len(picks)} (#{picks.index(s) + 1}); rebalances monthly"
        elif ret is not None and ret > 0 and above:
            out[s] = "eligible, outside top 3"
        else:
            out[s] = "not eligible: " + ("126d return ≤ 0" if (ret is None or ret <= 0) else "below SMA200")
    return out


def build(market: str, data: Dict[str, pd.DataFrame], held: set, strategy=None) -> List[dict]:
    rows = []
    cstate = commodity_states(data) if market == "COMMODITIES" and data else {}
    for symbol, df in data.items():
        if df is None or df.empty or len(df) < 2:
            continue
        row = base_row(symbol, df, symbol in held)
        if market == "COMMODITIES":
            row["signal"] = cstate.get(symbol, "")
        elif market == "INDIA":
            row["signal"] = momentum_state(df, strategy.lookback, strategy.min_ret, strategy.sma_n)
        else:
            row["signal"] = donchian_state(df, strategy.entry_period, strategy.trend_filter_period)
        rows.append(row)
    rows.sort(key=lambda r: (not r["held"], -(r["d1"] if r["d1"] is not None else -999)))
    return rows


def _ist(utc_text: str) -> str:
    """'2026-10-27 22:25 UTC' -> '2026-10-28 03:55 IST' (user reads IST); unparseable input is returned as is."""
    from datetime import timedelta
    try:
        dt = datetime.strptime(str(utc_text).replace(" UTC", "").strip()[:16], "%Y-%m-%d %H:%M") + timedelta(hours=5, minutes=30)
    except ValueError:
        return str(utc_text)
    return dt.strftime("%Y-%m-%d %H:%M") + " IST"


def digest_text(watch: dict) -> str:
    lines = [f"📊 <b>Daily market watch</b> ({_ist(watch.get('generated', ''))})"]
    for market, block in watch.get("markets", {}).items():
        rows = block["rows"]
        if not rows:
            lines.append(f"\n<b>{LABELS.get(market, market)}</b>: no data")
            continue
        moved = sorted((r for r in rows if r["d1"] is not None), key=lambda r: r["d1"])
        best, worst = moved[-1], moved[0]
        ready = [r["symbol"] for r in rows if r["signal"] in ("BREAKOUT", "QUALIFIES") or r["signal"].startswith("in today")]
        held = [r["symbol"] for r in rows if r["held"]]
        lines.append(
            f"\n<b>{LABELS.get(market, market)}</b> (bars to {block.get('as_of')}): "
            f"best {best['symbol']} {best['d1']:+.1f}%, worst {worst['symbol']} {worst['d1']:+.1f}%"
            f"\n  held: {', '.join(held) or 'none'} · signal now: {', '.join(ready) or 'none'}"
        )
    return "\n".join(lines)


SIGNAL_KEY = "signal_log"
ACTIVE = ("BREAKOUT", "QUALIFIES")


def is_active(signal: str) -> bool:
    return signal in ACTIVE or signal.startswith("in today")


def log_signals(watch: dict, log: Optional[dict]) -> dict:
    """Record every NEW signal (inactive -> active transition, so a multi-day streak counts once) with its price."""
    log = log or {"active": {}, "entries": []}
    for market, block in watch["markets"].items():
        for r in block["rows"]:
            key, active = f"{market}:{r['symbol']}", is_active(r["signal"])
            if active and not log["active"].get(key):
                log["entries"].append({"market": market, "symbol": r["symbol"], "date": r["bar_date"],
                                       "price": r["price"], "signal": r["signal"]})
            log["active"][key] = active
    log["entries"] = log["entries"][-5000:]
    return log


def scoreboard(log: Optional[dict], watch: dict) -> dict:
    """Return since each logged signal, measured to the latest price. Forward results only (no backtest, no leakage)."""
    out = {}
    for market, block in watch["markets"].items():
        last = {r["symbol"]: (r["price"], r["bar_date"]) for r in block["rows"]}
        rets, days = [], []
        for e in (log or {}).get("entries", []):
            if e["market"] != market or e["symbol"] not in last or not e["price"]:
                continue
            price, bar = last[e["symbol"]]
            rets.append((price / e["price"] - 1) * 100)
            days.append((pd.Timestamp(bar) - pd.Timestamp(e["date"])).days)
        out[market] = {
            "signals": len(rets), "avg_ret": sum(rets) / len(rets) if rets else None,
            "pct_positive": 100 * sum(1 for x in rets if x > 0) / len(rets) if rets else None,
            "avg_days": sum(days) / len(days) if days else None,
        }
    return out


def run(digest: bool = False) -> dict:
    from datetime import timedelta

    from paper_trader.crypto_orchestrator import CryptoTradingBot
    from paper_trader.data.binance_fetcher import BinanceFetcher
    from paper_trader.data.fetcher import DataFetcher
    from paper_trader.execution.paper_trader import PaperTrader
    from paper_trader.notify import send_telegram_message
    from paper_trader.orchestrator import TradingBot
    from paper_trader.persistence.state_store import load_state, save_state
    from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy
    from paper_trader.strategy.momentum_trend import MomentumTrend

    start = (datetime.now() - timedelta(days=450)).strftime("%Y-%m-%d")

    def held(key: str) -> set:
        t = PaperTrader(1.0, settings.commission_rate, settings.slippage_rate)
        t.load(key)
        return set(t.portfolio.positions)

    fx = DataFetcher()
    plan = {
        "US": (lambda: fx.fetch_many(settings.us_stocks, start_date=start), "us_portfolio", DonchianBreakoutStrategy(trend_filter_period=100)),
        "INDIA": (lambda: fx.fetch_many(settings.india_stocks, start_date=start, india=True), "india_portfolio", MomentumTrend(126, 0.10, 50)),
        "CRYPTO": (lambda: BinanceFetcher(market="spot").fetch_many(settings.crypto_pairs, start_date=start), "crypto_portfolio",
                   DonchianBreakoutStrategy(entry_period=20, exit_period=10, trend_filter_period=None)),
        "COMMODITIES": (lambda: fx.fetch_many(settings.commodities, start_date=start), "commodities_portfolio", None),
    }
    markets = {}
    for market, (fetch, key, strategy) in plan.items():
        try:
            rows = build(market, fetch(), held(key), strategy)
        except Exception as e:  # one market failing must not blank the others
            rows = []
            from loguru import logger
            logger.error(f"watch {market} failed: {e}")
        markets[market] = {"rows": rows, "as_of": max((r["bar_date"] for r in rows), default=None)}
    watch = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "markets": markets}
    log = log_signals(watch, load_state(SIGNAL_KEY))
    save_state(SIGNAL_KEY, log)
    watch["scoreboard"] = scoreboard(log, watch)
    save_state(STATE_KEY, watch)
    if digest:
        send_telegram_message(digest_text(watch))
    return watch

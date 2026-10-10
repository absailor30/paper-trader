"""
LOG-ONLY second opinion from TypeSafe's Jev decision model on live signals.

Jev never influences a trade: for every signal the live strategies produce,
this asks one yes/no question ("will this trade hit its take-profit before
its stop within 20 trading days?"), stores the probability next to the
signal, and later resolves the real outcome from price data. `run.py
jev-report` then scores calibration (Brier vs. a constant base-rate guess).
Nothing here can be validated by a backtest (the model may have seen the
history), so forward logging is the only honest test; it needs dozens of
resolved signals before it says anything.

Safety: no-ops without TYPESAFE_API_KEY, imports the SDK lazily, and every
public function swallows its own errors so a Jev outage can never break a
trading cycle. The SDK call shape (TypeSafeClient.system_one(state=...,
questions={...}) with a Noul yes/no question, answer read from `.noul`) was
taken from third-party guides, NOT official docs -- keep it confined to
_load_sdk()/ask() and verify on the first real run.
"""
import importlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

from paper_trader.config import settings
from paper_trader.persistence.state_store import load_state, save_state

STATE_KEY = "jev_log"
HORIZON_BARS = 20
QUESTION = (
    "This long trade was just signalled. Will price reach the take-profit level before "
    "falling to the stop-loss level within the next 20 trading days?"
)


def enabled() -> bool:
    return bool(settings.typesafe_api_key)


def _load_sdk():
    for module_name in ("typesafe", "typesafe_sdk"):
        try:
            mod = importlib.import_module(module_name)
            return mod.TypeSafeClient, mod.Noul
        except Exception:
            continue
    logger.warning("Jev: typesafe-sdk is not importable (pip install typesafe-sdk); skipping Jev opinions")
    return None


def ask(state_text: str, client: Any = None, noul_cls: Any = None, question: str = QUESTION) -> Optional[float]:
    """Probability of 'yes' for `question` given state_text, or None on any failure."""
    try:
        if client is None:
            sdk = _load_sdk()
            if sdk is None:
                return None
            client_cls, noul_cls = sdk
            client = client_cls()
        resp = client.system_one(state=state_text, questions={"followthrough": noul_cls(instructions=question)})
        return float(resp.answers["followthrough"].noul)
    except Exception as e:
        logger.warning(f"Jev ask failed: {e}")
        return None


def build_state(market: str, symbol: str, strategy: str, signal: Any, df: pd.DataFrame) -> str:
    close = df["close"]

    def ret(n: int) -> str:
        return f"{(close.iloc[-1] / close.iloc[-1 - n] - 1) * 100:+.1f}%" if len(close) > n else "n/a"

    risk = signal.price - signal.stop_loss
    reward = signal.take_profit - signal.price
    return "\n".join([
        f"Market: {market}; symbol: {symbol}; strategy: {strategy}; bar date: {df.index[-1].date()}",
        f"Entry price: {signal.price:.4f}; stop-loss: {signal.stop_loss:.4f} ({-risk / signal.price * 100:.1f}%); "
        f"take-profit: {signal.take_profit:.4f} (+{reward / signal.price * 100:.1f}%)",
        f"Signal reason: {signal.reasoning}",
        f"Trailing returns: 5d {ret(5)}, 20d {ret(20)}, 60d {ret(60)}, 126d {ret(126)}",
        f"Price vs SMA50: {(close.iloc[-1] / close.tail(50).mean() - 1) * 100:+.1f}%" if len(close) >= 50 else "Price vs SMA50: n/a",
    ])


def _load() -> Dict[str, Any]:
    return load_state(STATE_KEY) or {"records": []}


def observe(market: str, symbol: str, strategy: str, signal: Any, df: pd.DataFrame, client: Any = None, noul_cls: Any = None) -> None:
    """Log Jev's probability for one live signal (idempotent per symbol+bar)."""
    if not enabled() and client is None:
        return
    try:
        bar_date = str(df.index[-1].date())
        rec_id = f"{market}:{symbol}:{bar_date}"
        state = _load()
        if any(r["id"] == rec_id for r in state["records"]):
            return
        p = ask(build_state(market, symbol, strategy, signal, df), client=client, noul_cls=noul_cls)
        if p is None:
            return
        state["records"].append({
            "id": rec_id, "market": market, "symbol": symbol, "strategy": strategy,
            "bar_date": bar_date, "entry": float(signal.price), "stop": float(signal.stop_loss),
            "take_profit": float(signal.take_profit), "p_yes": p,
            "logged_at": datetime.now(timezone.utc).isoformat(), "outcome": None,
        })
        save_state(STATE_KEY, state)
        logger.info(f"Jev (log-only): {rec_id} p(follow-through)={p:.2f}")
    except Exception as e:
        logger.warning(f"Jev observe failed: {e}")


def _resolve(rec: Dict[str, Any], df: pd.DataFrame) -> Optional[str]:
    """win = take-profit touched first, loss = stop touched first (same bar counts as loss),
    timeout = neither within HORIZON_BARS; None if still open."""
    after = df[df.index.normalize() > pd.Timestamp(rec["bar_date"], tz=df.index.tz)].head(HORIZON_BARS)
    for _, bar in after.iterrows():
        if bar["low"] <= rec["stop"]:
            return "loss"
        if bar["high"] >= rec["take_profit"]:
            return "win"
    return "timeout" if len(after) >= HORIZON_BARS else None


def update(market: str, data: Dict[str, pd.DataFrame]) -> None:
    """Resolve outcomes for this market's open records using the cycle's fresh price data."""
    if not enabled():
        return
    try:
        state = _load()
        changed = False
        for rec in state["records"]:
            if rec["outcome"] is not None or rec["market"] != market:
                continue
            df = data.get(rec["symbol"])
            if df is None or df.empty:
                continue
            outcome = _resolve(rec, df)
            if outcome:
                rec["outcome"] = outcome
                changed = True
        if changed:
            save_state(STATE_KEY, state)
    except Exception as e:
        logger.warning(f"Jev update failed: {e}")


def report() -> Dict[str, Any]:
    records: List[Dict[str, Any]] = _load()["records"]
    resolved = [r for r in records if r["outcome"] is not None]
    out: Dict[str, Any] = {"logged": len(records), "resolved": len(resolved)}
    if not resolved:
        out["verdict"] = "no resolved signals yet"
        return out
    y = [1.0 if r["outcome"] == "win" else 0.0 for r in resolved]
    base = sum(y) / len(y)
    brier = sum((r["p_yes"] - yi) ** 2 for r, yi in zip(resolved, y)) / len(y)
    brier_base = sum((base - yi) ** 2 for yi in y) / len(y)
    buckets = {}
    for name, lo, hi in (("p<0.4", 0, 0.4), ("0.4<=p<0.6", 0.4, 0.6), ("p>=0.6", 0.6, 1.01)):
        sel = [yi for r, yi in zip(resolved, y) if lo <= r["p_yes"] < hi]
        buckets[name] = {"n": len(sel), "win_rate": (sum(sel) / len(sel)) if sel else None}
    out.update({
        "base_rate_win": base, "brier_jev": brier, "brier_constant_base_rate": brier_base,
        "buckets": buckets,
        "verdict": ("insufficient data (<30 resolved), do not act on this" if len(resolved) < 30
                    else ("Jev beats the constant base rate" if brier < brier_base else "Jev does NOT beat the constant base rate")),
    })
    return out

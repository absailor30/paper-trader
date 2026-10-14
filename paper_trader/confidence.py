"""
Confidence mechanism: a transparent 0..1 score for how favourable a symbol's
current price picture is, used to scale position size (never to create
entries -- the validated strategies still decide WHAT to buy).

  score = 0.30 * trend + 0.30 * momentum + 0.20 * strength + 0.20 * calm
    trend    : 0.5 if close > SMA50, +0.5 if close > SMA200 (SMA50 twice if <200 bars)
    momentum : 126-day return / 30%, clamped 0..1 (negative = 0); 60d/15% if <127 bars
    strength : where close sits inside its last-20-day high/low range, 0..1
    calm     : 1 at ATR <= 1% of price, falling to 0 at ATR >= 6% of price

Size = settings.max_position_size * size_fraction(score): below
settings.confidence_min the trade is skipped; at 1.0 it gets the full 12%;
in between it scales linearly from settings.confidence_floor_fraction of 12%.
The weights are judgement, not fitted: scripts/confidence_check.py measures
on real history whether higher scores actually preceded better trades.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional

import pandas as pd

from paper_trader.config import settings
from paper_trader.strategy.indicators import atr, sma

WEIGHTS = {"trend": 0.30, "momentum": 0.30, "strength": 0.20, "calm": 0.20}


@dataclass
class Confidence:
    score: float
    parts: Dict[str, float] = field(default_factory=dict)

    def explain(self) -> str:
        bits = ", ".join(f"{k} {v:.2f}" for k, v in self.parts.items())
        return f"confidence {self.score:.2f} ({bits})"


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def rule_confidence(df: pd.DataFrame) -> Confidence:
    close = df["close"]
    n = len(close)
    if n < 30:
        return Confidence(0.5, {"note": 0.5})  # not enough history to say anything: neutral
    price = float(close.iloc[-1])

    sma50 = sma(close, 50).iloc[-1] if n >= 50 else close.mean()
    sma200 = sma(close, 200).iloc[-1] if n >= 200 else sma50
    trend = 0.5 * (price > sma50) + 0.5 * (price > sma200)

    if n > 126:
        momentum = _clamp((price / float(close.iloc[-127]) - 1) / 0.30)
    elif n > 60:
        momentum = _clamp((price / float(close.iloc[-61]) - 1) / 0.15)
    else:
        momentum = 0.5

    hi20, lo20 = float(df["high"].tail(20).max()), float(df["low"].tail(20).min())
    strength = _clamp((price - lo20) / (hi20 - lo20)) if hi20 > lo20 else 0.5

    atr_now = atr(df["high"], df["low"], close, settings.atr_period).iloc[-1]
    atr_pct = float(atr_now) / price if price and not pd.isna(atr_now) else 0.03
    calm = 1 - _clamp((atr_pct - 0.01) / 0.05)

    parts = {"trend": float(trend), "momentum": momentum, "strength": strength, "calm": calm}
    return Confidence(sum(WEIGHTS[k] * v for k, v in parts.items()), parts)


def blend(rule: float, jev_p: Optional[float]) -> float:
    """Average the rule score with Jev's probability when Jev answered; otherwise the rule score alone."""
    return rule if jev_p is None else 0.5 * rule + 0.5 * jev_p


def size_fraction(confidence: Optional[float]) -> float:
    """Share of the base position size (max_position_size) that this confidence earns; 0 = skip."""
    if confidence is None:
        return 1.0
    if confidence < settings.confidence_min:
        return 0.0
    span = max(1e-9, 1 - settings.confidence_min)
    floor = settings.confidence_floor_fraction
    return min(1.0, floor + (1 - floor) * (confidence - settings.confidence_min) / span)

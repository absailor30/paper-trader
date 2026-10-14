"""
Confidence mechanism: a transparent 0..1 score for how favourable a symbol's
current price picture is, used to scale position size (never to create
entries -- the validated strategies still decide WHAT to buy).

  score = 0.30 * trend + 0.30 * momentum + 0.20 * strength + 0.20 * calm
    trend    : 0.5 if close > SMA50, +0.5 if close > SMA200 (SMA50 twice if <200 bars)
    momentum : 126-day return / 30%, clamped 0..1 (negative = 0); 60d/15% if <127 bars
    strength : where close sits inside its last-20-day high/low range, 0..1
    calm     : 1 at ATR <= 1% of price, falling to 0 at ATR >= 6% of price

Position size (share of the portfolio) comes from a smooth ramp, not steps:
    0.30 -> 5%,  0.55 -> 10%,  0.70 -> 12%,  0.90 -> 12%,  1.00 -> 15%     (below 0.30: skip)
which is the user's tier idea (30-50% -> 5%, 50-60% -> 10%, 60-89% -> 12%, 90%+ -> up to
15%) with the cliffs removed and the top capped at 15% instead of 20%. How much of the ramp
each market may use follows what real history showed (scripts/confidence_check.py):
    CRYPTO : full ramp (the score predicted outcomes there: rho +0.12, win 37% -> 53%)
    INDIA  : ramp but never above the 12% base (weak evidence)
    US     : flat 12% (the score did NOT predict outcomes there; it was slightly inverted)
    COMMODITIES : flat 12% (the rotation rule was validated at flat 12%; confidence untested there)
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


def _ramp(confidence: float) -> float:
    knots = [(0.30, 0.05), (0.55, 0.10), (0.70, settings.max_position_size),
             (0.90, settings.max_position_size), (1.00, settings.confidence_max_size)]
    if confidence <= knots[0][0]:
        return knots[0][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if confidence <= x1:
            return y0 + (y1 - y0) * (confidence - x0) / (x1 - x0)
    return knots[-1][1]


MARKET_POLICY = {"CRYPTO": "ramp", "INDIA": "down_only", "US": "flat", "COMMODITIES": "flat"}


def position_pct(confidence: Optional[float], market: str = "US") -> float:
    """Share of the portfolio to put in one new position; 0.0 = skip. confidence=None means full base size."""
    base = settings.max_position_size
    if confidence is None:
        return base
    if confidence < settings.confidence_min:
        return 0.0
    policy = MARKET_POLICY.get(market, "down_only")
    if policy == "flat":
        return base
    pct = _ramp(confidence)
    return min(pct, base) if policy == "down_only" else pct

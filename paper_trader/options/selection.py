"""Pick ONE contract from one expiry's chain: liquid, delta in a band, affordable. Returns (contract | None, info);
info always says why nothing was chosen, so a day of 'nothing affordable' is visible instead of silent."""
from datetime import date
from typing import Optional, Tuple

import pandas as pd

from paper_trader.options.pricing import bs_delta

MULTIPLIER = 100


def select_contract(chain: pd.DataFrame, spot: float, is_call: bool, today: date, expiry: date, budget: float, *,
                    min_oi: int = 50, max_spread: float = 0.35, min_delta: float = 0.25, max_delta: float = 0.65,
                    rate: float = 0.04) -> Tuple[Optional[dict], dict]:
    years = max((expiry - today).days, 0) / 365.0
    liquid = []
    for r in chain.itertuples():
        bid, ask = getattr(r, "bid", None), getattr(r, "ask", None)
        if bid is None or ask is None or pd.isna(bid) or pd.isna(ask) or bid <= 0 or ask <= 0 or ask < bid:
            continue
        mid = (bid + ask) / 2
        spread = (ask - bid) / mid
        oi = getattr(r, "openInterest", 0)
        oi = 0 if pd.isna(oi) else int(oi)
        iv = getattr(r, "impliedVolatility", None)
        if oi < min_oi or spread > max_spread or iv is None or pd.isna(iv):
            continue
        delta = bs_delta(spot, float(r.strike), years, rate, float(iv), is_call)
        if delta is None:
            continue
        liquid.append({"contract": str(r.contractSymbol), "strike": float(r.strike), "bid": float(bid), "ask": float(ask),
                       "mid": mid, "spread": spread, "oi": oi, "iv": float(iv), "delta": abs(delta), "cost": float(ask) * MULTIPLIER})
    if not liquid:
        return None, {"reason": "no liquid contracts (open interest / spread filter)"}
    band = [c for c in liquid if min_delta <= c["delta"] <= max_delta]
    if not band:
        return None, {"reason": f"no liquid contract with delta {min_delta}-{max_delta}"}
    cheapest = min(c["cost"] for c in band)
    ok = [c for c in band if c["cost"] <= budget]
    if not ok:
        return None, {"reason": f"too expensive: cheapest suitable contract costs ${cheapest:,.0f}, budget ${budget:,.0f}",
                      "cheapest_cost": cheapest}
    return max(ok, key=lambda c: c["delta"]), {"reason": "ok", "cheapest_cost": cheapest}

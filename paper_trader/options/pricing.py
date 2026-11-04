import math


def _cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_delta(spot: float, strike: float, years: float, rate: float, vol: float, is_call: bool):
    """Black-Scholes delta (yfinance gives no greeks). None when inputs make it meaningless."""
    if spot <= 0 or strike <= 0 or years <= 0 or vol <= 0:
        return None
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * years) / (vol * math.sqrt(years))
    return _cdf(d1) if is_call else _cdf(d1) - 1.0

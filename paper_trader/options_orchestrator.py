"""
US options paper pipeline (user's choice 2026-11-05: US only, long calls/puts on rule signals, $100 paper account).

  entry : bullish signal on a US-universe stock (live US rule: Donchian breakout + SMA100) -> buy a call;
          bearish signal (close below the prior 20-day low AND below SMA100; an UNTESTED rule) -> buy a put.
          Contract: expiry 30-60 DTE closest to 45, liquid (open interest / spread), BS delta 0.25-0.65, affordable
          (one contract may use up to `options_max_cost_fraction` of the account); highest delta that fits.
  exits : premium -50% (stop) / +100% (take profit) / <= 7 DTE / underlying breaks its 10-day channel against the position /
          expired (settled at intrinsic).
Forward paper test ONLY: free data has no historical option chains, so there is no backtest and nothing is proven.
Every candidate that was skipped is logged with the reason (most days at $100 will be 'too expensive').
Honours AUTO_EXECUTE and the drawdown breaker (entries only).
"""
from datetime import date, datetime, timedelta
from typing import List, Optional, Protocol

import pandas as pd
from loguru import logger

from paper_trader.config import settings
from paper_trader.data.fetcher import DataFetcher
from paper_trader.notify import notify_circuit_breaker
from paper_trader.options.book import OptionsBook, label
from paper_trader.options.selection import MULTIPLIER, select_contract
from paper_trader.strategy.donchian_breakout import DonchianBreakoutStrategy
from paper_trader.strategy.indicators import donchian_high, donchian_low, sma


class Chains(Protocol):
    def expiries(self, symbol: str) -> List[str]: ...
    def chain(self, symbol: str, expiry: str, kind: str) -> pd.DataFrame: ...


class YFChains:
    def expiries(self, symbol: str) -> List[str]:
        import yfinance as yf
        return list(yf.Ticker(symbol).options or [])

    def chain(self, symbol: str, expiry: str, kind: str) -> pd.DataFrame:
        import yfinance as yf
        ch = yf.Ticker(symbol).option_chain(expiry)
        return ch.calls if kind == "call" else ch.puts


def bullish_signal(df: pd.DataFrame) -> bool:
    return DonchianBreakoutStrategy(trend_filter_period=100).generate_signal(df) is not None


def bearish_signal(df: pd.DataFrame) -> bool:
    if len(df) < 105:
        return False
    close = df["close"]
    low20 = donchian_low(df["low"], 20).iloc[-1]
    trend = sma(close, 100).iloc[-1]
    return bool(not pd.isna(low20) and not pd.isna(trend) and close.iloc[-1] < low20 and close.iloc[-1] < trend)


def pick_expiry(expiries: List[str], today: date) -> Optional[str]:
    ok = [(abs((date.fromisoformat(e) - today).days - 45), e) for e in expiries
          if settings.options_dte_min <= (date.fromisoformat(e) - today).days <= settings.options_dte_max]
    return min(ok)[1] if ok else None


class OptionsBot:
    def __init__(self, fetcher=None, chains: Optional[Chains] = None):
        self.fetcher = fetcher or DataFetcher()
        self.chains = chains or YFChains()
        self.book = OptionsBook()
        found = self.book.load()
        logger.info(f"OPTIONS: {'loaded existing state' if found else 'starting fresh'}")

    # ---- marks / exits -----------------------------------------------------------------------------
    def _quote(self, sym: str, pos: dict):
        try:
            ch = self.chains.chain(pos["underlying"], pos["expiry"], pos["kind"])
            row = ch[ch["contractSymbol"] == sym]
            if row.empty:
                return None
            bid, ask = float(row["bid"].iloc[0]), float(row["ask"].iloc[0])
            return bid, ask
        except Exception as e:
            logger.warning(f"OPTIONS quote failed for {sym}: {type(e).__name__}")
            return None

    def mark_to_market(self) -> None:
        if not self.book.positions:
            return
        marks = {}
        for sym, pos in self.book.positions.items():
            q = self._quote(sym, pos)
            if q and q[0] > 0 and q[1] > 0:
                marks[sym] = (q[0] + q[1]) / 2
        if marks:
            self.book.update_marks(marks)
            self.book.save()

    def _underlying_exit(self, pos: dict, df: Optional[pd.DataFrame]) -> bool:
        if df is None or df.empty or len(df) < 12:
            return False
        close = float(df["close"].iloc[-1])
        if pos["kind"] == "call":
            lo = donchian_low(df["low"], 10).iloc[-1]
            return bool(not pd.isna(lo) and close < lo)
        hi = donchian_high(df["high"], 10).iloc[-1]
        return bool(not pd.isna(hi) and close > hi)

    def _exits(self, today: date, data: dict) -> List[dict]:
        actions = []
        for sym, pos in list(self.book.positions.items()):
            dte = (date.fromisoformat(pos["expiry"]) - today).days
            df = data.get(pos["underlying"])
            if dte < 0:
                spot = float(df["close"].iloc[-1]) if df is not None and not df.empty else pos["entry_spot"]
                intrinsic = max(spot - pos["strike"], 0) if pos["kind"] == "call" else max(pos["strike"] - spot, 0)
                actions.append(self._sell(sym, intrinsic, "expired (settled at intrinsic)", today, commission=False))
                continue
            q = self._quote(sym, pos)
            if q and q[0] > 0 and q[1] > 0:
                self.book.update_marks({sym: (q[0] + q[1]) / 2})
            bid = q[0] if q else 0.0
            chg = (pos["mark"] / pos["entry_price"] - 1) * 100
            reason = None
            if chg <= settings.options_stop_pct:
                reason = f"stop: premium {chg:+.0f}%"
            elif chg >= settings.options_take_profit_pct:
                reason = f"take profit: premium {chg:+.0f}%"
            elif dte <= settings.options_exit_dte:
                reason = f"{dte} days to expiry"
            elif self._underlying_exit(pos, df):
                reason = "underlying broke its 10-day channel against the position"
            if reason and bid > 0:
                actions.append(self._sell(sym, bid, reason, today))
            elif reason:
                logger.warning(f"OPTIONS {sym}: wanted to exit ({reason}) but no bid; will retry next cycle")
        return actions

    def _sell(self, sym, price, reason, today, commission=True) -> dict:
        if not settings.auto_execute:
            logger.info(f"[PROPOSE-ONLY] Would SELL {sym} @ {price:.2f}: {reason}")
            return {"action": "PROPOSED_SELL", "symbol": sym, "price": price, "reason": reason}
        o = self.book.sell(f"OPT:{today}:{sym}:SELL", sym, price, reason, commission)
        return {"action": "EXECUTED", **(o or {})}

    # ---- entries -----------------------------------------------------------------------------------
    def _breaker_ok(self) -> bool:
        ret = (self.book.total_value - self.book.initial) / self.book.initial * 100
        if ret < -settings.max_drawdown * 100:
            notify_circuit_breaker("OPTIONS", f"max drawdown reached ({ret:.2f}%)")
            return False
        return True

    def _entries(self, today: date, data: dict) -> List[dict]:
        actions = []
        if not self._breaker_ok():
            return actions
        held_underlyings = {p["underlying"] for p in self.book.positions.values()}
        for symbol, df in data.items():
            if len(self.book.positions) >= settings.options_max_positions:
                break
            if symbol in held_underlyings or df.empty:
                continue
            kind = "call" if bullish_signal(df) else ("put" if bearish_signal(df) else None)
            if kind is None:
                continue
            spot = float(df["close"].iloc[-1])
            try:
                expiry = pick_expiry(self.chains.expiries(symbol), today)
                if expiry is None:
                    actions.append({"action": "SKIPPED", "symbol": symbol, "kind": kind, "reason": "no expiry in the DTE window"})
                    continue
                chain = self.chains.chain(symbol, expiry, kind)
            except Exception as e:
                actions.append({"action": "SKIPPED", "symbol": symbol, "kind": kind, "reason": f"chain fetch failed: {type(e).__name__}"})
                continue
            budget = min(self.book.cash, self.book.total_value * settings.options_max_cost_fraction)
            contract, info = select_contract(chain, spot, kind == "call", today, date.fromisoformat(expiry), budget,
                                             min_oi=settings.options_min_open_interest, max_spread=settings.options_max_spread)
            if contract is None:
                actions.append({"action": "SKIPPED", "symbol": symbol, "kind": kind, "spot": spot, "reason": info["reason"]})
                logger.info(f"OPTIONS {symbol} {kind}: skipped, {info['reason']}")
                continue
            if not settings.auto_execute:
                actions.append({"action": "PROPOSED_BUY", "symbol": symbol, "kind": kind, "contract": contract["contract"],
                                "ask": contract["ask"], "cost": contract["cost"]})
                continue
            o = self.book.buy(f"OPT:{today}:{contract['contract']}:BUY", contract, kind, symbol, expiry, spot)
            actions.append({"action": "EXECUTED" if o["status"] == "FILLED" else "REJECTED", **o})
        return actions

    def run_cycle(self) -> List[dict]:
        today = datetime.now().date()
        start = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
        data = self.fetcher.fetch_many(settings.us_stocks, start_date=start)
        actions = self._exits(today, data) + self._entries(today, data)
        self.book.save()
        skipped = sum(1 for a in actions if a["action"] == "SKIPPED")
        logger.info(f"OPTIONS cycle: {len(actions)} actions ({skipped} skipped), cash {self.book.cash:.2f}, value {self.book.total_value:.2f}")
        return actions

    def get_status(self) -> dict:
        return self.book.status()

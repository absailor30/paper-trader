"""
Market Regime Understanding Engine
Analyzes macro benchmarks (SPY, QQQ, VIX for US; Nifty 50, India VIX for India)
to categorize market environment and autonomously dynamically select appropriate strategies.
"""
from dataclasses import dataclass
from typing import List, Dict
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
import yfinance as yf
from src.strategies.indicators import sma, rsi

@dataclass
class MarketRegime:
    market: str  # "US" or "INDIA"
    regime: str  # "BULL_MOMENTUM", "SIDEWAYS_CONSOLIDATION", "BEAR_DOWNTREND", "HIGH_VOLATILITY"
    benchmark_symbol: str
    benchmark_price: float
    sma50: float
    sma200: float
    vix_level: float
    description: str
    allowed_strategies: List[str]
    position_size_multiplier: float  # 0.0 to 1.0

class MarketRegimeDetector:
    """
    Evaluates macro market structure to prevent trading against the dominant trend.
    Blocks breakout strategies during bear markets and expands size during confirmed stage 2 uptrends.
    """

    def analyze_us_market(self) -> MarketRegime:
        """Analyze US market regime via SPY, QQQ, and VIX"""
        try:
            spy = yf.Ticker("SPY").history(period="1y")
            vix = yf.Ticker("^VIX").history(period="5d")

            vix_val = float(vix["Close"].iloc[-1]) if not vix.empty else 16.0

            if spy.empty or len(spy) < 50:
                return self._fallback_regime("US", "SPY")

            c = float(spy["Close"].iloc[-1])
            s50 = float(sma(spy["Close"], 50).iloc[-1])
            s200 = float(sma(spy["Close"], 200).iloc[-1]) if len(spy) >= 200 else s50 * 0.95

            # High volatility spike
            if vix_val > 25.0:
                return MarketRegime(
                    market="US",
                    regime="HIGH_VOLATILITY",
                    benchmark_symbol="SPY",
                    benchmark_price=c,
                    sma50=s50,
                    sma200=s200,
                    vix_level=vix_val,
                    description=f"VIX elevated at {vix_val:.1f}. High risk environment.",
                    allowed_strategies=["Mean_Reversion"],
                    position_size_multiplier=0.5
                )

            # Confirmed Bull Uptrend
            if c > s50 and s50 > s200:
                return MarketRegime(
                    market="US",
                    regime="BULL_MOMENTUM",
                    benchmark_symbol="SPY",
                    benchmark_price=c,
                    sma50=s50,
                    sma200=s200,
                    vix_level=vix_val,
                    description=f"SPY (${c:.2f}) above 50 SMA (${s50:.2f}) & 200 SMA (${s200:.2f}). Stage 2 Bull Market.",
                    allowed_strategies=["Stage_Analysis", "SEPA_VCP", "CAN_SLIM", "Momentum_RL"],
                    position_size_multiplier=1.0
                )

            # Bear Downtrend
            elif c < s50 and c < s200:
                return MarketRegime(
                    market="US",
                    regime="BEAR_DOWNTREND",
                    benchmark_symbol="SPY",
                    benchmark_price=c,
                    sma50=s50,
                    sma200=s200,
                    vix_level=vix_val,
                    description=f"SPY (${c:.2f}) below 50 SMA (${s50:.2f}) & 200 SMA. Stage 4 Bear Market. Breakouts disabled.",
                    allowed_strategies=["Mean_Reversion"],
                    position_size_multiplier=0.5
                )

            # Choppy / Sideways
            else:
                return MarketRegime(
                    market="US",
                    regime="SIDEWAYS_CONSOLIDATION",
                    benchmark_symbol="SPY",
                    benchmark_price=c,
                    sma50=s50,
                    sma200=s200,
                    vix_level=vix_val,
                    description=f"SPY (${c:.2f}) oscillating around 50 SMA (${s50:.2f}). Rangebound consolidation.",
                    allowed_strategies=["Mean_Reversion", "Momentum_RL"],
                    position_size_multiplier=0.75
                )

        except Exception as e:
            logger.error(f"Error detecting US market regime: {e}")
            return self._fallback_regime("US", "SPY")

    def analyze_india_market(self) -> MarketRegime:
        """Analyze Indian market regime via Nifty 50 (^NSEI) and India VIX"""
        try:
            nifty = yf.Ticker("^NSEI").history(period="1y")
            vix = yf.Ticker("^INDIAVIX").history(period="5d")

            vix_val = float(vix["Close"].iloc[-1]) if not vix.empty else 14.0

            if nifty.empty or len(nifty) < 50:
                return self._fallback_regime("INDIA", "^NSEI")

            c = float(nifty["Close"].iloc[-1])
            s50 = float(sma(nifty["Close"], 50).iloc[-1])
            s200 = float(sma(nifty["Close"], 200).iloc[-1]) if len(nifty) >= 200 else s50 * 0.95

            if vix_val > 22.0:
                return MarketRegime(
                    market="INDIA",
                    regime="HIGH_VOLATILITY",
                    benchmark_symbol="^NSEI",
                    benchmark_price=c,
                    sma50=s50,
                    sma200=s200,
                    vix_level=vix_val,
                    description=f"India VIX elevated at {vix_val:.1f}. Heightened volatility.",
                    allowed_strategies=["Mean_Reversion"],
                    position_size_multiplier=0.5
                )

            if c > s50 and s50 > s200:
                return MarketRegime(
                    market="INDIA",
                    regime="BULL_MOMENTUM",
                    benchmark_symbol="^NSEI",
                    benchmark_price=c,
                    sma50=s50,
                    sma200=s200,
                    vix_level=vix_val,
                    description=f"Nifty 50 ({c:.0f}) above 50 SMA ({s50:.0f}) & 200 SMA ({s200:.0f}). Bull regime.",
                    allowed_strategies=["Stage_Analysis", "SEPA_VCP", "CAN_SLIM", "Momentum_RL"],
                    position_size_multiplier=1.0
                )
            elif c < s50 and c < s200:
                return MarketRegime(
                    market="INDIA",
                    regime="BEAR_DOWNTREND",
                    benchmark_symbol="^NSEI",
                    benchmark_price=c,
                    sma50=s50,
                    sma200=s200,
                    vix_level=vix_val,
                    description=f"Nifty 50 ({c:.0f}) below key moving averages. Defensive bear regime. Breakouts blocked.",
                    allowed_strategies=["Mean_Reversion"],
                    position_size_multiplier=0.5
                )
            else:
                return MarketRegime(
                    market="INDIA",
                    regime="SIDEWAYS_CONSOLIDATION",
                    benchmark_symbol="^NSEI",
                    benchmark_price=c,
                    sma50=s50,
                    sma200=s200,
                    vix_level=vix_val,
                    description=f"Nifty 50 ({c:.0f}) consolidating near 50 SMA ({s50:.0f}). Mixed trend.",
                    allowed_strategies=["Mean_Reversion", "Momentum_RL"],
                    position_size_multiplier=0.75
                )

        except Exception as e:
            logger.error(f"Error detecting India market regime: {e}")
            return self._fallback_regime("INDIA", "^NSEI")

    def _fallback_regime(self, market: str, symbol: str) -> MarketRegime:
        return MarketRegime(
            market=market,
            regime="SIDEWAYS_CONSOLIDATION",
            benchmark_symbol=symbol,
            benchmark_price=0.0,
            sma50=0.0,
            sma200=0.0,
            vix_level=15.0,
            description="Default balanced regime.",
            allowed_strategies=["Stage_Analysis", "SEPA_VCP", "CAN_SLIM", "Mean_Reversion", "Momentum_RL"],
            position_size_multiplier=0.8
        )

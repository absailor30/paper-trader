"""
Configuration. Every knob that affects money movement lives here, with
no hidden defaults scattered across other modules.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    # Persistence: Postgres in production, local SQLite file for dev/tests.
    # Never plain JSON files on disk (they don't survive a redeploy and
    # aren't safe to write to concurrently).
    database_url: str = "sqlite:///paper_trader.db"

    # Market data
    gemini_api_key: str = ""

    # Telegram push notifications (trade fills/rejections, fetch
    # failures). Both empty = notifications silently disabled; no
    # Telegram credentials are ever needed for local dev or tests.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Capital
    us_capital: float = 100.0
    india_capital: float = 10000.0
    crypto_capital: float = 1000.0

    # Universe. Widened from an initial 6-symbol mega-cap-tech-heavy set
    # (SPY/QQQ/AAPL/MSFT/NVDA/AMD) after the first backtest results: that
    # set was dominated by an extreme 2022-2026 bull run (NVDA +1268%),
    # making "beat buy-and-hold" a near-impossible bar and telling us
    # little about the strategy's actual edge. This set spans sectors
    # (tech, healthcare, financials, energy, consumer, industrials,
    # utilities) and deliberately includes names that have NOT been
    # straight-line winners (BA, PFE, DIS) rather than only cherry-picking
    # the biggest gainers, so the backtest isn't grading itself on easy mode.
    us_stocks: List[str] = [
        "AAPL", "MSFT", "GOOGL", "NVDA", "AMD",          # tech
        "JNJ", "UNH", "PFE",                              # healthcare
        "JPM", "BAC", "GS",                               # financials
        "XOM", "CVX",                                     # energy
        "WMT", "KO", "PG", "DIS",                         # consumer
        "CAT", "BA",                                      # industrials
        "NEE",                                            # utilities
        "SPY", "QQQ", "IWM", "DIA",                       # broad-market benchmarks
    ]
    india_stocks: List[str] = [
        "RELIANCE", "TCS", "INFY", "WIPRO",               # energy/IT
        "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK",      # financials
        "HINDUNILVR", "ITC",                              # consumer staples
        "BHARTIARTL", "LT",                                # telecom/industrials
        "MARUTI", "TMPV",                                  # auto (TATAMOTORS demerged Oct 2025 into
                                                            # TMPV/passenger vehicles + TMCV/commercial;
                                                            # TMPV kept as the closer match to the original)
        "SUNPHARMA",                                       # pharma
    ]

    # Commodity ETFs (not raw futures contracts like GC=F/CL=F, which have
    # periodic contract rollover gaps that distort a daily-bar SMA/RSI
    # backtest). These track spot price continuously, same as an equity.
    commodities: List[str] = [
        "GLD",   # SPDR Gold Trust
        "SLV",   # iShares Silver Trust
        "USO",   # United States Oil Fund (WTI crude)
        "UNG",   # United States Natural Gas Fund
    ]

    # Risk parameters
    max_position_size: float = 0.12       # max 12% of portfolio per position
    max_daily_loss: float = 0.04          # daily circuit breaker
    max_drawdown: float = 0.15            # total circuit breaker
    concentration_ceiling: float = 0.5    # hard cap on a single minimum-viable order

    # Strategy parameters (trend following)
    fast_sma: int = 50
    slow_sma: int = 200
    atr_period: int = 14
    atr_stop_multiple: float = 3.5        # stop = entry - N * ATR (widened from
                                           # 2.5 after the first backtest showed
                                           # frequent premature stop-outs — see
                                           # trend_following.py docstring)
    min_risk_reward: float = 1.5

    # Strategy parameters (mean reversion)
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0

    # Strategy parameters (Donchian breakout, classic Turtle-style
    # channel: enter on a new N-day high, exit on a new M-day low)
    donchian_entry_period: int = 20
    donchian_exit_period: int = 10

    # Strategy parameters (momentum rotation)
    rotation_lookback_days: int = 126     # ~6 trading months of trailing return
    rotation_top_n: int = 5               # hold this many names at a time
    rotation_rebalance_days: int = 21     # ~monthly
    rotation_min_momentum: float = 0.0    # exclude negative-momentum names
                                           # even if fewer than top_n qualify

    # Crypto universe (Binance spot pairs, quoted in USDT). Deliberately
    # a small, liquid set to start -- majors plus a couple of large-caps --
    # rather than every pair Binance lists, same reasoning as the equity
    # universe widening: a backtest needs names that aren't all the same
    # trade (BTC/ETH/SOL move together far more than AAPL/XOM do).
    crypto_pairs: List[str] = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
    ]

    # Costs (applied identically in backtest and live paper trading, so
    # backtest results and live results are directly comparable). Binance
    # spot taker fee (no BNB discount) happens to match the equity default
    # already used here, so no separate crypto rate is needed.
    commission_rate: float = 0.001
    slippage_rate: float = 0.0005

    # Autonomy gate. Defaults to propose-only: signals are generated,
    # sized, and logged, but no order is placed, until this is explicitly
    # set to true after a backtest has demonstrated positive expectancy.
    auto_execute: bool = False

    # extra="ignore": a leftover .env from the previous codebase (or any
    # future unrelated var) must not crash startup — pydantic-settings
    # rejects unknown env vars by default.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()

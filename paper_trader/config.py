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

    # Capital
    us_capital: float = 100.0
    india_capital: float = 10000.0

    # Universe (kept intentionally small while validating the strategy)
    us_stocks: List[str] = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMD"]
    india_stocks: List[str] = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]

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

    # Costs (applied identically in backtest and live paper trading, so
    # backtest results and live results are directly comparable)
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

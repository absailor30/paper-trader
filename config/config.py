"""
Configuration settings for Paper Trader
"""
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    # API Keys
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    gemini_api_key: str = ""

    # Telegram Alert Settings
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_heartbeat_hours: int = 1  # Send heartbeat update every N hours

    # Risk Parameters
    max_position_size: float = 0.12  # 12% max per position
    max_daily_loss: float = 0.04  # 4% daily loss limit
    stop_loss: float = 0.06  # 6% stop loss
    max_drawdown: float = 0.15  # 15% max drawdown circuit breaker
    trailing_stop_trigger: float = 0.10  # Activate trailing stop after 10% gain

    # Capital
    us_capital: float = 100.0
    india_capital: float = 10000.0

    # Universe
    us_stocks: List[str] = [
        # AI/Momentum
        "NVDA", "AMD", "AVGO", "QCOM",
        # Energy
        "XOM", "CVX", "COP", "SLB",
        # Defense
        "LMT", "RTX", "NOC",
        # Tech
        "MSFT", "GOOGL", "META", "AMZN",
        # ETFs
        "SPY", "QQQ", "XLE", "XLK"
    ]

    india_stocks: List[str] = [
        # Top performers (Sep 2026)
        "SHRIRAMFIN", "HDFCBANK", "DRREDDY", "TECHM", "HDFCLIFE", "WIPRO",
        # Momentum
        "TATAMOTORS", "INDIGO", "KOTAKBANK",
        # Defensive
        "ITC", "HINDUNILVR", "SUNPHARMA",
        # Additional Nifty 50
        "RELIANCE", "TCS", "INFY", "ICICIBANK", "SBIN", "BHARTIARTL", "LT", "AXISBANK", "BAJFINANCE", "NTPC", "TITAN"
    ]

    # Trading hours
    us_market_open: str = "09:30"
    us_market_close: str = "16:00"
    india_market_open: str = "09:15"
    india_market_close: str = "15:30"

    # LLM Settings
    glm_model_path: str = "models/glm-4-9b-quantized"
    gemini_model: str = "gemini-2.5-flash-lite"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

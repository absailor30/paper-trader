# Project Checkpoint: Autonomous AI Paper Trader
**Date**: 2026-09-16
**Repo**: `https://github.com/absailor30/paper-trader.git` (Branch: `main`)
**Commit**: `634ed99` ("feat(deploy): add Dockerfile, supervisord, and render configuration")

---

### 1. Capital & Active Portfolios
- **US Equities (Alpaca Paper)**:
  - Starting Capital: $100.00
  - Current Positions:
    - `XLE`: 0.186 shares (rebalanced from 1.0 full share to enforce 12% max allocation risk guard)
    - `CVX`: active
  - Available Cash: Preserved ~$75.86 for high-expectancy setups.
  - Sizing Engine: Dynamic 4-decimal fractional share calculation (`round(allocation / price, 4)`).
- **Indian Equities (NSE Simulated)**:
  - Starting Capital: ₹10,000.00
  - Current Position: `DRREDDY.NS` (2 shares).
  - Available Cash: ₹7,667 preserved in cash. 19 of 22 Nifty 50 constituents below 50-day SMA; capital preserved until mean reversion setups hit -2.0 Z-score extreme.
- **Accounting & Frictions**:
  - 0.10% commission + 0.05% slippage applied to every paper fill and exit.

---

### 2. Autonomous Market Understanding, Trading & Risk Engine
- **Market Regime Detection (`src/intelligence/market_regime.py`)**:
  - Dynamically classifies US (SPY, QQQ, VIX) and India (^NSEI, India VIX) into 4 macro states: `BULL_MOMENTUM`, `SIDEWAYS_CONSOLIDATION`, `BEAR_DOWNTREND`, `HIGH_VOLATILITY`.
  - Strategy filtering: blocks breakout playbooks during bear/choppy regimes to eliminate false breakouts; unleashes momentum & stage 2 breakouts only during confirmed bull uptrends.
  - Dynamic sizing: scales exposure up to full 12% in bull regimes, 6-8% in consolidation, down to 0-6% in high volatility.
- **Autonomous Trade Execution (`src/main.py`)**:
  - Validates risk-to-reward ratio (minimum 1.5:1 required).
  - Enforces fractional share sizing for US ($5 min order) and integer shares for India.
  - Automatically dispatches Telegram alerts on all BUY entries and SELL exits.
- **Dynamic Trailing Stop Loss (`src/execution/paper_trader.py`)**:
  - Automatically activates when position reaches +10% profit.
  - Ratchets stop loss upward (5% below peak price) to lock in gains; never adjusts downward.
- **24/7 Cloud Daemon (`src/execution/live_monitor.py`)**:
  - **06:00 AM IST**: Autonomous pre-market global macro sweep, watchlist screening, and Telegram brief.
  - **09:35 AM IST**: Autonomous Indian market entry cycle (screens Nifty 50, evaluates regime, executes approved buys).
  - **15:35 IST**: Indian market close EOD reflection and Telegram performance summary.
  - **09:45 AM EST (20:15 IST)**: Autonomous US market entry cycle (screens US universe, evaluates regime, executes approved buys).
  - **16:05 EST**: US market close EOD reflection and Telegram performance summary.
  - **Continuous 5-Second Ticks**: Real-time mark-to-market prices, trailing stop ratchet, and immediate stop-loss/take-profit exit.
  - **Hourly**: Portfolio mark-to-market heartbeat sent to Telegram.

---

### 3. Telegram Real-Time Notifications (`src/notifications/telegram_notifier.py`)
- **Bot**: `@us_india_trader_bot` (Configured securely via `TELEGRAM_BOT_TOKEN` in `.env`)
- **Target Chat ID**: Configured via `TELEGRAM_CHAT_ID` in `.env`
- **Alert Types**:
  - Live trade execution / stop-loss / take-profit fills.
  - Hourly portfolio mark-to-market heartbeats.
  - 06:00 AM IST pre-market research briefs.
- **Status**: Live, verified, and operational.

---

### 4. Live Dashboard (`src/monitoring/dashboard.py`)
- Streamlit application running on port `8501`.
- Real-time mark-to-market prices via `yfinance.fast_info` with 15-second cache.
- Metrics: Invested capital, current valuation, portfolio allocation percentage per position.
- Sidebar live monitor health badge tracking log timestamps (`● Active (Last tick: Xs ago)`).
- Strategy Playbook & Experience matrix tabulating empirical edge across Weinstein Stage Analysis, Minervini SEPA/VCP, Bollinger Mean Reversion, O'Neil CAN SLIM, and Momentum RL.
- Autonomous daily reflections reader (`logs/daily_reflections.md`).

---

### 5. Cloud Deployment & 24/7 Production Setup
- **Platform**: Render (Web Service, Docker Runtime)
- **Container**: Python 3.11-slim orchestrated via `supervisord.conf`
  - Worker 1: `live_monitor.py` (5s active hours risk tick + off-hours 06:00 AM IST scheduler)
  - Worker 2: Streamlit Live Dashboard (`0.0.0.0:8501`)
- **Keep-Alive Uptime**: cron-job.org scheduled HTTP GET every 10 minutes to `/_stcore/health` to eliminate free tier sleep.
- **Local Independence**: Fully cloud-hosted. Terminal, CMD, and local laptop can be closed without interrupting trading or monitoring.
- **Git Status**: Pushed to `origin/main` at `https://github.com/absailor30/paper-trader.git`.

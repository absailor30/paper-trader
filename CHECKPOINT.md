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

### 2. Autonomous Monitoring & Research Engine
- **Live Risk Daemon (`src/execution/live_monitor.py`)**:
  - Real-time tick polling every 5 seconds during active market hours:
    - NSE: 09:15 – 15:30 IST
    - US: 09:30 – 16:00 EST
  - Auto-evaluates stop-loss and take-profit targets on every tick.
  - Off-market hours: halts 5-second polling to prevent rate limits and compute waste; calculates exact countdown to 06:00:00 AM IST.
- **Pre-Market Research Engine (`src/intelligence/premarket_research.py`)**:
  - Autonomous wake-up scheduled at 06:00 AM IST daily.
  - Scans global macro regime (`CL=F` Crude, `GC=F` Gold, `ES=F` S&P Futures, `^NSEI` Nifty).
  - Screens US and Indian universes for Stage 2 breakouts (50 SMA > 150 SMA, Vol > 1.2x) and oversold mean-reversions (RSI < 30).
  - Persists intelligence output to `data/watchlist_research.json`.
  - Dispatches morning briefing directly to Telegram.

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

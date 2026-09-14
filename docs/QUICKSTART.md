# Paper Trader - Autonomous AI Trading Agent

**Mission**: Build an AI trading agent that learns from paper trades before going live.

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure API keys
cp .env.example .env
# Edit .env with your API keys

# 3. Run test
python test_system.py

# 4. Start trading
python src/main.py
```

## 📊 Status

**Started**: September 14, 2026

**Goal**: End of September 2026 - Green after taxes and fees

## 💰 Capital

| Market | Allocation | Platform |
|--------|------------|----------|
| US Stocks | $100 | Alpaca Paper Trading |
| Indian Stocks | ₹10,000 | Simulated Paper |

## 🧠 Strategies Implemented

1. **CAN SLIM + ML Screening** (William O'Neil)
   - Cup-with-handle detection
   - Volume surge analysis
   - Relative strength scoring

2. **SEPA + VCP** (Mark Minervini)
   - Stage 2 uptrend identification
   - Volatility contraction patterns
   - 7-8% stop loss rule

3. **Stage Analysis** (Stan Weinstein)
   - 4-stage market classification
   - 30-week MA breakout system
   - Volume confirmation

4. **Momentum + RL Optimization**
   - RSI + MACD + Volume factors
   - Trend strength detection
   - RL-weighted signals (coming)

5. **Mean Reversion + Dynamic Z-Score**
   - Bollinger Band squeezes
   - Adaptive volatility thresholds
   - Z-score extremes

## 🏗️ Project Structure

```
trading-agent/
├── src/
│   ├── data/              # Data pipelines
│   │   └── data_fetcher.py
│   ├── strategies/        # 5 core strategies
│   │   ├── base_strategy.py
│   │   ├── can_slim.py
│   │   ├── sepa_vcp.py
│   │   ├── stage_analysis.py
│   │   ├── momentum_rl.py
│   │   └── mean_reversion.py
│   ├── execution/         # Order execution
│   │   └── paper_trader.py
│   └── main.py            # Main orchestration
├── config/
│   └── config.py          # Settings
├── models/                # Trained models
├── logs/                  # Trade journals
├── data/                  # Historical data
└── notebooks/             # Research notebooks
```

## 🤖 LLM Stack

| Model | Purpose | Deployment |
|-------|---------|------------|
| GLM-4-9B (quantized) | Trade rationale, daily reflection | Local (4GB VRAM) |
| Gemini 2.5 Flash-Lite | Signal validation, quick checks | Cloud API |
| Claude Sonnet | Deep analysis, debugging | External |

## ⚠️ Risk Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Max Position Size | 12% | Aggressive for learning |
| Daily Loss Limit | 4% | Circuit breaker |
| Stop Loss | 6% | Tighter in volatility |
| Max Drawdown | 15% | System pause |
| Trailing Stop | After 10% gain | Lock profits early |

## 📈 Universe (Updated Sep 14, 2026)

### US Stocks (20)
- **AI/Momentum**: NVDA, AMD, AVGO, QCOM
- **Energy**: XOM, CVX, COP, SLB
- **Defense**: LMT, RTX, NOC
- **Tech**: MSFT, GOOGL, META, AMZN
- **ETFs**: SPY, QQQ, XLE, XLK

### Indian Stocks (25)
- **Top Performers**: SHRIRAMFIN, HDFCBANK, DRREDDY, TECHM, HDFCLIFE, WIPRO
- **Momentum**: TATAMOTORS, INDIGO, KOTAKBANK
- **Defensive**: ITC, HINDUNILVR, SUNPHARMA
- **Nifty 50**: RELIANCE, TCS, INFY, ICICIBANK, SBIN, BHARTIARTL, LT, AXISBANK, BAJFINANCE, NTPC, TITAN

## 🎯 Success Metrics

- [ ] 50+ trades by Sep 30
- [ ] Win rate > 45%
- [ ] Positive expectancy
- [ ] Max drawdown < 15%
- [ ] All trades with reasoning logged

## 🔧 Configuration

Edit `.env` file:

```env
# Alpaca (US Stocks)
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here

# Gemini (Google AI)
GEMINI_API_KEY=your_key_here

# Risk Parameters
MAX_POSITION_SIZE=0.12
MAX_DAILY_LOSS=0.04
STOP_LOSS=0.06
```

## 📝 Development Roadmap

### Week 1 (Sep 14-21)
- [x] Project setup
- [x] Data pipelines (US + India)
- [x] 5 core strategies implemented
- [x] Paper trading engine
- [ ] Backtesting framework
- [ ] GLM-4 local deployment

### Week 2 (Sep 22-30)
- [ ] RL agent training
- [ ] LLM reasoning integration
- [ ] Dashboard (Streamlit)
- [ ] Live paper trading
- [ ] Performance tracking
- [ ] Daily journals

## 🚨 Current Status

**✅ Working**:
- Data fetching (yfinance)
- All 5 strategies
- Paper trading engine
- Risk management

**🚧 In Progress**:
- Alpaca API integration (need keys)
- Backtesting module
- LLM reasoning layer

**📋 TODO**:
- Dashboard UI
- Telegram alerts
- RL training pipeline

## 📦 Dependencies

Core:
- yfinance, pandas, numpy
- pydantic-settings
- loguru

ML/RL:
- stable-baselines3
- torch
- scikit-learn

LLM:
- google-generativeai
- transformers, accelerate

## 🔗 API Keys Needed

1. **Alpaca** (free): https://alpaca.markets/
   - US stock paper trading
   - Real-time & historical data

2. **Google AI** (free tier): https://aistudio.google.com/
   - Gemini 2.5 Flash-Lite
   - Signal validation

## 📖 Strategy References

- **CAN SLIM**: William O'Neil - "How to Make Money in Stocks"
- **SEPA/VCP**: Mark Minervini - "Trade Like a Stock Market Wizard"
- **Stage Analysis**: Stan Weinstein - "Secrets for Profiting in Bull and Bear Markets"

## 📄 License

MIT

---

**Built with aggressive learning. Paper trade first. Learn. Then go live.**

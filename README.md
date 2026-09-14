# Paper Trader - Autonomous AI Trading Agent

**Mission**: Build an AI trading agent that learns from paper trades before going live.

## Status
🚧 **In Development** - Started September 14, 2026

## Goal
End of September 2026: **Green after taxes and fees**

## Markets
- **US Stocks**: $100 paper capital (Alpaca)
- **Indian Stocks**: ₹10,000 simulated paper (NSE/BSE)

## Strategies
1. **CAN SLIM + ML Screening** (O'Neil)
2. **SEPA + VCP** (Minervini)
3. **Stage Analysis** (Weinstein)
4. **Momentum Factor Blend + RL**
5. **Mean Reversion + Dynamic Z-Score**

## Architecture

```
├── src/
│   ├── data/           # Data pipelines (Alpaca, NSE, yfinance)
│   ├── strategies/     # 5 core strategies
│   ├── execution/      # Order execution, paper trading
│   ├── intelligence/   # LLM reasoning (GLM-4, Gemini)
│   └── monitoring/     # Dashboard, alerts, logging
├── models/             # Trained RL models
├── data/               # Historical data storage
├── logs/               # Trade journals, performance logs
├── config/             # Configuration files
└── notebooks/          # Research notebooks
```

## LLM Stack
- **GLM-4-9B (quantized)**: Trade rationale, daily reflection (local, 4GB VRAM)
- **Gemini 2.5 Flash-Lite**: Signal validation, quick risk checks
- **Claude Sonnet**: Deep analysis, debugging (external)

## Risk Parameters (September 2026 Volatility Adjusted)
- Max position: 12%
- Daily loss limit: 4%
- Stop loss: 6%
- Max drawdown: 15%
- Trailing stop: After 10% gain

## Universe (Updated Sep 14, 2026)

### US Stocks (20)
- **AI/Momentum**: NVDA, AMD, AVGO, QCOM
- **Energy**: XOM, CVX, COP, SLB
- **Defense**: LMT, RTX, NOC
- **Tech**: MSFT, GOOGL, META, AMZN
- **ETFs**: SPY, QQQ, XLE, XLK

### Indian Stocks (25)
- **Top performers**: SHRIRAMFIN, HDFCBANK, DRREDDY, TECHM, HDFCLIFE, WIPRO
- **Momentum**: TATAMOTORS, INDIGO, KOTAKBANK
- **Defensive**: ITC, HINDUNILVR, SUNPHARMA

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env with your keys

# Run paper trading
python src/main.py
```

## Timeline
- **Week 1 (Sep 14-21)**: Setup, data, strategies, backtests
- **Week 2 (Sep 22-30)**: RL training, launch, first trades

## Success Metrics
- 50+ trades by Sep 30
- Win rate > 45%
- Positive expectancy
- Max drawdown < 15%
- All trades with reasoning logged

---
Built with aggressive learning.

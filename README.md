# Paper Trader

A paper-trading agent with a **backtest-gated** path to autonomy: a
strategy only gets to place live orders after `run.py backtest` shows it
has positive expectancy net of realistic costs, against real historical
data.

This is a from-scratch rebuild (branch `rebuild/v2`). Previous iterations
went straight to live paper trading without ever backtesting, carried a
missing core module for weeks without anyone noticing, and accumulated
five strategies and a "regime detection" layer none of which had been
validated to have any edge. See `CHECKPOINT.md` for that history and why
this rebuild happened.

## Status: iteration 2

The first backtest run (see `CHECKPOINT.md`) showed the trend-following
strategy's original exit rule (single close below the 50 SMA) whipsawing
out of real trends — 0/6 symbols beat buy-and-hold, win rates 8-27%. Two
changes went in as a result, not yet re-verified against real data:

- Exit now requires two consecutive closes below the 50 SMA, and the ATR
  stop widened from 2.5x to 3.5x — both aimed at reducing premature
  stop-outs from single-day noise.
- A second strategy, `MeanReversionStrategy` (RSI oversold-recovery
  within a long-term uptrend), was added so the next backtest run
  compares two approaches, not just re-tests a tweaked version of one.

`python run.py backtest` now runs both and prints separate per-strategy
verdicts. Whether either one actually has an edge is still unverified —
that's the next real-internet run, same as before.

## Design principles

1. **Backtest before automation.** `paper_trader/backtest/` runs a
   strategy against real history using the *same* execution code paths
   as live trading (commission, slippage, sizing) — a backtest result and
   a live result are directly comparable, not two implementations that
   can silently diverge.
2. **One source of truth for state.** `paper_trader/persistence/` is
   SQLAlchemy against Postgres in production, SQLite locally — the same
   code path either way. No JSON files on disk that vanish on a redeploy.
3. **One entry point.** `run.py` replaces the previous split across
   `main.py` / `run_daily.py` / `live_monitor.py`, which re-implemented
   the same cycle logic three times and drifted out of sync.
4. **Idempotent by construction.** Every order carries a caller-supplied
   `client_order_id`; placing the same id twice is a no-op, not a double
   fill. A retried cron run or a crash-and-resume can't double-trade.
5. **Named for what it is.** No strategy is called "RL" unless it's
   actually reinforcement learning. `TrendFollowingStrategy` is plain
   rule-based technical analysis, and says so in its own docstring.
6. **Propose-only by default.** `AUTO_EXECUTE=false` (the default) means
   the bot generates and sizes signals and logs what it *would* do, but
   places no orders. Flip it only after the backtest looks right.

## Structure

```
paper_trader/
  config.py                    # every setting that affects money movement
  data/fetcher.py               # yfinance OHLCV fetch
  strategy/
    base.py                     # Strategy interface, Signal/Position types
    indicators.py                # sma, atr
    trend_following.py           # the one strategy, honestly named
  backtest/
    engine.py                    # runs a Strategy over history using PaperTrader itself
    run_backtest.py               # CLI: prints a verdict per symbol
  execution/paper_trader.py     # idempotent order execution, P&L, metrics
  persistence/state_store.py    # Postgres/SQLite state (one code path)
  orchestrator.py               # TradingBot: one cycle, US or India, propose-only by default
run.py                          # CLI entry point
tests/                          # unit tests against deterministic synthetic data
```

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # DATABASE_URL optional locally (defaults to SQLite)

# 1. Prove the strategy has an edge before anything else
python run.py backtest

# 2. Run a cycle in propose-only mode (default) and read what it *would* do
python run.py cycle

# 3. Only after (1) looks right across the universe, not one symbol:
#    set AUTO_EXECUTE=true in .env, then re-run (2) for real
```

## Tests

```bash
pytest tests/ -v
```

All fixtures are deterministic synthetic OHLCV data — no network calls,
no flakiness. This sandbox's network policy blocks live market data
entirely (confirmed: yfinance, Alpha Vantage, and even plain google.com
all get rejected by the egress proxy), so `python run.py backtest` has
not been run against real data yet — that has to happen from an
environment with real internet access before `AUTO_EXECUTE` is ever set
to true.

## What's deliberately not here (yet)

Telegram alerts, the Streamlit dashboard, market-regime detection, and
the other four strategies from the previous version were dropped in this
rebuild — clean slate, one validated strategy first. They can come back
once the foundation here is proven, not before.

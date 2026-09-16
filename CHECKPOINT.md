# Project Checkpoint

**Date**: 2026-09-16
**Branch**: `rebuild/v2` (not merged to `main` — `main` still has the previous
architecture live on Render, untouched by this branch)

## Why this rebuild happened

An audit on 2026-09-15 found the previous system's core data module
(`src/data/data_fetcher.py`) was missing from the repo entirely — a
`.gitignore` rule silently excluded it from every commit — so the bot
could never actually generate a new trade in any deployment. That got
fixed, along with several related bugs (dead exit logic, no signal
de-dup, risk checks only run once per batch, India position sizing that
rounded to zero for large caps). See the commit history and PR #1 on
`main` for that fix chain.

While auditing further, the deeper problem became clear: nothing had
ever been backtested. Five strategies plus a market-regime detection
layer were built and pointed at live paper trading with zero evidence
any of them had positive expectancy. "Momentum_RL" had no trained model
— it was rule-based scoring mislabeled as reinforcement learning.
Portfolio state lived in JSON files that Render's free tier wipes on
every redeploy. Given all of that, patching forward wasn't going to
produce something trustworthy — hence this from-scratch rebuild.

## What's in this rebuild

One backtest-gated strategy (`TrendFollowingStrategy`, SMA 50/200 with
an ATR stop — plain technical analysis, honestly named), one execution
engine shared between backtest and live (idempotent by `client_order_id`,
so re-running a cycle can't double-trade), one persistence path
(SQLAlchemy against Postgres in prod / SQLite locally), one entry point
(`run.py`), and `AUTO_EXECUTE=false` by default — it proposes and logs
trades without placing them until you've run the backtest and are
satisfied with the result.

Full rationale and structure: see `README.md`.

## What's explicitly not here

Telegram alerts, the Streamlit dashboard, market-regime detection, the
other four strategies (CAN SLIM, SEPA/VCP, Stage Analysis, Mean
Reversion), the n8n workflow, and the Render/Docker deployment config —
all dropped for this rebuild. They were real features but none of them
were the problem; the missing validation step was. They can be rebuilt
on top of this once the foundation is proven, not merged back in
wholesale.

## Status — what's verified vs. not

- ✅ 15 unit tests pass against deterministic synthetic data (strategy
  signal generation, exits, idempotent order execution, insufficient
  capital handling, backtest engine, Postgres/SQLite state round-trip).
- ✅ All entry points (`run.py`, `paper_trader.orchestrator`,
  `paper_trader.backtest.run_backtest`) import and initialize cleanly.
- ❌ **Not yet run against real market data.** This sandbox's network
  policy blocks all outbound data access (confirmed by testing yfinance,
  Alpha Vantage, and plain `google.com` — all rejected by the egress
  proxy), so `python run.py backtest` has never actually executed
  against real prices. This is the next required step, from an
  environment with real internet access, before `AUTO_EXECUTE` is ever
  set to true.

## Next steps (in order)

1. Run `python run.py backtest` against real data (your laptop, or
   Render). Read the per-symbol verdicts — don't just check it runs,
   check whether it actually beats buy-and-hold with enough trades to
   mean something.
2. If the strategy doesn't show an edge: that's a real result, not a
   bug — either iterate on the strategy or accept that trend-following
   on this universe doesn't have one, before building anything further
   on top of it.
3. If it does: run `python run.py cycle` in propose-only mode for a
   while and sanity-check the proposals against your own judgment before
   flipping `AUTO_EXECUTE=true`.
4. Only after that: decide whether/what to merge into `main`, and
   whether to re-add Telegram/dashboard/deployment on top.

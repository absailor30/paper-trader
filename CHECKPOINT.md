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

## Update: first real backtest ran (2026-09-16)

Ran `python run.py backtest` on a laptop with real internet — this
sandbox still can't (see network policy note above). Result: **0/6
symbols beat buy-and-hold**, win rates 8.7%-27.3%, and on NVDA the
strategy returned -1.18% while buy-and-hold returned +1268.40%.

Root cause from the trade log: the exit rule ("close back below the 50
SMA") fired on single-day dips, whipsawing out of real trends before
they played out — dozens of round trips paying commission+slippage while
barely breaking even, never capturing the actual moves.

Response (not yet re-verified — this is the next thing to test, not a
fix to trust on faith):
- `TrendFollowingStrategy.should_exit()` now requires two consecutive
  closes below the 50 SMA, not one.
- `atr_stop_multiple` widened 2.5x -> 3.5x.
- Added `MeanReversionStrategy` (RSI oversold-recovery in a long-term
  uptrend) as a second candidate, so the next run compares two
  approaches rather than re-testing one tweaked strategy in isolation.
- `run_backtest.py` now runs both strategies and prints separate
  per-strategy verdicts.

## Strategy scoreboard (as of 2026-09-16)

Single source of truth for what's actually been tested against real
market data and what the result was. Update this table, don't just
narrate results in chat, every time a real backtest result comes back.

| Strategy | Universe | Result | Validated? |
|---|---|---|---|
| Trend Following (SMA 50/200 + ATR stop) | US stocks (widened, 38 symbols) | Whipsaw bug found and fixed (2-close exit rule); re-run not yet reported back with clean aggregate numbers | Not confirmed |
| Mean Reversion (RSI oversold-recovery) | US stocks (widened, 38 symbols) | Best-performing so far on individual names (e.g. NVDA 100% win rate once profit_factor bug fixed); some India names (TCS/INFY/WIPRO/HINDUNILVR) came back negative-return, correctly caught as NOT VALIDATED after the "beats a falling benchmark" bug was fixed | Mixed — no clean aggregate win-rate/profit-factor table captured yet |
| Trend Following | Commodities (GLD/SLV/USO/UNG) | 0/4 validated | No |
| Mean Reversion | Commodities (GLD/SLV/USO/UNG) | 0/4 validated, weaker than trend-following on commodities | No |
| Momentum Rotation (top-5, 126d lookback, 21d rebalance) | US (widened) | +60.29% vs +117.00% benchmark, Sharpe 0.63, max DD -23.82% — run **before** the insufficient-capital bug fix, needs re-run | No |
| Momentum Rotation | India | +2.13% vs +49.88% benchmark, Sharpe 0.10, max DD -22.45% — same caveat, needs re-run | No |
| Donchian Breakout | — | Not built yet | — |

**Bottom line so far**: nothing is validated yet. Mean reversion on
individual US stocks is the most promising thread but I don't have a
clean aggregate table for it — next real-data run should capture that
explicitly instead of just spot-checking symbols. Rotation underperformed
its own benchmark by a wide enough margin that the capital-allocation bug
fix (see below) probably won't flip the verdict, but it needs re-running
to confirm rather than assumed.

## Next steps (in order)

1. Re-run `python run.py rotation` (both universes) now that the
   insufficient-capital allocation bug is fixed, to get a clean number —
   the ones in the table above were measured with the bug present.
2. Re-run `python run.py backtest` and capture the full aggregate table
   (avg win rate, avg profit factor, avg drawdown) per strategy per
   universe into this checkpoint — not just individual symbol anecdotes.
3. Build and backtest Donchian breakout (in progress now).
4. Once at least one strategy is validated on real data with a clean
   aggregate table: run `python run.py cycle` in propose-only mode for a
   while and sanity-check proposals before flipping `AUTO_EXECUTE=true`.
5. Only after that: decide whether/what to merge into `main`, and
   whether to re-add Telegram/dashboard/deployment on top.

## Bug log (rebuild/v2)

| Bug | Found via | Fix |
|---|---|---|
| Single-day dip below SMA50 triggered exit, whipsawing out of real trends | Real US stock backtest | Require 2 consecutive closes below SMA; widened ATR stop 2.5x→3.5x |
| `profit_factor` returned 0.0 for a 100% win rate (no losing trades) | Real NVDA mean-reversion backtest | Return `inf` when there are wins and no losses |
| "POSITIVE EDGE" label on strategies that lost money but beat an even-more-negative benchmark | Real 38-symbol India backtest (TCS/INFY/WIPRO/HINDUNILVR) | `is_validated()` now also requires `total_return_pct > 0` |
| Rotation rebalancing spuriously rejected buy orders for "insufficient capital" on nearly every rebalance | Real US+India rotation backtest trade log | Reserve slippage+commission headroom in allocation calc; floor (not round) quantity so early buys can't overspend and starve later ones; epsilon tolerance on the capital check |

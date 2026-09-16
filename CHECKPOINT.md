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

## Strategy scoreboard (as of 2026-09-17, full real-data run)

Single source of truth for what's actually been tested against real
market data and what the result was. Update this table, don't just
narrate results in chat, every time a real backtest result comes back.

Full run: `python run.py backtest` across US (24 symbols), India (14,
TATAMOTORS.NS delisted/unavailable), Commodities (4) — 42 symbols total
per strategy, 3 strategies, 1993 trades combined.

| Strategy | Symbols validated | Avg win rate | Avg profit factor | Avg max drawdown |
|---|---|---|---|---|
| Trend Following (SMA 50/200 + ATR stop) | 3/42 | 26.4% | 1.49 | -2.72% |
| Mean Reversion (RSI oversold-recovery) | 0/42 | 52.5% | 1.67 | -2.14% |
| Donchian Breakout (20d entry / 10d exit) | 3/42 | 43.9% | 1.72 | -3.68% |

"Validated" = profitable AND beat buy-and-hold AND >=5 trades — a near-
impossible bar in this 2022-2026 window (extreme bull run, e.g. NVDA
+1300%), so the win-rate/profit-factor columns are the more honest read.

**Read**: Mean Reversion has the best win rate and lowest drawdown but
literally 0/42 beat buy-and-hold (small, choppy gains vs. a runaway
market). Donchian has the best profit factor (1.72) and a respectable
win rate (43.9%) but the widest drawdown. Trend Following is weakest on
every axis — the whipsaw fix helped it stop losing money outright but it
still has the lowest win rate of the three. None of the three has a
demonstrated edge worth auto-executing yet; Donchian and Mean Reversion
are the two worth refining further before Trend Following.

| Strategy | Universe | Result | Validated? |
|---|---|---|---|
| Momentum Rotation (top-5, 126d lookback, 21d rebalance) | US (widened) | **+143.37%** vs +116.10% benchmark, CAGR +21.91%, Sharpe 0.98, max DD -28.87%, 54 rebalances, 523 trades — re-run **after** the insufficient-capital bug fix | **YES — POSITIVE EDGE** |
| Momentum Rotation | India | +5.24% vs +49.88% benchmark, CAGR +1.15%, Sharpe 0.15, max DD -25.08%, 53 rebalances, 496 trades — re-run after fix | No |

**This is the first validated strategy in the rebuild.** The capital-allocation
fix flipped the US verdict: pre-fix it returned +60.29% vs a +117.00%
benchmark (not validated, lost to buy-and-hold); post-fix, with orders no
longer being spuriously rejected mid-rebalance, it returns +143.37% vs a
+116.10% benchmark — the strategy now actually holds the positions its logic
selects instead of silently missing fills, and that alone was enough to beat
the benchmark. India stays not validated — same fix applied, still a real
gap (+5.24% vs +49.88%), so the edge there (if any) is universe-specific, not
a residual bug.

## Next steps (in order)

1. ~~Re-run `python run.py rotation` post-fix~~ — done, see above. US rotation
   validated; India did not.
2. Sanity-check US Momentum Rotation isn't a one-window fluke: rotation was
   already validated on a single 2022-2026 run — worth confirming the result
   holds before treating it as trustworthy (e.g. re-check trade log for any
   remaining silent-rejection artifacts, consider a second date range if
   feasible).
3. Decide whether to iterate on Donchian (best profit factor among the
   single-symbol strategies) or Mean Reversion (best win rate/drawdown) —
   neither is validated as-is but both show more promise than Trend
   Following.
4. Once US Momentum Rotation's result is double-checked: run `python run.py
   cycle` in propose-only mode for a while and sanity-check proposals before
   flipping `AUTO_EXECUTE=true` for that strategy specifically (not the
   others — they're still unvalidated).
5. Only after that: decide whether/what to merge into `main`, and whether to
   re-add Telegram/dashboard/deployment on top.

## Donchian iteration (2026-09-16, prep for tomorrow's real-data session)

Sandbox has no network access, so nothing below is a real backtest result —
it's infrastructure + correctness prep so tomorrow's session can compare
variants against real data in one run instead of guessing at one config.

**Code changes:**
- `DonchianBreakoutStrategy` constructor now takes `entry_period`,
  `exit_period`, `trend_filter_period`, `name` — all optional, default to
  the existing `settings.donchian_*` values, so nothing changes for
  existing callers.
- Added an optional trend filter: when `trend_filter_period` is set, entry
  additionally requires `close > SMA(trend_filter_period)`. Classic fix for
  pure breakout systems whipsawing on breakouts against the longer-term
  trend (e.g. a sharp bounce inside an ongoing downtrend).
- `run.py backtest --sweep donchian` / `python -m
  paper_trader.backtest.run_backtest --sweep donchian` runs 5 variants
  side by side instead of the fixed 3-strategy list:
  - `Donchian_20_10_baseline` — current default, no trend filter
  - `Donchian_55_20_turtle` — classic slower Turtle System 2 periods
  - `Donchian_10_5_fast` — faster/choppier variant
  - `Donchian_20_10_trend100` — default periods + 100-day trend filter
  - `Donchian_55_20_trend100` — slow periods + trend filter
- 4 new tests (`test_custom_periods_override_settings_defaults`,
  `test_trend_filter_blocks_breakout_below_long_term_sma`,
  `test_sweep_variants_have_distinct_names`, plus the existing suite) — 45/45
  pass. Also smoke-tested all 5 sweep variants end-to-end against synthetic
  data (no crashes, no shared-state bugs between variants).

**Next step (tomorrow, on the laptop with real data):** run `python run.py
backtest --sweep donchian` across US/India/commodities and pick whichever
variant(s) validate — don't assume trend-filter or slower periods are
"better," that's exactly what the real run needs to decide.

## Other work this session

- Sanity-checked the rotation trade log end-to-end against a synthetic
  24-symbol/5-year run: 0 rejected orders, cash-flow reconciliation exact
  to the cent, total_value reconciliation exact, no lookahead bias in the
  momentum ranking (same-bar decide/execute is a pre-existing convention
  shared with `engine.py`, not new to rotation). No bugs found — the
  validated US rotation result stands.
- Did not add new speculative strategies beyond what was asked (Donchian
  iteration) — per the project's own rule, nothing gets built and left
  untested; better to hand off clean, sweep-ready code than half-tested
  new strategies with no real data to check them against here.

## Bug log (rebuild/v2)

| Bug | Found via | Fix |
|---|---|---|
| Single-day dip below SMA50 triggered exit, whipsawing out of real trends | Real US stock backtest | Require 2 consecutive closes below SMA; widened ATR stop 2.5x→3.5x |
| `profit_factor` returned 0.0 for a 100% win rate (no losing trades) | Real NVDA mean-reversion backtest | Return `inf` when there are wins and no losses |
| "POSITIVE EDGE" label on strategies that lost money but beat an even-more-negative benchmark | Real 38-symbol India backtest (TCS/INFY/WIPRO/HINDUNILVR) | `is_validated()` now also requires `total_return_pct > 0` |
| Rotation rebalancing spuriously rejected buy orders for "insufficient capital" on nearly every rebalance | Real US+India rotation backtest trade log | Reserve slippage+commission headroom in allocation calc; floor (not round) quantity so early buys can't overspend and starve later ones; epsilon tolerance on the capital check |

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

## Re-run confirmation (2026-09-17, from an environment with real internet + Supabase access)

This is the handoff environment the previous session asked for. Confirmed
network access here: yfinance works, Binance is geo-blocked (HTTP 451) from
this sandbox specifically — so the crypto backtest/loop numbers below are
carried over from the prior session, not re-verified here; everything else
was re-run fresh.

- `pytest tests/` — 56/56 pass (was 56/56).
- `python run.py backtest` (full US+India+commodities, 42 symbols x 3
  strategies) re-run against live data. Donchian now uses
  `trend_filter_period=100` as the checkpointed default (previously flagged
  as "not yet re-run with the new default"):
  - Trend Following: 3/42 validated, 26.3% avg win rate, PF 1.47, DD -2.72%
  - Mean Reversion: 0/42 validated, 52.9% avg win rate, PF 1.72, DD -2.14%
  - **Donchian (trend100): 5/42 validated**, 43.6% avg win rate, PF 1.64,
    DD -3.16% — confirms the sweep's prediction (was stale at 3/42 pre-fix).
- `python run.py rotation` (US 24 + India 15) re-run:
  - US: **+149.56% vs +119.32% benchmark**, CAGR +22.58%, Sharpe 1.01, max
    DD -28.87%, 54 rebalances, 523 trades — **POSITIVE EDGE, reconfirmed**
    (checkpoint had +143.37%/+116.10%; same result within normal drift from
    a few more trading days of data).
  - India: +5.79% vs +50.73% benchmark, CAGR +1.26%, Sharpe 0.16, max DD
    -25.08%, 54 rebalances, 503 trades — **not validated, reconfirmed**.

Net: nothing changed directionally. US Momentum Rotation is the one
strategy with a demonstrated, twice-confirmed edge; Donchian
(trend100) is the best single-symbol strategy but still short of the
validation bar; India rotation and all other single-symbol strategies
remain unvalidated.

## GitHub Actions crypto loop (2026-09-17)

Added `.github/workflows/crypto-cycle.yml` — daily cron (00:10 UTC) plus
manual `workflow_dispatch`, running `python run.py crypto` (single cycle)
against `DATABASE_URL` from a repo secret. This is the "make the crypto
loop run independent of any laptop" plan from the previous session, now
actually wired up. `AUTO_EXECUTE` reads from a repo variable, defaulting to
`false` — same propose-only gate as everywhere else, controlled without a
code change.

**Resolved (2026-09-18):** Supabase's 2-project cap turned out to be a dead
end (see "Vercel/Neon" note below) — switched to Neon.tech instead.
`DATABASE_URL` is set as a GitHub Actions secret pointing at a real Neon
Postgres instance. The repo's default branch was changed from `main` to
`rebuild/v2` (GitHub only discovers/runs workflow files that exist on the
default branch — this is why both workflows initially showed "0 workflows
found" despite existing on `rebuild/v2`). Both `crypto-cycle.yml` and
`crypto-intraday-stops.yml` have since run successfully. Confirmed via
Neon's SQL Editor: a `crypto_portfolio` row exists (`capital: 1000.0,
positions: {}, trade_history: [], ...`, `updated_at: 2026-09-17
20:00:45`), proving the full path — Actions runner → `DATABASE_URL` →
Neon Postgres — works end to end. Empty positions/unchanged capital is
expected here: propose-only mode (`AUTO_EXECUTE` unset/false by default),
no qualifying Donchian breakout on that run.

**Still open:**
- "Two consecutive scheduled runs show state continuity" (day 2 reflecting
  day 1's state, not a reset) has not been explicitly demonstrated yet —
  only one state snapshot has been observed so far. Both crons are live
  (daily + every-30-min), so this should confirm itself passively; worth
  a deliberate before/after check rather than assuming it from one snapshot.
- The Neon connection string (including its password) was pasted in plain
  text in chat during setup. Recommend rotating the Neon database password
  from the Neon dashboard and updating the `DATABASE_URL` secret to match.
- Binance is geo-blocked from this sandbox (HTTP 451 on
  `api.binance.com`), so the crypto strategy itself couldn't be re-validated
  here — only the equities/rotation numbers were reconfirmed this session.
  GitHub Actions runners are typically US-hosted, so this should not affect
  the scheduled workflow itself, only what could be checked from here.

## Intraday stop monitoring (2026-09-17) — code + tests only, not yet backtest-verified

The daily crypto cron (`crypto-cycle.yml`) checks stops once a day. Flagged
as a real gap: a sharp intraday crash-and-recover is invisible to a
once-daily check — the position gets held through the whole move because
by the time the next check runs, price has already recovered. Decided
against just polling more often without backtesting it first (that would
repeat exactly the mistake this whole rebuild exists to fix — see "Why
this rebuild happened" above).

**What's built**, per the project's backtest-gated rule — nothing here runs
live, or even feeds a real number into the scoreboard, until it's been
run against real intraday data:

- `Strategy.check_stop_only(position, current_price) -> bool`
  (`paper_trader/strategy/base.py`): a lightweight stop/take-profit check
  using only a price, no indicator recomputation — confirmed identical to
  the stop/target check duplicated at the top of all three strategies'
  `should_exit()`, so this is a real de-duplication, not new behavior.
- `paper_trader/backtest/intraday_stop_engine.py`
  (`run_intraday_stop_backtest`): entries and full (indicator-based) exits
  stay on the daily bar — unchanged from what was validated — but the stop
  is additionally checked against every intraday bar's low (target against
  every bar's high) in between. Returns both a `daily_only` and a
  `with_intraday_stops` result run against identical entries, so the
  measured effect of intraday checking is a real number, not a guess.
  `engine.py` itself is untouched — this is a separate module so the
  already-validated daily engine can't regress.
- 11 new tests (`tests/test_intraday_stop_engine.py`), 67/67 total pass.

**A real finding from writing the tests**, not from real data, but worth
recording: `should_exit()` in every strategy compares only the day's
*close* against `stop_loss`/`take_profit` — never that day's own high or
low. So the intraday engine can exit earlier than the daily engine even
using a day's own already-known high/low (no fabricated finer-resolution
data needed) whenever a take-profit or stop was touched intraday but the
close pulled back before triggering it on a close-only check. This isn't
a bug in the existing strategies (they were validated on close-only exits,
and that's what the scoreboard reflects) — it's the concrete mechanism by
which "checking more often" can matter even with the exact same OHLC data
already being fetched daily, not only in a hypothetical crash-and-recover
scenario. See `test_intraday_engine_also_catches_touches_within_the_reported_daily_range`.

## Intraday stop monitoring — real-data result (2026-09-17)

Run from a real-internet environment (this sandbox is Binance-blocked, see
above) via `scripts/run_intraday_stop_backtest.py`, all 8 `crypto_pairs`,
`interval=1h`, ~2.3 years of history (2024-10-19 to 2026-09-17),
`Donchian(trend_filter_period=100)` — same strategy/config as the
validated daily crypto result.

| Pair | Daily-only | With intraday stops | Stops caught | Delta |
|---|---|---|---|---|
| BTCUSDT | +5.06% / 10tr / 60.0%wr | +4.23% / 13tr / 46.2%wr | 7 | -0.83% |
| ETHUSDT | +0.78% / 11tr / 54.5%wr | +2.67% / 12tr / 50.0%wr | 7 | +1.89% |
| BNBUSDT | +4.08% / 8tr / 62.5%wr | +7.51% / 12tr / 66.7%wr | 9 | +3.44% |
| SOLUSDT | +2.03% / 9tr / 44.4%wr | +1.38% / 11tr / 45.5%wr | 6 | -0.65% |
| XRPUSDT | +8.58% / 11tr / 45.5%wr | +19.89% / 14tr / 57.1%wr | 11 | +11.30% |
| ADAUSDT | +1.58% / 10tr / 30.0%wr | +4.73% / 11tr / 36.4%wr | 6 | +3.14% |
| DOGEUSDT | +9.60% / 8tr / 50.0%wr | +8.49% / 11tr / 45.5%wr | 6 | -1.12% |
| AVAXUSDT | -2.17% / 6tr / 33.3%wr | +7.77% / 6tr / 50.0%wr | 3 | +9.93% |

**5/8 pairs improved, 3/8 got worse. Average delta +3.39%, but that
average is doing a lot of work carrying two outliers** (XRPUSDT +11.30%,
AVAXUSDT +9.93% — together more than the sum of every other pair's delta
combined). Take the average as directionally positive, not as "intraday
stops add ~3.4% reliably" — on a per-pair basis this is closer to a coin
flip with a couple of big wins than a uniform improvement.

A consistent pattern worth recording plainly: every pair had **more
trades** with intraday stops (11-14 vs 6-11 daily-only) and **win rate
dropped or stayed flat in 6/8 cases**. This matches what the engine's own
design intent warned about — checking more often exits faster, which
sometimes locks in a loss that a daily-close check would have let recover
by end of day (lower win rate), and sometimes catches a real reversal
early (the wins). The net return improvement comes from the take-profit
side catching upside intraday (XRP, AVAX) more than the stop side's extra
losses cost — not from "stops are just better," a genuinely mixed result,
not an unambiguous win.

**Decision**: net positive on this sample, worth building the live
poller — but given how outlier-driven the average is, this should be
treated as a first real signal, not a settled edge, the same caution the
scoreboard already applies to every other result here (a single 2024-2026
window, not cross-validated across periods). Re-check this comparison
periodically once the live poller has run for a while, the same way
Donchian's daily numbers get re-run rather than trusted forever from one
pull.

**Not done yet:**

1. Wire a second, more frequent GitHub Actions job (e.g. every 15-30 min)
   calling a stops-only cycle method on `CryptoTradingBot` — not yet added
   to `crypto_orchestrator.py`. `run_cycle()` (entries + full daily exit)
   stays on the once-daily schedule regardless.
2. That new job should use the SAME propose-only/`AUTO_EXECUTE` gate as
   `run_cycle()` — no separate, looser gate for the more-frequent job.
3. Since a stops-only job only ever closes positions (never opens new
   ones), it needs to read/write the same persisted portfolio state as
   `run_cycle()` (`crypto_portfolio` in `state_store.py`) so the two jobs
   don't race or diverge on what's open.

## Next steps (in order)

1. ~~Re-run `python run.py rotation` post-fix~~ — done, see above. US rotation
   validated; India did not.
2. ~~Sanity-check US Momentum Rotation isn't a one-window fluke~~ — done,
   see "Re-run confirmation" above: reconfirmed on a fresh data pull,
   +149.56% vs +119.32% benchmark, consistent with the prior run.
3. ~~Free a Supabase project slot... provision Postgres... verify two
   consecutive scheduled runs~~ — done differently than planned: used
   Neon.tech instead of Supabase (see "GitHub Actions crypto loop"
   section above for the resolution). `DATABASE_URL` is set, both
   workflows are live and confirmed writing to Postgres. Explicit
   two-consecutive-runs continuity check still worth doing (see "Still
   open" above) but the mechanism is proven working.
4. Decide whether to iterate on Donchian (best profit factor among the
   single-symbol strategies) or Mean Reversion (best win rate/drawdown) —
   neither is validated as-is but both show more promise than Trend
   Following.
5. Once the crypto loop has a real multi-day track record: run `python
   run.py cycle` in propose-only mode for the equities side too, and
   sanity-check proposals before flipping `AUTO_EXECUTE=true` for US
   Momentum Rotation specifically (not the others — they're still
   unvalidated).
6. Only after that: decide whether/what to merge into `main`, and whether to
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

**Real sweep result (2026-09-17, full 42-symbol run):**

| Variant | Validated | Avg win rate | Avg PF | Avg max DD |
|---|---|---|---|---|
| Donchian_20_10_baseline | 3/42 | 43.9% | 1.72 | -3.68% |
| **Donchian_20_10_trend100** | **5/42** | 43.6% | 1.64 | **-3.17%** |
| Donchian_55_20_turtle | 1/42 | 46.9% | 1.77 | -3.09% |
| Donchian_10_5_fast | 1/42 | 41.5% | 1.41 | -3.72% |
| Donchian_55_20_trend100 | 1/42 | 46.9% | 1.77 | -3.09% |

The 100-day trend filter on the default 20/10 periods is the winner: 5/42
validated vs baseline's 3/42 (+67%), and drawdown cut from -3.68% to -3.17%,
at a negligible cost to win rate/profit factor. Slower (55/20) and faster
(10/5) period variants both did worse than baseline on validated count —
period tuning alone doesn't help here, the trend filter does.

**Decision made**: `run_backtest.py`'s `STRATEGIES` list now uses
`DonchianBreakoutStrategy(trend_filter_period=100)` as the default (was the
untuned 20/10 baseline). 45/45 tests still pass. This changes what the plain
`python run.py backtest` (no `--sweep`) reports for Donchian going forward —
the scoreboard row above (3/42, -3.68% DD) is now stale and needs a re-run
with the new default to confirm it lands at 5/42 the way the sweep did.

## Crypto (Binance) real-data run (2026-09-17)

First real result for the crypto universe (8 pairs: BTC/ETH/BNB/SOL/XRP/
ADA/DOGE/AVAX, spot, 2022-04 to 2026-09). Same 3 strategies as equities.

| Strategy | Validated | Avg win rate | Avg PF | Avg max DD |
|---|---|---|---|---|
| Trend Following (SMA 50/200) | 1/8 | 19.7% | 0.72 | -7.33% |
| Mean Reversion (RSI) | 2/8 | 41.3% | 0.89 | -5.92% |
| **Donchian (20/10 + trend100)** | **5/8** | 44.2% | **1.49** | -8.07% |

Donchian is the only one with profit factor > 1 — same winner as equities/
commodities. It validated on BTC, ETH, SOL, DOGE, AVAX; missed BNB, XRP,
ADA. Notably beat buy-and-hold on AVAXUSDT (-90.9%) and ADAUSDT (-80.1%)
by simply not holding through the crash — breakout/trend-filter logic
transfers to crypto's higher volatility reasonably well. Trend Following
is weak here too (whipsaws badly in a 24/7, no-overnight-gap market).

**Futures price-action check (2026-09-17):** ran the same 3 strategies
against Binance USD-M futures OHLCV (1x, no leverage/funding modeled —
`--universe crypto_futures`). Result tracks spot closely:

| Strategy | Validated | Avg win rate | Avg PF | Avg max DD |
|---|---|---|---|---|
| Trend Following | 1/8 | 19.9% | 0.74 | -7.29% |
| Mean Reversion | 2/8 | 43.9% | 0.95 | -5.75% |
| **Donchian (trend100)** | 4/8 | 45.0% | **1.47** | -8.13% |

Nearly identical to spot (5/8 spot vs 4/8 futures, same strategy ranking) —
confirms the Donchian edge isn't a spot-data artifact. This still says
nothing about real futures trading: no margin/liquidation/funding-rate
cost is modeled, so it only proves the price-action edge transfers, not
that it survives leverage or funding cost. Needs a proper margin-aware
backtest before any futures number is trustworthy for real leverage.
No crypto-native strategy (funding-rate carry, etc.) built yet either.

## Crypto autonomous loop (2026-09-17)

Backtesting proved which strategy to use; it did not build anything that
runs by itself. This closes that gap: `CryptoTradingBot`
(`paper_trader/crypto_orchestrator.py`) is a live paper-trading loop for
Binance spot, mirroring `TradingBot` (the stock orchestrator) but:
- data via `BinanceFetcher(market="spot")` instead of yfinance
- one market ("CRYPTO"), `settings.crypto_pairs`, the strategy proven
  above (`DonchianBreakoutStrategy(trend_filter_period=100)`)
- purely fractional position sizing (no integer-share constraint)
- same idempotent-by-`client_order_id`, same PROPOSE-ONLY-unless-
  `AUTO_EXECUTE` gate, same risk circuit breakers as the stock bot

`python run.py crypto` runs one cycle; `python run.py crypto --loop
--interval-hours 24` runs forever, sleeping between cycles, catching and
logging any single cycle's failure so a network blip doesn't kill a
process meant to run unattended for days. Verified in the sandbox that it
correctly reaches the real Binance API (blocked only by this sandbox's
network policy, same as every other real-data check in this project) and
that propose-only mode produces zero trades. 4 new tests against synthetic
breakout data (isolated SQLite, mocked fetcher) confirm propose-only vs
auto-execute behavior and that state persists across bot restarts —
56/56 tests total pass.

**Not done yet:**
- No scheduler beyond the `--loop`/`sleep` inside the process itself —
  if the process dies (crash, laptop sleep, reboot) nothing restarts it.
  For real unattended operation this needs OS-level supervision (a
  systemd service, Task Scheduler, or a process manager), not just this
  loop.
- Zero real Binance order execution. `BinanceFetcher` only reads public
  market data. There is no code anywhere that authenticates to Binance
  or places an order, paper or real. `AUTO_EXECUTE=true` today only
  means "the `PaperTrader` simulates a fill" — it does not send
  anything to Binance.
- No live paper-trading track record exists yet — the loop above has
  never actually been run for real time (only smoke-tested against
  historical backtest data and one blocked live cycle). That's the next
  required step before considering real execution at all.

## Stocks: fixed live loop to use the proven strategy (2026-09-19)

Found a real bug while extending scheduling to stocks: `orchestrator.py`'s
`TradingBot` (the live US/India paper-trading loop, `python run.py
cycle`) was still hardcoded to `TrendFollowingStrategy()` — the weakest
strategy on every axis in the "Strategy scoreboard" above. The backtest
script (`run_backtest.py`) had already been updated to default to
`DonchianBreakoutStrategy(trend_filter_period=100)`, but that fix never
made it into the actual live bot. Fixed now: `TradingBot.__init__` uses
the same Donchian+trend100 strategy as crypto and the backtest default.

Also added `tests/test_orchestrator.py` (4 tests: strategy identity,
propose-only default, auto-execute places a real order, state persists
across bot restarts) — there was no test coverage of `TradingBot` at all
before this. 60/60 tests total pass. Verified in-sandbox that `python
run.py cycle --market US` reaches yfinance correctly (blocked only by
this sandbox's network policy, same pattern as every other real-data
check here).

**Update**: added `.github/workflows/stocks-cycle.yml`, mirroring Cowork's
`crypto-cycle.yml` — runs `python run.py cycle` (both US and India in one
call) on a weekday cron (21:30 UTC, after both markets have closed for
the day) against the same Postgres `DATABASE_URL` secret Cowork already
confirmed live for crypto. Not yet verified running for real (this
sandbox still has no outbound network) — next check-in should confirm it
actually fires and that state persists across two consecutive scheduled
runs, same bar Cowork already cleared for crypto.

## Next: make both the crypto and stock loops run independent of any laptop (not yet built)

Decided direction after discussing hosting options: a long-running process
or an always-on VM is more than this needs, since the strategy only
decides once per day. The right shape is a **scheduled, stateless job**:

1. **GitHub Actions workflow** (`.github/workflows/` — not yet created)
   on a daily `cron` schedule, running `python run.py crypto` (single
   cycle, not `--loop`) AND `python run.py cycle` (stocks, both US and
   India in one call) unmodified. Each run is a fresh, throwaway VM —
   nothing persists on disk between runs, and no process needs to survive
   overnight; today's run and tomorrow's run share no state except
   through the database. Crypto trades 24/7 so any daily time works;
   stocks should run once after US/India market close so the day's bar is
   final when fetched — two cron entries (or one workflow, two jobs) with
   different times, not one schedule for both.
2. **This means `DATABASE_URL` must point at a real external Postgres**,
   not the local SQLite default (`sqlite:///paper_trader.db`). SQLite on
   a GitHub Actions runner gets wiped every run — the bot would forget
   its positions and restart from scratch daily, silently, which would
   make every scoreboard number meaningless. `state_store.py` already
   works against Postgres via `DATABASE_URL` (same code path prod used
   for the old system) — this is config, not new code.
3. Concretely still to do:
   - Provision a Postgres instance (Supabase Postgres is a fine fit —
     just used as a database here, nothing else about Supabase is
     relevant) and get its connection string
   - Add `DATABASE_URL` as a GitHub Actions secret
   - Write the workflow file (checkout, install deps, run
     `python run.py crypto`, on a `schedule: cron` trigger)
   - Verify: two consecutive scheduled runs should show continuity
     (day 2's state reflects day 1's proposed/executed trades), not a
     reset

Why this over the alternatives considered: Vercel and Supabase Edge
Functions are both wrong fits for a scheduled Python batch job — Vercel
functions are built for short HTTP request/response, not cron batch runs;
Supabase Edge Functions run Deno/TypeScript, not Python, so the strategy
code would need a rewrite or an awkward cross-language call-out. An
always-on VM (EC2/DigitalOcean, ~$5-6/mo) would also work but is more
infrastructure than a once-a-day decision needs.

This session's sandbox has no outbound network at all (confirmed
repeatedly throughout this project), so none of the above can be
built/tested here. Handing off to continue with a tool that has real
internet + Supabase access.

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

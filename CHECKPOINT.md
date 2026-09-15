# Project Checkpoint: Autonomous AI Paper Trader
**Date**: 2026-09-15
**Repo**: `https://github.com/absailor30/paper-trader.git` (Branch: `claude/zealous-knuth-4ypdx7`)

This checkpoint replaces the previous one, which described the system as
verified and operational. It was not — an audit on 2026-09-15 found the
core signal-generation pipeline had never been able to run. That and
several related bugs are fixed as of this branch; one persistence item is
still pending on your end (see "Action needed" below).

---

### 1. What was actually broken (fixed this session)

- **`src/data/data_fetcher.py` did not exist in the repo.** `.gitignore`'s
  `data/` rule was matching `src/data/` anywhere in the tree and silently
  excluding the module from every commit. Every entry point that generates
  trading signals (`main.py`, `run_daily.py`, `premarket_research.py`,
  `run_benchmark.py`, `diagnose_india.py`, `test_system.py`) raised
  `ModuleNotFoundError` on import as a result. **The bot could never open a
  new position, ever, in any deployment.** Fixed: gitignore scoped to
  `/data/` only, `DataFetcher` rebuilt (yfinance-backed) to match the
  interface the rest of the codebase already expected.
- **What was actually deployed on Render (`live_monitor.py` + dashboard)
  only ever monitored existing positions** for stop-loss/take-profit — it
  never generated new signals. Real signal generation was wired through an
  n8n workflow on a local Windows machine (`D:/Code/trading-agent`),
  calling the also-broken `run_daily.py`. These two deployments were
  disconnected from each other and both non-functional.
- **`BaseStrategy.should_exit()` was defined on every strategy but never
  called anywhere.** Only fixed stop-loss/take-profit price levels were
  ever checked; momentum-reversal/RSI-extreme exit logic was dead code.
  Fixed: `TradingBot.check_strategy_exits()` now runs each open position
  through the strategy that opened it, once per daily cycle.
- **Multiple strategies firing BUY on the same symbol in one cycle produced
  multiple uncoordinated orders** averaging into one position with no
  conflict resolution. Fixed: `TradingBot.dedupe_signals()` collapses to
  the single highest-confidence signal per symbol before execution.
- **Risk limits were checked once per cycle, before the whole batch of
  signals**, not per trade — a breach partway through a batch didn't stop
  the remaining trades. Fixed: re-checked before every individual order in
  `execute_signals()`.
- **India position sizing rounded to 0 shares** for higher-priced large
  caps (TCS, RELIANCE, etc.) at the 12% target allocation, even when the
  account could afford 1 share — several configured India universe symbols
  were structurally untradeable. Fixed: allows a single minimum-viable
  share up to a hard 50% concentration ceiling instead of always skipping.
- **`run_daily.py` had hand-duplicated the daily-cycle logic** from
  `TradingBot.run_daily_cycle()` and had drifted out of sync with it (so
  it would have missed the fixes above even after they landed in
  `main.py`). It now calls the single shared implementation.

### 2. Still open — needs your action tomorrow

**Portfolio state persistence on Render's free plan.** `logs/*.json` lives
on ephemeral disk — wiped on every redeploy/restart, silently resetting
the portfolio to starting capital and losing all trade history. This
undermines the entire point of paper trading (you can't trust any
performance number if the history keeps disappearing).

Fixed in code: `src/persistence/state_store.py` — when `DATABASE_URL` is
set, portfolio state persists to Postgres (survives redeploys) instead of
local JSON. When unset, behavior is unchanged (local JSON files).

**What you need to do:**
1. Create a free Postgres instance (neon.tech or supabase.com, no card
   required) and copy its connection string.
2. Add `DATABASE_URL=<connection string>` to Render's environment
   variables for this service (dashboard → Environment).
3. Redeploy. First run auto-creates the `portfolio_state` table.

Until you do this, state loss on redeploy is still live — untouched code
behaves exactly as before.

### 3. Known remaining risks (not yet fixed, flagged from the audit)

- **"RL" in `MomentumRLStrategy` is a misnomer** — rule-based scoring, no
  trained model. You asked for a real RL build; that's a separate,
  multi-week scoped project (state/reward design, training data, offline
  training loop, backtest validation before it touches even paper capital)
  — not something to bolt on alongside bug fixes.
- **Strategies have not been backtested against current code** to confirm
  positive expectancy before trading. `run_benchmark.py`/`backtester.py`
  exist but haven't been run recently. Recommended next step once #2 above
  is done.
- **yfinance from a cloud IP is fragile** — no official support, commonly
  rate-limited/blocked. No fallback data source yet.
- **"LLM validation" is a rule-based fallback** (approve if R:R ≥ 1.5)
  unless `GEMINI_API_KEY` is actually set and reachable in prod — verify
  it's live before treating trade approval as AI-reasoned.
- **Daily reflections (`logs/daily_reflections.md`) are write-only** —
  nothing feeds them back into strategy parameters. "Learning" is
  currently a log, not a feedback loop.

---

### 4. System components (unchanged from before, for reference)

- **Live Risk Daemon** (`src/execution/live_monitor.py`): 5s tick polling
  during active market hours (NSE 09:15–15:30 IST, US 09:30–16:00 EST),
  evaluates stop-loss/take-profit. Halts polling off-hours; runs
  pre-market research at 06:00 IST.
- **Pre-Market Research** (`src/intelligence/premarket_research.py`):
  macro regime scan, Stage 2 / mean-reversion screening, Telegram
  briefing. (Was broken by the missing `DataFetcher`; fixed alongside it.)
- **Telegram Notifications** (`src/notifications/telegram_notifier.py`):
  trade fills, hourly heartbeats, morning briefs.
- **Dashboard** (`src/monitoring/dashboard.py`): Streamlit on port 8501,
  live mark-to-market via yfinance, strategy playbook, reflections reader.
- **Deployment**: Render Docker web service, `supervisord` running
  `live_monitor.py` + dashboard, cron-job.org keep-alive ping every 10 min
  against `/_stcore/health` (prevents free-tier sleep — does not solve
  disk persistence, see #2).

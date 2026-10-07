# ARVEN — MASTER PROMPT (give this whole file to the coding AI)

You are a senior quantitative engineer + full-stack engineer taking over the repository `C:\Users\Victus\arven`
(Python 3.13, DuckDB + Parquet, pytest, Windows 11 laptop). Your job: **finish ARVEN into a real, always-on
signal product** with Telegram alerts, a new strategy, a multi-timeframe event-driven engine and a premium web interface —
**without breaking anything that already works**.

Read first, in this order: `CLAUDE.md`, `docs/current_state.md`, `docs/architecture.md`, `docs/roadmap.md`, then the code.
Never answer from memory about the repo; open the files.

---

## 0. Owner's goal (verbatim intent)

The owner wants ARVEN to become **a tool they can actually trade with** (signals for BTC/ETH/major perpetuals, delivered to
Telegram and to a beautiful website), with a new strategy, and to demonstrate it at a thesis defence. The diploma paper
itself is secondary. The owner wants "quality signals" and wants to start earning from them.

## 1. Honesty contract (non-negotiable — this is what makes signals worth trusting)

1. **Nobody can guarantee profit, and you must not write code, copy or UI text that implies it.** Show win rate, profit factor,
   expectancy in R, max drawdown, number of trades, costs, sample size and confidence intervals — never "guaranteed",
   "sure", "risk-free". Every page that shows signals carries a risk disclaimer.
2. **Current measured reality** (from `docs/current_state.md`, Stages 5–8): the three existing rule-based strategies lost
   money in all 16 walk-forward windows (mean −11.2 %), the ML meta-filter showed no replicated edge (ROC-AUC 0.42–0.60),
   and the first forward paper run was −14.9 % on baseline. So **today ARVEN has no proven edge.** "Teaching ARVEN to trade"
   therefore means: build a rigorous research loop that can *find and validate* an edge or honestly report that there is none.
   It does not mean tuning until the equity curve looks good.
3. **Signal grading gate.** Every strategy has a status shown everywhere (Telegram, web, API):
   - `EXPERIMENTAL` — default; no validated edge; signals are labelled "paper / not validated".
   - `VALIDATED` — only if ALL hold: positive net expectancy after costs on purged walk-forward windows (majority of
     windows positive, not just the mean), ≥ 100 simulated trades, beats no-trade / buy&hold / random-entry baselines,
     survives 2× slippage stress, and ≥ 30 forward paper trades with non-negative net expectancy.
   - `SUSPENDED` — automatic when forward performance degrades beyond a pre-registered threshold (e.g. rolling 30-trade
     expectancy < −0.3R or drawdown > 8R). Signals are then paper-only again.
   The owner must never be able to mistake an EXPERIMENTAL signal for a validated one.
4. ErkeScan's published numbers (Vertex PF 1.42 / 50.5 % / 104 trades / +19.4R; Helix PF 2.67 / 70.4 % / 135 trades / +58.2R)
   are **self-reported marketing figures, unverified**. Use the site only as a **product and UX reference**, never as
   evidence that any approach works. Do not copy its branding, texts, logo or assets — build an original design.
5. If a result is negative, say so plainly in `docs/current_state.md` and in the UI. A documented negative result is valid.

## 2. Engineering rules that stay (from CLAUDE.md — keep rules 1–11 exactly)

No look-ahead (`available_at <= t`), no leakage, chronological splits only, realistic costs (taker fees, slippage, funding),
fills at the next bar/1m open, worst case when SL & TP share a bar, `NO_TRADE` as the default for missing/stale data,
strict module separation (data / features / regime / strategies / ML / decision / risk / backtest), one code path for backtest
and live, **LLMs never produce trading numbers**, determinism (seeds, config hash, git commit in every run), tests for
everything important (leakage tests mandatory for every feature).

**Explicit approvals granted by the owner for this task** (these override the "ask first" lines in CLAUDE.md, nothing else):
- Writing application code for the phases in section 6, in order.
- A web frontend and a small HTTP API (CLAUDE.md's "no web frontends" was an MVP limit).
- New dependencies, only these and only if needed: `fastapi`, `uvicorn`, `httpx` (optional, stdlib is preferred),
  `websockets` (optional), and a Vite + React + TypeScript + Tailwind frontend toolchain. Add each to `pyproject.toml` /
  `package.json` explicitly; no others without asking.
- **Rule 12 (no real order execution) stays in force.** ARVEN emits signals. It never places orders, never stores exchange
  API keys with trading rights, never has order endpoints. (Copy-trading is out of scope.)

**Still requires the owner (stop and ask):** providing the Telegram bot token / chat id, an Anthropic API key, running the
sealed test, deploying anywhere outside this laptop, spending money, and any change to the honesty contract.

## 3. Safety net — nothing may break

Before changing anything: `git status` must be clean (commit or stash WIP on a new branch `feat/signal-product`), tag the
current head `pre-signal-product`, run the full suite and record the count (currently ≈1708 passed / 13 skipped).
Golden regression: the committed Stage 5 development backtest has `result_hash 3eca0a70…`. After the engine refactor, the
three existing strategies declared as 1h-trigger **must reproduce the identical `result_hash`**. Also keep
`tests/pipeline/test_stage5_no_ml_regression.py` green. Every phase ends with: full test suite green, `docs/current_state.md`
updated, a git commit with a clear message. If a regression appears, fix or revert the phase — never weaken a test.

## 4. Product reference — what ErkeScan does (studied from the public site; sign-in pages were not entered)

- **Screener:** all USDT futures in one table: price, 24h change, 1h volume, RVOL (5m), OI change (1h %), VDelta (5m),
  funding %, category tags (DeFi, L1, Privacy…). Filters on user conditions; market charts view.
- **Signals, two strategies with different horizons:** *Vertex* (BTC/ETH/large alts, long/short, staged profit-taking,
  position management) and *Helix* (swing, days–weeks, TP2 unlocks only after TP1 is confirmed, TP3 after TP2).
  Each signal has entry, stop, targets and later updates.
- **Public "verified history" page per strategy:** profit factor, win rate (break-evens excluded, stated), closed trades,
  cumulative result in **R multiples**, an equity curve (cumulative R), a table of recent closed trades (date, symbol, side,
  result in R, status win/loss/partial) and an R-definition footnote. History is visible without a subscription; live levels
  are gated. A "feed reconnecting" state exists when sync is down.
- **Telegram alerts:** new signals, position updates, user-created alerts. **Journal:** imported trades, fees/result, notes,
  mistake tags. Pricing is time-based (1/3/12 months). Dark luxury look: near-black background, warm gold accent, monospace numerals,
  EN/RU toggle, calm micro-interactions.
- Takeaways to implement *originally*: R-multiple reporting, a public history with honest stats, staged targets,
  a screener over many symbols, Telegram as a first-class channel, a journal with mistake tags, EN/RU.

## 5. Target system

```
Binance public data (REST poll, optional WS)  ──►  ingestion (1m truth) ──► DuckDB/Parquet (point-in-time)
                                                                   │
                      EventClock (bar-close events per TF) ◄───────┘
                                   │
            features per TF ──► MultiTFView ──► regime ──► strategies (each declares its own TFs)
                                   │                                │
                           decision engine ◄── ML meta-filter (1h only, optional)
                                   │
                              risk engine (veto/reduce only) ──► Signal (+ status grade, R-plan, TP ladder)
                                   │
        ┌──────────────────────────┼───────────────────────────────┐
   signal store (DuckDB)     Telegram notifier               HTTP API (FastAPI, read-only on market data)
   + paper tracker (R)       (Bot API)                        └─► Web app (React): Overview, Signals, Screener,
                                                                  Charts, Strategies/History, Journal, Lab, Health
```

### 5.1 Multi-timeframe event-driven engine
- A strategy declares `StrategySpec(id, version, context_tfs, setup_tf, trigger_tf, warmup_bars, allowed_regimes)` and is evaluated
  only on the close of its `trigger_tf`. Existing strategies: `trigger_tf = setup_tf = 1h`, `context_tfs = (4h,)`.
- `EventClock` protocol with a simulated implementation (from 1m history, strict time order, fixed documented tie rule) and a live
  implementation (bar confirmed closed + derived TF bars complete). Keep the old `Clock` for the legacy path.
- Per-TF causal feature tables (`features_<tf>`) + `MultiTFView` (trigger row + last *closed* higher-TF rows by backward as-of on
  `available_at`; raises `LookAheadError` otherwise). Truncation + perturbation leakage tests for every new feature and the view.
- Decision engine: candidates per event with a validity window; same vote/conflict rules. Risk engine: same 8 rules plus per-strategy
  risk budget and a global net-exposure cap (one net position per symbol, no pyramiding).
- Backtester: event loop over simulated events, **Stage 4 execution/costs/margin reused unchanged**.
- Multi-symbol: generalise from BTCUSDT to a configured list (BTC, ETH, then liquid majors) *only after* the single-symbol path is proven
  identical. Per-symbol data quality gates. Verify on Binance whether a gold perpetual (e.g. XAUUSDT) exists before promising gold.

### 5.2 Always-on runtime
- One long-running asyncio process (no Docker / queues / microservices): poll public 1m klines every 10–20 s, detect closed bars,
  backfill gaps before emitting, persist the last processed event (restart-safe, no duplicate/skipped signals), heartbeat file,
  stale data ⇒ `NO_TRADE`, graceful shutdown, structured logs. Windows: provide a wrapper/Task Scheduler "restart on failure" recipe
  and a power-settings note (a sleeping laptop is not 24/7).
- Avoid the known DuckDB trap: bulk-load via staged `COPY`, never `executemany` into PK tables.

### 5.3 Signal object (extend, do not break `core/signal.py` consumers)
`signal_id` (deterministic hash), symbol, side, strategy id+version, **strategy status grade**, event time, entry reference,
stop, **TP ladder (TP1/TP2/TP3 with unlock rules)**, risk fraction, **R-plan** (reward/risk per target), confidence, regime,
reasons, risk-check results, data/feature/config/git versions. Updates (TP hit, stop moved to break-even, closed) are separate
append-only events linked by `signal_id`. A paper tracker resolves every signal on 1m bars with the same cost model and records
results **in R and net of costs**; this feeds the public-style history and the grading gate.

### 5.4 Telegram integration (stdlib HTTP, no SDK; secrets only in `.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`)
- Messages: new signal (symbol, side, entry zone, SL, TP1–TP3, risk %, R-plan, strategy + **grade**, regime, 2–3 reasons, disclaimer),
  position update (TP hit / SL moved / closed with R result), daily summary, system alerts (data stale, process restarted,
  strategy auto-suspended).
- Commands: `/start`, `/status`, `/signals`, `/history`, `/strategies`, `/pause`, `/resume`, `/help`; allow-list of chat ids.
- Reliability: idempotent sends (dedupe by `signal_id` + event type, persisted outbox table), retry with backoff, rate-limit
  respect (429 `retry_after`), message edit for updates when possible, no secret in logs, dry-run mode and a **test-bot mode**
  used by tests with a fake HTTP server. Never block the trading loop on Telegram failures.

### 5.5 New strategy S4 — "Impulse-Retest" (derived from the owner's chart screenshots; hypothesis, not proof)
The owner's discretionary method: after an impulse, price retraces into a confluence zone (Fib 0.5–0.618 + demand/supply zone +
trendline), breaks the counter-trend line, retests, and runs toward Fib extensions (1.0 / 1.414 / 1.618 / 2.0 / 2.618).
Formalise it **causally** and pre-register every parameter:
- Swings: pivot of order *k* is confirmed only *k* bars after the extreme (`available_at` shifted accordingly).
- Impulse = last confirmed swing-low→swing-high (or reverse) on `setup_tf` with size ≥ *m*×ATR.
- Zone = Fib 0.5–0.618 of that impulse overlapping a rule-defined demand/supply zone (base candle before an impulse ≥ *n*×ATR).
- Trendline = line through the last two confirmed counter-trend pivots; trigger = close beyond the line **and** a retest that holds
  the zone on `trigger_tf`; stop beyond the zone/impulse origin (ATR-buffered), targets on extensions 1.0 / 1.414 / 1.618 with the
  TP2-after-TP1 / TP3-after-TP2 unlock rule.
- Timeframes: context 4h, setup 1h, trigger 15m. Write the spec in `docs/strategy_impulse_retest.md` *before* coding, with fixed parameters
  and a **log of every variant tried** (multiple-testing disclosure). No parameter optimisation on validation/test.
- Evaluate with the same machinery: development backtest, purged walk-forward windows, baselines, cost stress, per-regime breakdown,
  then forward paper. Report honestly even if it loses. Optionally add a second, slower "swing" strategy later (Helix-like) as a separate spec.
- Do not use the screenshots as labels or training data (hindsight, selection bias).

### 5.6 Web app (premium, original design — "wow", but data-honest)
Stack: FastAPI (read-only access to stored artifacts/market data, Server-Sent Events for live updates) + Vite + React + TypeScript +
Tailwind + `lightweight-charts` (TradingView open-source charting lib) + Framer Motion. Served locally (`arven web`).
Pages:
1. **Overview** — system health (data freshness, last event, runtime uptime), market regime, active signals, equity curve in R, today's activity.
2. **Live signals** — cards with entry/SL/TP ladder drawn on an interactive candle chart, status grade badge, countdown to next bar close,
   signal timeline/updates, "why" panel (features, regime, strategy votes, risk checks, ML probability) and optional LLM explanation (clearly labelled).
3. **Screener** — all configured USDT perps: price, 24h %, volume, RVOL, OI Δ, VDelta, funding, sort/filter/saved filters, sparkline, alerts to Telegram.
4. **Charts** — multi-TF candles with regime shading and overlays (zones, trendlines, Fib from S4, pivots).
5. **Strategies / verified history** — per strategy: grade, profit factor, win rate (break-even rule stated), trades, expectancy R, max DD, equity curve in R,
   closed-trade table, baselines comparison, walk-forward windows chart, cost-stress result, sample-size warning.
6. **Journal** — manual trade entries (or CSV import), fees, notes, mistake tags, R stats; separate from system signals.
7. **Research lab** — run/view backtests and WFO (read-only over artifacts), per-regime breakdown, hashes, `touched_test_set` flag, run log.
8. **Telegram & settings** — connection status, test message, alert rules, language EN/RU, theme.
Design language (original, not a copy of ErkeScan): near-black canvas with subtle gradient/noise, warm-gold + emerald/crimson semantic colours,
glass-morphism cards with soft borders, large monospace tabular numerals, smooth number/chart transitions, skeleton loaders, keyboard shortcuts,
fully responsive (phone-width ready), WCAG-AA contrast, `prefers-reduced-motion` respected, light theme optional. Empty/error/offline states
are designed, not afterthoughts. No fake data in production views: if data is missing, show an honest empty state. A clearly labelled
**demo mode** may use recorded real artifacts for the defence.
Security: bind to `127.0.0.1` by default; no secrets in the frontend; CORS locked; the API has no write path to market data or any execution code.

### 5.7 LLM layer
Keep Stage 9b/10 behaviour: LLM only structures news, writes explanations from computed payloads, answers Q&A from stored artifacts.
Test it once against the real Anthropic API when the owner provides a key (currently only fakes). Never let it set prices, sizes or actions.

## 6. Phases (do them in order; each ends with green tests + docs + commit; do not start the next if the gate fails)

| # | Phase | Gate |
|---|---|---|
| 0 | Safety net (section 3) | baseline suite count recorded, tag created |
| 1 | `StrategySpec`, `BarCloseEvent`, `EventClock` (+simulated), types & tests | ordering/availability/no-look-ahead tests |
| 2 | Per-TF features + `MultiTFView` + leakage suite | all truncation/perturbation tests pass |
| 3 | Event-driven backtest loop on top of Stage 4 execution | **identical `result_hash` for the 1h strategies**; 1708+ tests green |
| 4 | Signal object v2, paper tracker in R, signal store, grading gate | hand-computed R/TP-ladder tests |
| 5 | Always-on runtime (poll, backfill, persist cursor, heartbeat) | 48 h soak on live public data: no duplicate/skipped events, correct stale ⇒ NO_TRADE |
| 6 | Telegram notifier + bot commands + outbox | fake-server tests; owner supplies token for a live test |
| 7 | Strategy S4 spec → implementation → full evaluation (dev, WFO, baselines, stress, per-regime) | honest report in `docs/`; grade assigned by the gate |
| 8 | HTTP API + Web app (all pages in 5.6) | Playwright smoke tests, Lighthouse a11y/perf ≥ 90, screenshots committed |
| 9 | Multi-symbol generalisation + screener metrics | single-symbol results byte-identical; per-symbol quality gates |
| 10 | Research loop: structured experiment log, pre-registered variants, WFO for S4 and any new idea; ML meta-filter retest only with ≥ 100 trades/window | no use of sealed test |
| 11 | Hardening: error budget, log rotation, backup of DuckDB/artifacts, crash-recovery tests, README + `docs/` + defence demo script | owner acceptance |
| 12 | **Sealed test: owner-approved, exactly once**, strategy/config frozen and hashed first; result published as-is | owner says go |

## 7. Definition of done / acceptance

- All pre-existing tests still pass; the golden `result_hash` for the 1h pipeline is unchanged.
- ≥ 14 days of continuous forward paper operation logged with zero missed/duplicated events and correct stale-data behaviour.
- Telegram: a real signal and a real update arrive in the owner's chat; restarting the process never re-sends old signals.
- Web app: every page loads real data, passes smoke + accessibility checks, looks premium on desktop and phone.
- Each strategy shows a grade computed by the gate, with sample size and confidence interval; no UI text overstates it.
- `docs/current_state.md`, `architecture.md` (A2, A3, section 4 and 9 changes with reasons) and `roadmap.md` updated; `README.md` explains setup,
  run, backup, troubleshooting.
- A short `docs/DEFENCE_DEMO.md` script: 10-minute walkthrough (data → features → regime → strategies → decision → risk → signal →
  Telegram → web → honest evaluation results).

## 8. How to work

- Think about each phase, then implement in small commits; run the relevant tests after each change, the full suite at phase end.
- Prefer boring, reliable designs. No clever abstractions the tests do not require.
- When uncertain about market facts (exchange symbols, endpoints, rate limits), check the official docs; never guess.
- If something cannot be done honestly (e.g. proving profitability), say so in the UI/docs and continue with what can be done.
- Never commit secrets, `.env`, `data/`, or API tokens. Never run anything that moves real money.
- At the end of every session, report: what changed, tests run (with counts), what is still not verified, and the next phase.

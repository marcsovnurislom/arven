# ARVEN — Current state

_Last updated: 2026-10-03 (Stage 8 paper-signal loop implemented, validated, and run on live data)_

## Phase

**Stage 8 (the paper-signal loop) is implemented, validated, and has produced the project's first genuinely
forward, out-of-sample result.** It needed almost no new execution/decision code — a new
`BacktestPeriod.FORWARD` plus a REST data tail let the real, unmodified Stage 4/5/6 pipeline run itself on
live data. See "Stage 8" below for the methodology, two real bugs found and fixed before the result was
trusted, and the live result itself (baseline −14.9% over 94.4 days; the logistic MetaFilter flat at +0.06%
on 2 trades) — consistent with Stage 7's finding that Stage 6's single-run +8.6% does not generalize.
- Stage 7 (walk-forward evaluation, WFO) is complete: implemented, validated, approved and committed (see
  below). Headline finding: Stage 6's single-run +8.6% result does not replicate under genuine walk-forward
  evaluation — see "Stage 7" below.
- Stage 6 (ML meta-filter) is complete: implemented, validated, approved and committed (`e9b7c72`).
- Stage 5 (regime, strategies, decision, risk) is complete: reviewed, approved and committed (`2298e5a`).
- Stage 4 (backtester) is complete: reviewed, approved (including the final `liquidation_includes_funding =
  true` decision) and committed (`8009719`, docs correction `a6da56b`).
- Stage 3 (features) is complete: reviewed, approved and committed (`6ac57d4`).
- Stage 2 is complete: the full backfill 2020-01-01 → 2026-07-01 is ingested and verified (see below).
- Split dates, the DuckDB index/storage design and the 300 s OI availability delay are unchanged. Stage 8
  changes no Stage 0-7 decision/execution logic: `src/arven/paper/` is new and additive, driving the real,
  unmodified `Backtester`/`Stage5Pipeline` via `runs.execute_run` (the same function `arven backtest run`
  uses); the only change to existing core code is one new `BacktestPeriod.FORWARD` member in
  `core/splitguard.py` (implementing a period `docs/architecture.md`'s own "Data periods" table already
  listed from the start, not a new design decision) plus one new config field
  (`download.rest_base_url`, excluded from `config_hash()` like the rest of the `download` section).
  `cli.py` gained additive `paper run`/`show`/`status` subcommands.
- Stage 7 changes no Stage 0–6 behaviour: `src/arven/wfo.py` and `src/arven/wfo_runs.py` are new, additive
  modules that only *call* Stage 6's existing, unmodified primitives (`generate_folds`,
  `purge_and_embargo_train_mask`, `validation_mask`, `run_walk_forward`, `select_threshold`, `fit_isotonic`)
  and the real, unmodified `Stage5Pipeline`/`Backtester`; `cli.py` gained additive `wfo run`/`wfo show`
  subcommands; no config schema, dependency, or existing-file logic changed.
- Stage 1 + Stage 2 are committed on branch `feat/historical-data` (commit `efb6677`), followed by a docs commit
  (`4be9329`), the Stage 3 commit (`6ac57d4`), the Stage 4 commit (`8009719`), a docs-only correction
  (`a6da56b`), the Stage 5 commit (`2298e5a`), the Stage 6 commit (`e9b7c72`) and the Stage 7 commit
  (`aa43c1b`). Stage 8 is included in this commit.

## Stage 3 — features (v1)

**What was built** (see "What exists" for files): a causal feature builder that turns the stored 1m-derived bars,
funding and open interest into **61 columns per 1h bar close** (56 952 rows, 2020-01-01 00:00 → 2026-06-30 23:00 UTC),
cached as `data/features/v1/features_1h.parquet` + `manifest.json`.

**Feature groups (v1)** — every window is in `config/features.yaml`:

| Group | Columns |
|---|---|
| Returns | `h1_ret_{1,4,24,72,168}`, `h4_ret_{1,6,30}`, `m15_ret_{1,4}` |
| Volatility | `h1_atr_pct`, `h4_atr_pct`, `h1_cc_vol_{24,168}`, `h1_vol_ratio`, `h1_parkinson_24`, `m5_rv_{1h,24h}` |
| Trend | `h1_/h4_ema_dist_{20,50,200}`, `h1_/h4_ema_slope`, `h1_/h4_adx`, `h1_donchian_pos_{24,168}` |
| Momentum | `m15_/h1_/h4_rsi`, `h1_macd_hist`, `h1_bb_z`, `h1_bb_width` |
| Volume / candle | `h1_rel_volume`, `h1_rel_trades`, `h1_/h4_taker_buy_ratio`, `h1_body_ratio`, `h1_upper_wick`, `h1_lower_wick` |
| Funding | `fund_rate`, `fund_z`, `fund_sum_last_3`, `fund_hours_to_next`, `funding_available` |
| Open interest | `oi_chg_{1,4,24}h`, `oi_z`, `oi_top_ls_log`, `oi_taker_ls_log`, `oi_age_s`, `oi_available` |
| Time | `time_hour_{sin,cos}`, `time_dow_{sin,cos}` |
| Quality | `feat_ready` (1 if every *required* feature is finite; OI features are optional) |

**Point-in-time rules as implemented**
- Decision time `t` = a 1h bar close. Row `t` uses only records with `available_at <= t`; the bar closing at `t` is included
  (with `bar_availability_delay_seconds > 0` it is not). Fills belong to the backtester (next bar's open).
- 4h / 15m / 5m data are joined to the 1h grid with a backward as-of join on `available_at` (`features/asof.py`, the only join
  used). A bar older than its own timeframe is NaN, never carried forward.
- Each timeframe is computed on a gap-free grid: missing or incomplete bars are NaN rows, so `shift(k)` means k bars.
- Rolling windows are explicit shifted additions; a NaN in a window gives NaN. **Recursive indicators (EMA, Wilder RSI/ATR/ADX)
  are seeded at the first stored bar and emit only after `ceil(5 × period)` valid inputs** (`warmup_factor`, configurable). A NaN
  input resets them. Consequence: `h4_ema_dist_200` needs 1 000 4h bars, so the first `feat_ready` row is
  **2020-06-15 16:00 UTC** (52 951 ready rows).
- **Builds always start at the first stored bar.** Dropping early history changes recursive features slightly (tested and documented),
  so the cache is the canonical form; a live loop must compute over the same history (Stage 8, renumbered 2026-10-01).
- Nothing is interpolated or forward-filled. Values are NaN or finite, never ±inf.
- Missing-data policy (settles former Stage 3 input decisions):
  - **OI**: latest snapshot with `available_at <= t`, used only if its timestamp is ≤ `open_interest.max_staleness_seconds`
    (900 s) old. OI changes and the z-score use hourly as-of values, so source gaps yield NaN instead of shifting windows; the
    z-score needs ≥ 90 % of the trailing 720 h. OI features are NaN before 2020-09-01.
  - **Funding**: latest record with `available_at <= t`, NaN if older than 1.5 intervals; windows count *contiguous* settled fundings.
  - **Zero-volume bars**: 0/0 ratios are NaN (e.g. taker-buy ratio), a real 0 volume gives `rel_volume = 0`.
  - **2021-05-15 00:20 anomaly**: the 1m-derived values are used as decided in Stage 2; nothing is patched.

**Validation (2026-09-28)**
- Full suite: **403 tests pass** (109 from Stages 1–2, 294 new). New: `tests/features/` (indicators against hand-computed cases
  and naive references, as-of/alignment, warm-up declarations, funding/OI policies, config, registry, builder, cache) and
  `tests/leakage/`.
- Leakage suite (`tests/leakage/`): for **every** registered feature, a **truncation test** (row at `t` from all data equals the
  row from only data available at `t`) and a **perturbation test** (replacing everything that became available after `t` with
  garbage changes nothing), both bitwise-exact; also with a bar availability delay and late-published funding. **Canary tests**
  prove the checks catch a future-close feature, a centred rolling mean and a full-sample z-score, and do not flag a causal control.
  **Static rules** (AST scan): no `shift(-k)`, centred windows, `bfill`/`ffill`/interpolation, whole-series mean/std/rank/quantile,
  and `features/` imports nothing from `data`, storage, `ml`, `strategies`, `risk`, `backtest`, `regime`, etc.
- Real-data spot check (`ARVEN_REAL_DATA_TESTS=1 ARVEN_REAL_DATA_SAMPLES=200`, development period only, read-only; inputs end at
  2023-07-01): **passed**. Truncation test at 235 decision times (200 random from 2020-07 on, 25 early, 7 hand-picked: OI start
  2020-09-01, the 2021-06-22 OI gap, the 2021-05-15 anomaly, 2021-12 and 2022-03) and perturbation test at 13 of them: no feature
  changed, all 61 columns compared bitwise. Also: `h1_ret_1`/`h4_ret_1` equal an independent SQL computation at 25 random times,
  and value invariants hold on all 30 648 development rows. Runs in about 1 minute.
- Real build: 6.7 s, **peak working set 282 MB** (target < 500 MB). Two consecutive builds gave the identical content hash
  (`c06b09e7…`); the manifest records definition hash, feature-config hash, app-config hash, source-data fingerprint, git commit.
- `arven features check`: definition hash, column list, content hash and value invariants (RSI/ADX in [0,100], ratios in
  [0,1], no ±inf) all pass. Statistics are printed for the **development period only**; the sealed test period was not inspected.

**Data findings surfaced by the feature build (not pipeline bugs)**
- Binance metrics files have **empty `sum_toptrader_long_short_ratio` for almost every row from 2021-12 to 2022-12** (only parts of
  2022-06 and 2022-12 are filled) and **empty `sum_taker_long_short_vol_ratio` from 2021-12 to 2022-05**. The stored NULLs match
  the raw files (Stage 2 verified stored vs raw). So in the development period `oi_top_ls_log` is NaN for 44 % of rows and
  `oi_taker_ls_log` for 29 %; `oi_chg_*` / `oi_z` are NaN for 19–22 % (mostly the pre-2020-09 boundary).
- `oi_age_s` has mean 300.1 s (the publication delay) and maximum 900 s (the staleness limit) in the development period.

## Stage 4 — backtester

**What was built** (see "What exists" for files): a deterministic, event-driven 1m execution backtester. It turns a
`SignalProvider`'s `Signal`s (decided at each 1h bar close, from Stage 3's `feat_ready` grid) into fills, funding
settlements, exits and a full order/fill/trade/equity ledger, with fees, slippage, isolated margin and liquidation.

**Execution model**
- **Clock:** `SimulationClock` iterates the pre-computed 1h decision grid of the requested window; nothing in
  `backtest/` reads the wall clock (`test_backtest_static_rules.py` enforces this with an AST scan).
- **Decision → order → fill:** at `t`, the provider sees a `FeatureView` (raises `LookAheadError` for any row after
  `t`) and a `PortfolioSnapshot`, and returns a `Signal | None`. LONG/SHORT becomes an order that fills at the open
  of the 1m bar at `t + latency_minutes` (default: `t` itself, i.e. the next bar). If that bar is missing, the order
  is `CANCELLED(no_market_data)` — no forward search.
- **Costs:** taker fee (`costs.yaml`), and slippage = `s * (fixed_bps + volatility_multiplier * bar_range_bps) / 1e4`
  on the fill/exit bar's own range (`s` = `stress_multiplier` with `--stress`), adverse to the trade direction.
- **Sizing / leverage / margin:** `notional_fraction * equity`, rounded down to `qty_step_btc`; rejected (with a
  reason, never resized) if it exceeds `leverage`, falls below `min_notional_usdt`, or the isolated margin
  (`notional / leverage`) plus the entry fee exceeds the wallet.
- **Stop/target/time-stop:** distances are fractions of the fill price. In one bar, an adverse level (stop or
  liquidation) always beats the take-profit; between two adverse levels the one nearer the entry triggers first. A
  stop the market gaps through fills at the bar's open, never at the stop level. A target never fills better than
  its level.
- **Funding:** settled from the recorded rate at each funding timestamp while a position is open (entry instant
  excluded, exit instant included), at `qty * open-price-at-that-minute * rate`; a missing rate aborts the run by
  default (`costs.funding.missing_policy`).
- **Liquidation:** `liquidation_includes_funding` (new; see open issue #13) — **true** (current default): funding is
  debited from the position's isolated margin, so the liquidation price moves with the margin balance and equity can
  never go negative; **false**: the plan's original model (liquidation price fixed at entry, funding never triggers
  it — which a real long-held position with persistent positive funding can push into negative wallet equity, see
  #13). Either way, on liquidation the wallet loses exactly the (possibly funding-adjusted) isolated margin; no exit
  fee or extra slippage.
- **One position, no pyramiding:** a second entry signal while a position is open is `REJECTED(position_open)`; only
  an explicit `NO_TRADE(close_position=True)` closes early. Data gaps while a position is open close it at the first
  bar after the gap (`DATA_GAP`). An open position at the window end is force-closed at the last bar's close
  (`END_OF_PERIOD`).

**Point-in-time and split enforcement**
- `FeatureView` and `MarketData` are read-only, window-scoped, and every timestamp loaded is asserted inside the
  requested `AllowedWindow`.
- `SplitGuard.resolve(period, start?, end?)` is the only way to obtain an `AllowedWindow` (its constructor refuses to
  be called directly — `test_allowed_window_cannot_be_forged`). A range crossing a period boundary is refused. The
  sealed `test` period additionally needs `allow_sealed=True` and a non-empty `reason`; the access is appended to
  `data/backtests/sealed_test_log.jsonl` **before** any data is read, so even an aborted attempt is logged.
- Verified on real data: a development-period `arven backtest run` was refused for `--period test` without
  `--allow-sealed`/`--reason`, and no sealed-log entry was written for the refusal.

**Determinism and reproducibility**
- Money is float64 with a fixed operation order; the only randomness is `RandomEntry`'s, seeded from
  `SeedSequence(project.random_seed).spawn(n_seeds)[i]` (documented, and verified to match the plain
  `spawn_key=(i,)` construction).
- `result_hash` is a SHA-256 over the canonical (fixed column order, 10-decimals-rounded) CSV of every ledger; two
  independent runs of the same inputs give an identical hash (verified on real development-period data, and with
  golden hashes on three fixed synthetic scenarios in `test_report_determinism.py`).
- Each run's `run.json` records: `git_commit` + `git_dirty`, the feature cache's `definition_hash` /
  `data_sha256` (content hash) / `source_fingerprint`, a fingerprint of the 1m+funding arrays actually used,
  `app_config_hash`, `backtest_config_hash`, the period/window, `touched_test_set`, the provider's parameters and a
  `provider_hash`, the random-seed derivation, per-table hashes and `result_hash`. `arven backtest verify <run_id>`
  recomputes every hash from the written files and checks that no logged data range left the window.

**Correctness validation**
- **Independent oracle:** a deliberately separate, naive bar-by-bar reference implementation of the same
  specification (no shared code with the engine) matched the fast engine exactly (trades, exit reasons, funding,
  every decision-time equity value, final wallet) on 300 seeded random scenarios covering every exit reason.
- **~30 hand-computed accounting cases**, each with by-hand expected numbers: fees, slippage (with/without stress),
  take-profit/stop/gap-through/same-bar-tie/liquidation-vs-stop-vs-target ordering, funding sign and boundary timing,
  a missing funding rate (error and assumed-rate policies), each rejection reason, latency, end-of-period close,
  a frictionless buy-and-hold matching independent price arithmetic, and both liquidation models.
- **Accounting invariants** on 150 further random scenarios: `final_wallet = initial + Σ net_pnl`; per-trade
  `net = gross_ref - slippage - fees + funding (+ liquidation loss)`; fill price = fill bar's open (adjusted); one
  position at a time; notional ≤ leverage × equity; equity never negative when `liquidation_includes_funding=true`.
- **Leakage** (`tests/leakage/test_backtest_leakage.py`): `FeatureView` refuses future rows; **prefix invariance**
  (cutting all data at `T` leaves every trade closed before `T` and the equity curve up to `T` byte-identical) and
  **perturbation** (garbage after `T` changes nothing decided or completed at or before `T`), both on 25 seeded
  scenarios; a fills-at-next-open test (a price gap exactly at the decision time proves the fill is not the signal
  bar's close); a test-only provider with raw access to the market's future is caught by its impossible return
  (> 0.3 on a 30-day driftless random walk after costs), while 24 seeded `RandomEntry` runs on the same data show no
  edge before costs (mean gross PnL within 4 standard errors of 0) and a loss after costs matching the fee+slippage
  total almost exactly.
- **Static rules:** an AST scan forbids wall-clock/file/unseeded-random calls and enforces that `backtest/` imports
  nothing from `data`, `features`, `strategies`, `risk`, `regime`, `ml`, `decision` or `duckdb`, and that no
  lower-layer or later-stage package imports `backtest`/`runs`.

**Baselines on the real development period** (2020-01-01 → 2023-07-01, 1 277 days, repo `config/backtest.yaml` +
`costs.yaml`, `liquidation_includes_funding=true`, git `6ac57d47` + Stage 4 working tree, `touched_test_set=false`;
`arven backtest baselines --period development`, artifacts in `data/backtests/baselines-20260928T184751Z-b5abd36a/`):

| metric | no_trade | buy_and_hold | random p5 | random mean | random p95 |
|---|---:|---:|---:|---:|---:|
| total_return | 0 | −1.905 | −0.562 | −0.083 | 0.612 |
| net_pnl (USDT) | 0 | −19 046 | −5 616 | −829 | 6 115 |
| max_drawdown | 0 | 1.155 | 0.194 | 0.388 | 0.616 |
| n_trades | 0 | 1 | 100 | 100 | 100 |
| win_rate | n/a | 0 | 0.400 | 0.478 | 0.551 |
| profit_factor | n/a | n/a | 0.488 | 0.918 | 1.480 |
| fees (USDT) | 0 | 5.0 | 644 | 953 | 1 372 |
| slippage (USDT) | 0 | 4.2 | 325 | 476 | 693 |
| funding (USDT, signed) | 0 | −19 041 | −136 | −3.0 | 118 |
| turnover | 0 | 2.44 | 187 | 198 | 207 |
| exposure_time | 0 | 0.570 | 0.078 | 0.078 | 0.078 |
| sharpe | n/a | −0.205 | −1.099 | −0.149 | 0.808 |

- **no_trade:** equity exactly flat at 10 000 (asserted).
- **buy_and_hold** (`notional_fraction=1.0`, i.e. up to the 3× leverage cap): entered 2020-06-15 (the first
  `feat_ready` decision) at 9 293.92, and was **liquidated 2022-06-13** at a reference price of 24 004.01 — a net
  loss of 19 045.45 USDT (−190.5 % of the initial equity), *before* the price ever fell far enough alone: cumulative
  funding of −19 040.46 USDT over ~2 years eroded the isolated margin, and with
  `liquidation_includes_funding=true` that pulled the liquidation trigger price up to meet BTC's June 2022 decline.
  This is the same scenario that originally exposed the fixed-liquidation-price model's flaw (see open issue #13),
  now confirmed on real data: re-run with `liquidation_includes_funding=false` (the plan's original D11 model), the
  identical trade instead runs to `END_OF_PERIOD` and ends at 12 262.68 (+22.6 %) — but along the way, at
  2022-11-21 22:00 UTC, **equity reaches −2 585.50 USDT**, which no real isolated-margin account allows. Same market
  data, same entry, only this one switch differs (`result_hash` for `false`: `b55d9d0c…`).
- **random_entry** (200 seeds, 100 trades of 1 440 min = 24 h each, `notional_fraction=1.0`, 50/50 long/short): mean
  net PnL is negative (−829 USDT) and mostly a function of costs — mean fees + slippage + |funding| ≈ 953 + 476 + 3 ≈
  1 432 USDT, against a mean net loss of 829 USDT, so roughly two-thirds of the average loss is explained by
  round-trip costs on a direction with no edge, consistent with a fair coin flip. All 200 seed schedules and their
  `result_hash`es are stored in `random_entry/seeds.csv`; the seed-0 self-check reproduced exactly.
- These are baseline measurements of the simulator (its costs, its leverage/liquidation mechanics), **not evidence
  that any strategy is profitable** — no strategy exists yet.

**Known limitations, all deliberate MVP simplifications (documented, not bugs)**
- No maker fills (`require_taker_only` raises `ConfigurationError` if `costs.yaml` ever selects maker); no tiered
  maintenance-margin schedule; no order-book/market-impact model; single funding-interval assumption
  (`costs.funding.default_interval_hours`, informational elsewhere) drives the funding grid actually queried.
- `qty_step_btc`, `min_notional_usdt` and `maintenance_margin_rate` are stated assumptions, not verified against
  Binance's current live schedule (open issue #12).
- The 3 real strategies, the ML meta-filter and the risk engine are Stage 5/6 — the backtester takes a
  `SignalProvider`, not a strategy; only the 3 baselines exist in Stage 4, as the roadmap requires.

**Operational notes**
- `con.executemany` / a single large parameterised `INSERT` into a table with a `PRIMARY KEY` ART index is
  pathologically slow in the installed DuckDB version (≈20 ms/row; 5 000 rows ≈ 94 s — this is what caused the first
  integration-test run to hang for several minutes). Stage 2's own ingestion never hits this, since it loads via
  `COPY … FROM` a file. Test helpers now use the same idiom (`bt_helpers.bulk_insert_1m/_funding`, `COPY FROM` a temp
  CSV): 5 000 rows in ≈0.09 s. Nothing in `src/` was affected; this is a test-infrastructure fix only.
  **Update (Stage 8, 2026-10-03): this time it did affect `src/`** — `rest_ingestion.py`'s first implementation hit
  the exact same pitfall (measured ~33 s per 1000-row REST page) and was fixed with the identical staged-bulk-load
  idiom; see the "Stage 8" section above for the real run this was found on.

## Stage 5 — regime, strategies, decision, risk

**What was built:** a rule-based regime detector, three independent strategies, a decision engine (regime
gate + weighted vote) and a risk engine (8 ordered veto/reduce rules), wired into one
`Stage5Pipeline` that implements Stage 4's `SignalProvider` protocol unmodified — `arven backtest run
--provider pipeline` runs it exactly like the Stage 4 baselines.

**Regime detection** (`config/regime.yaml`, `src/arven/regime/detector.py`)
- **Trend** (`TREND_UP` / `TREND_DOWN` / `NO_TREND`): `h4_adx >= 20` **and** `h1_adx >= 15` (the 1h
  confirmation), then direction from the sign of `h4_ema_slope` agreeing with the sign of `h4_ema_dist_200`
  (price vs EMA200); any disagreement (including ADX high but slope/price disagreeing) is `NO_TREND`.
- **Volatility** (`LOW` / `NORMAL` / `HIGH`): percentile rank of `h1_atr_pct` in its own trailing window
  (causal — only bars up to and including `t`; NaNs filtered, not treated as zero), default window ~1 year
  (architecture's own wording), classified once at least 720 (30 days) valid values exist, `NORMAL` before that.
- **Stress** (flag, not an axis): `|fund_z| >= 3.0` or `|oi_chg_1h| >= 0.05` (log change).
- **Hysteresis:** a candidate trend state must be the raw classifier's output for `min_dwell_bars = 3`
  consecutive decisions (including the very first transition away from `NO_TREND`) before the detector
  actually switches; a reverting candidate resets its counter. Stateful, causal, reset at the start of every run.

**The three strategies** (`config/strategies.yaml`, `src/arven/strategies/`) — each reads only Stage 3
features, returns a `CandidateSignal(direction, strength, stop_pct, take_profit_pct, ...)` or `None`, and
never sees the other strategies, the portfolio, or the regime label (regime *gating* is config declared per
strategy and applied by the decision engine, not by the strategy):
1. **Trend/Momentum** (architecture #1): direction from the 1h EMA(20) vs EMA(50) relationship (derived from
   `h1_ema_dist_20 - h1_ema_dist_50`); a 4h filter requires `h4_adx >= 20` and the 4h EMA-slope sign to agree;
   optional MACD-histogram confirmation (on by default); blocked if `h1_rsi` is already extreme in that
   direction (75 / 25). Strength = `h4_adx / 50`, clamped. Stop = `1.5 × h1_atr_pct`, target = `3 × h1_atr_pct`.
   Gated to `TREND_UP`/`TREND_DOWN`, any volatility, not during stress.
2. **Breakout** (architecture #3, volatility breakout): a squeeze is detected causally — `h1_bb_width` must
   have been strictly below the 25th percentile of its own 480-bar (20-day) trailing window (percentile and
   squeeze check both computed **excluding the current bar**, so a bar can't set its own threshold) at some
   point in the last 48 bars (2 days); the trigger is `h1_donchian_pos_24` at or beyond 0.95 / 0.05 **now**.
   Stop = `2 × h1_atr_pct`, target = `3 × h1_atr_pct`. Gated to `NORMAL`/`HIGH` volatility, any trend.
3. **Mean Reversion** (architecture #2): contrarian on `h1_bb_z` beyond ±2.0, confirmed by `h1_rsi` beyond
   35/65 in the same direction. Stop = `1.0 × h1_atr_pct`, target = `1.5 × h1_atr_pct`. Gated to `NO_TREND`
   only ("RANGE" in the architecture's wording), not during stress.
- The 4th architecture strategy (funding/positioning contrarian) is out of the explicit Stage 5 scope and was
  not built.

**Decision engine** (`src/arven/decision/engine.py`) — architecture section 13, steps 1-3, 5, 6 (step 4, the
ML filter, is Stage 6 and was **omitted**, not stubbed):
1. **Regime gate:** each strategy's `allowed_trends`/`allowed_vols`/`require_not_stress` (config) filters its
   candidate out entirely if the current regime doesn't match; gated-out ids are kept for logging.
2. **Weighted vote:** `score = Σ weight_s × strength_s` over the *allowed* candidates, separately summed for
   each direction (`pos_mass`, `neg_mass`); `score = pos_mass - neg_mass`. Equal weights (1.0 each) by default.
3. **Conflict rule:** `pos_mass >= 0.35` **and** `neg_mass >= 0.35` (both, not just close) ⇒ `NO_TRADE`.
4. **Threshold:** `|score| < 0.35` ⇒ `NO_TRADE`. No candidates ⇒ `NO_TRADE`. These are also the *only* ways to
   reach `NO_TRADE` here — the default outcome is always `NO_TRADE` unless something actively clears both bars.
5. **Output:** the winning direction's contributing strategies, a weighted average of their stop/take-profit
   hints, the most conservative (shortest) of their holding caps, and `confidence = |score| / Σ(all weights)`.
- The decision engine never receives the portfolio (enforced by a static test on its signature): sizing and
  vetoing is entirely the risk engine's job.

**Risk engine** (`config/risk.yaml`, `src/arven/risk/engine.py`) — architecture section 14, an ordered
pipeline of independent rules, each vetoing or reducing, never creating/flipping a direction; rule 2 (macro
event blackout) is explicitly deferred there ("later stage" = Stage 9, renumbered 2026-10-01 — was Stage 8
before the Stage 7 WFO insertion) and was not implemented:
1. **Data-quality gate:** `feat_ready != 1` ⇒ veto `stale_or_incomplete_data`.
2. *(deferred to Stage 9)*
3. **Volatility guard:** `regime.stress` ⇒ veto `extreme_volatility_stress` (config `veto_on_stress: true`);
   `HIGH` volatility ⇒ size ×0.5.
4. **Funding guard:** entering the side that *pays* extreme funding (`direction × fund_z`) — ×0.5 at
   `|·| >= 2.0`, veto `extreme_funding` at `|·| >= 4.0`. Longs pay on a positive rate, shorts on a negative
   one (matches `arven.backtest.accounting`'s sign convention exactly — the same fact, not re-derived).
5. **Stop & target bounds:** the decision layer's hint is clamped to `[0.3%, 8%]`; the target is *extended*
   (never shortened) to meet `take_profit_pct >= stop_pct × 1.2` if it doesn't already.
6. **Position sizing:** `notional_fraction = risk_fraction_per_trade (0.75%) / stop_pct`, then the guard
   multipliers above, capped at `max_notional_fraction = 1.0` and at `config/backtest.yaml`'s `leverage` (one
   source of truth — risk.yaml does **not** duplicate leverage or `maintenance_margin_rate`).
7. **Portfolio limits** (checked early, before 3-6, since nothing downstream matters if any holds): a position
   or a pending order already exists ⇒ veto `position_already_open`; max daily loss 2% (UTC-day baseline,
   resets each day) ⇒ veto `max_daily_loss_halt`; running-peak drawdown ≥ 20% ⇒ veto `max_drawdown_halt` until
   it recovers to ≤ 15%; 3 consecutive losing trades ⇒ veto `loss_streak_cooldown` for 24 decision bars. All
   four are stateful and causal (driven only by the sequence of `PortfolioSnapshot`s the engine itself
   observes at each decision — never a peek at a future trade's outcome), reset at the start of every run.
8. **Liquidation-distance check:** the relative liquidation distance is a pure function of
   `(side, leverage, maintenance_margin_rate)` alone — **not of price** — reusing
   `arven.backtest.margin.liquidation_price` (one pure function; nothing here touches the engine, execution or
   accounting). Veto `stop_too_close_to_liquidation` if that distance is less than `1.5 ×` the (bounded) stop.
- A veto or a pass-through (`NO_TRADE` proposed) always returns `None` (no `Signal`) to the backtester; every
  outcome — pass, reduce, veto, or pass-through — is recorded with its reason and numbers in the pipeline's
  `DecisionRecord` history.

**Module separation, enforced mechanically** (`tests/pipeline/test_stage5_static_rules.py`,
`tests/backtest/test_backtest_static_rules.py`): `regime` imports nothing from `strategies`/`decision`/`risk`;
`strategies` imports nothing from `risk`/`decision`/`regime`/`arven.backtest.margin`; `risk` imports nothing
from `strategies`, and only `arven.backtest.provider` (types) + `arven.backtest.margin` (one pure function)
from `backtest`; `decision` imports nothing from `backtest` at all; nothing in any of the four imports
`arven.backtest.engine`/`execution`/`accounting` (would bypass the engine); no lower layer or Stage 6+ package
imports any Stage 5 package. The per-regime analysis report (`arven.reports`, see below) deliberately lives
**outside** `arven.decision` — it runs only after a backtest finishes and never feeds back into a live
decision, so it is not bound by the same separation rules, and a static test confirms the dependency stays
one-directional (`regime`/`strategies`/`decision`/`risk` never import `arven.reports`).

**Validation**
- **Unit tests** (`tests/regime/`, `tests/strategies/`, `tests/decision/`, `tests/risk/`): hand-computed cases
  for every rule branch of the regime classifier (including hysteresis/dwell and its reset), each strategy
  (using a hand-built `FeatureView` via the real Stage 3 column names, so a renamed column fails the test
  rather than silently reading NaN), the decision engine's gating/vote/conflict/threshold/confidence
  arithmetic, and all 8 risk rules including the 4 stateful circuit breakers. One real bug was found and fixed
  by these tests: the breakout strategy's compression check used `>` instead of a strict `<`, so a perfectly
  flat (untouched) `bb_width` series tied its own percentile and was wrongly read as "compressed" — fixed to
  `>=` (i.e. strictly below the threshold only).
- **Leakage / causality** (`tests/pipeline/test_leakage.py`): prefix invariance (cutting all data — both the
  Stage 3 feature table and the raw 1m market — at time `T` leaves every trade closed before `T` and every
  decision-time equity value up to `T` byte-identical) and perturbation (replacing everything after `T` with
  Stage-3-plausible garbage changes nothing decided or completed at or before `T`), each on 5 seeded 250-day
  scenarios; a further check that the regime detector's own hysteresis-state sequence up to `T` is identical
  under perturbation (proving the sequential state itself doesn't leak, not just the final trades). `FeatureView`'s
  existing `LookAheadError` guard (Stage 4) is exercised throughout, since every strategy/regime read goes
  through it.
- **Determinism / reproducibility** (`tests/pipeline/test_determinism.py`): two independent runs of the same
  inputs give an identical `result_hash`; reusing one `Stage5Pipeline` object for two `Backtester.run()` calls
  (as the engine does internally) gives the same result as two fresh objects — `prepare()` fully resets regime
  and risk state; the full decision history (not just the ledgers) reproduces exactly; `--stress` changes the
  result deterministically.
- **Accounting/execution integration** (`tests/pipeline/test_backtest_integration.py`): Stage 4's own
  invariants (`final_wallet = initial + Σ net_pnl`, one position at a time, notional ≤ leverage × equity, fill
  price = the fill bar's open, ...) hold on 30 seeded runs driven entirely by the Stage 5 pipeline on a
  volatile synthetic 1m market (needed for stops/targets/rare liquidations to actually trigger — the Stage 4
  test helper's default market is flat); every trade's tag carries its contributing strategies and regime;
  stop-exit R-multiples cluster near −1 and take-profit R-multiples clear roughly the configured minimum
  reward:risk ratio; liquidations stay under a sanity ceiling.
- **Real development-period data** (opt-in, `ARVEN_REAL_DATA_TESTS=1`, `tests/pipeline/test_pipeline_real_data.py`):
  the pipeline runs on the real database + Stage 3 v1 feature cache, reproduces its `result_hash` on an
  independent re-run, the sealed test period is refused without `--allow-sealed --reason`, the validation
  period is allowed and correctly marked `touched_test_set=false`, and the development run's own data-range
  log never reaches or exceeds its window's end.
- **Full suite:** 1338 passed, 8 skipped (3 Stage 3/4 + 4 Stage 5 opt-in real-data checks, 1 Stage-6-doesn't-exist-yet),
  ≈5 minutes. All 8 skipped tests pass when run with `ARVEN_REAL_DATA_TESTS=1` (verified together, 7 tests, ≈44 s
  — the 8th, the `ml` static-rule check, has no meaning until Stage 6 exists).

**Real backtest result** (development period, `arven backtest run --provider pipeline --period development`,
git `8009719`+working tree, `touched_test_set=false`, result_hash `3eca0a70…`, reproduced identically on an
independent re-run and via `arven backtest verify`):

| metric | value |
|---|---|
| trades | 111 (74 STOP, 37 TAKE_PROFIT, 0 liquidations) |
| total_return | −20.3% (final equity 7 973.83 from 10 000) |
| win_rate | 33.3% |
| profit_factor | 0.566 |
| max_drawdown | 20.6% (intrabar 22.3%) |
| sharpe | −1.43 |
| fees / slippage / funding | 829.19 / 640.69 / −7.04 USDT |
| exposure_time | 3.0% |

No parameters were tuned to make this positive (CLAUDE.md rule: "do not optimize parameters"), and this is a
measurement of the *framework* with unoptimized, architecture-derived defaults — not a claim that these three
strategies have an edge. The per-regime breakdown (`arven.reports.per_regime_breakdown`, printed by the CLI)
shows losses concentrated in `NO_TREND/LOW` (51 of 111 trades, −812 USDT) and `NO_TREND/NORMAL` (14 trades,
−635 USDT) — i.e. mean-reversion trades in quiet/normal-vol ranging conditions were the main drag — while
`TREND_DOWN/HIGH` was the only regime with a net positive contribution (+44.76 USDT, 7 trades). This is exactly
the kind of regime-conditional signal the roadmap's "per-regime analysis" deliverable exists to surface; it is
not evidence either way about whether the framework has value, only about where *this* unoptimized
configuration's losses concentrated.

**Known limitations, all deliberate MVP scope (not bugs)**
- No ML filter (Stage 6) and no macro-event blackout (Stage 9) — architecture explicitly places both later.
- No parameter search of any kind was performed or is provided (CLAUDE.md rule; the config values are the
  architecture's own stated defaults, e.g. "risk 0.5-1%" → 0.75%, "max leverage e.g. 3×" → uses `backtest.yaml`'s 3×).
- The regime volatility window (`window_hours: 8760`, "trailing 1-year") means the first ~1 year of the
  development period classifies mostly on partial history (`NORMAL` until 720 bars/30 days exist, then a
  percentile over a still-growing window) — matches the architecture's own stated window, not a shortcut.
- `arven.reports.per_regime_breakdown` attributes a trade to the regime at its **signal** time (when the
  decision was made), not its fill or exit time — the natural choice, since regime gating happens at the
  decision, but worth stating explicitly for anyone extending the analysis.

## Stage 6 — ML meta-filter

**What was built:** a `MetaFilter` that estimates `P(success)` for the single `ProposedDecision`
`DecisionEngine.decide()` already produced, and either passes it through unchanged or replaces its action
with `NO_TRADE`. It sits strictly between `DecisionEngine.decide()` and `RiskEngine.apply()` inside
`Stage5Pipeline`, wired through one new, optional constructor parameter (`ml_filter: MLFilterProtocol | None
= None`, default `None`) — with no filter, `Stage5Pipeline` is byte-identical to the committed Stage 5
behaviour (`tests/pipeline/test_stage5_no_ml_regression.py`, 9 tests). The ML layer can never flip direction,
create a trade, resize a position, change risk parameters, or bypass the risk engine or Stage 4 execution —
it has exactly two outcomes: pass or veto.

**Labels** (`src/arven/ml/labels.py`) — triple-barrier, resolved on 1m bars, net of the same cost functions
Stage 4 uses (`arven.backtest.costs.adverse_price`/`slippage_fraction`/`taker_fee_rate`; pure functions, not
the execution engine): stop/take-profit distances from the candidate's own hints, vertical barrier =
`max_holding_minutes`. Same-bar tie ⇒ stop wins (worst-case, matching CLAUDE.md rule 4). Label = 1 if net
return ≥ `min_net_return_for_positive_label` (0.0 — net-of-costs already implies "TP must exceed round-trip
cost"). `None` (unresolvable) if the fill bar is missing or the horizon runs past stored data. Documented
simplifications: no gap-through adjustment (uses the barrier level, not a gapped price — slightly optimistic
vs Stage 4's real fill model), no funding cost, no liquidation modelling in the label itself.

**Dataset construction** (`src/arven/ml/dataset.py`) — replays the *real* `RegimeDetector`, the real
`build_strategies`, the real `DecisionEngine`, and the real `RiskEngine` (imported directly, not
reimplemented — enforced by a static test) over development+validation, exactly as Stage 5 does, except every
candidate is risk-checked against a fixed, always-flat `PortfolioSnapshot` before being reset (D3): dataset
eligibility reflects each candidate's own merit — data-quality/stress/funding/stop-distance rules still
apply, only the *portfolio-state* rules (position-open, daily-loss halt, drawdown halt, cooldown) are
neutralised. This is deliberately not the same population a real backtest sees (which only opens one
position at a time), and is documented as such everywhere it matters. Feature row = 60 causal Stage 3
columns + 18 Stage 5 context columns (3 trend one-hot + 3 vol one-hot + stress flag + 3 contributing-strategy
flags + 3 contributing-strategy strengths + score + confidence + stop/take-profit/max-holding hints) = 78
columns total.

**Splits** (`src/arven/ml/splits.py`) — purged, embargoed, **expanding**-window walk-forward, date-agnostic
(takes plain start/end ms; a static test locks that it never imports `SplitGuard` or the app config — the
real development/validation boundary is resolved once, by the caller, through the existing `SplitGuard`, not
duplicated here). A training row is purged if its label horizon overlaps the validation block or falls within
`embargo_hours` (96) before it starts. `min_train_months=12`, `retrain_interval_months=3` (D4) — on
development+validation this produced **17 chronological folds**.

**Models** (`src/arven/ml/model.py`) — pure-numpy Newton's-method logistic regression (intercept never
regularized, deterministic) and a LightGBM adapter (`deterministic=True, force_row_wise=True,
num_threads=1`, all four seed parameters fixed from the project seed, early stopping). D7: LightGBM uses all
78 columns; logistic regression restricts the Stage-3-sourced portion to the 51 `required=True` Stage 3
columns (context columns are always finite, so aren't restricted) = 69 columns. Hyperparameters: a fixed grid
of ≤4 configurations per family (`config/ml.yaml`, D5), selected per walk-forward fold by mean validation
log-loss — no open-ended search, no sealed-test involvement anywhere. Calibration is isotonic only (D6,
stack-based PAVA), fitted on each fold's held-out validation rows, never the rows a model trained on.

**Model artifacts** (`src/arven/ml/artifact.py`) — every saved model carries the full provenance list agreed
in planning: model id/family, `git_commit`+`git_dirty`, feature/ML/app/backtest/regime/strategies/risk config
hashes, feature definition and content hashes, training/validation period bounds, random seed, the selected
hyperparameters, the complete per-fold walk-forward summary, a dataset fingerprint, the model artifact's own
SHA-256 hash, threshold, feature names, all candidate/ineligible/train/calibration row counts, raw and
calibrated metrics, warnings, environment, and `touched_test_set` (always `False` for a Stage 6 training
run — `arven.ml_runs` never resolves `BacktestPeriod.TEST`, checked both by test and by a static string
scan). `arven ml verify <model_id>` recomputes the artifact hash from the saved files.
- **One real bug found and fixed during implementation:** `LightGBMModel` originally stored the raw
  `lgb.Booster` object; pickling a freshly-trained Booster gave different bytes than pickling the same model
  after a save→load round trip (LightGBM reconstructs its pickled state from an internal text dump, and that
  round trip isn't byte-stable), so `arven ml verify` failed only for LightGBM models. Fixed by storing the
  canonical `model_str` text dump instead, with a `booster` property that reconstructs on demand; locked by
  `test_two_independently_trained_lightgbm_artifacts_with_the_same_seed_have_the_same_hash`.

**MetaFilter** (`src/arven/ml/filter.py`) — `build_row()` encodes the same 78-column row live, from the
`ProposedDecision` and the current `FeatureView` (never a later time — `FeatureView`'s existing Stage 4
`LookAheadError` guard is inherited unchanged, no new leakage-prevention code was written). `apply()` returns
the proposed decision unchanged if it's already `NO_TRADE` or `P(success) ≥ threshold` (0.55, D-approved
config default); otherwise returns it with the action replaced by `NO_TRADE` and the stop/target/holding
fields cleared. `RandomFilter` (control) — a seeded uniform rejection at a fixed rate, same interface, used
for the matched-rate control below.

**CLI** (`src/arven/cli.py`, additive only): `arven ml train --model-family {logistic,lightgbm}
[--shuffle-labels-seed N]`, `arven ml verify <model_id>`, `arven ml show <model_id>`; `arven backtest run
--provider pipeline` gained `--ml-model <model_id>` (loads a trained `MetaFilter`) and
`--random-filter-rate <p>` (the `RandomFilter` control).

**Module separation, enforced mechanically** (`tests/ml/test_ml_static_rules.py`,
`tests/leakage/test_ml_leakage.py`): `arven.ml` never imports the Stage 4 execution/accounting engine or
`duckdb` directly; the `lightgbm` package itself is imported only by `model.py` and `artifact.py` (the
version string); `regime`/`strategies`/`risk`/`decision` never import `lightgbm` or `arven.ml` (one-directional
dependency, ML depends on Stage 5, never the reverse); `features/` never imports `arven.ml.labels`
(forward-looking labels never reachable from causal feature code); `dataset.py` imports the real
`RiskEngine`, not a local reimplementation; `splits.py` takes only plain ms/int parameters, no
`SplitGuard`/app-config imports.

**Validation**
- **Leakage canaries** (`tests/leakage/test_ml_leakage.py`, 11 tests): all 5 planned deliberate-break types
  — (1) a future label folded into a feature column (structural: only `.label`/`.net_return` are ever read
  from a `LabelResult` into `x`), (2) a future feature read (`FeatureView`'s `LookAheadError`, exercised
  directly against `build_row`), (3) random temporal shuffling (a synthetic regime-flip dataset demonstrates
  shuffled train/test assignment looks *falsely* better than real walk-forward, and fold boundaries are
  proven monotonic/non-overlapping), (4) full-period normalisation (train-only standardisation is proven to
  differ from full-period statistics; calibration fit on a model's own training rows is proven to differ
  from a proper held-out fit), (5) sealed-test contamination (`arven.ml_runs` never resolves
  `BacktestPeriod.TEST`; a direct `.resolve(TEST)` raises `SealedAccessError`; fold generation is bounded
  exactly at `validation.end_ms`, never beyond).
- **Hand-computed label cases** (`tests/ml/test_labels.py`, 12 tests): known entry/stop/target/time-barrier
  combinations against by-hand expected outcomes and net returns, including a zero-cost control case and the
  same-bar-tie-favours-stop rule.
- **Purge/embargo property tests** (`tests/ml/test_splits.py`, 28 tests): exhaustive 20-seed property test
  that no purged training row's label horizon ever overlaps a validation block or falls inside the embargo.
- **Determinism**: two independent real-data training runs give identical `model_artifact_hash` and
  `training_dataset_fingerprint` for both model families (`tests/ml/test_ml_real_data.py`, opt-in;
  `test_two_independently_trained_{lightgbm,logistic}_artifacts...` in `tests/ml/test_artifact.py`, always-on).
- **Stage 5 no-ML regression** (`tests/pipeline/test_stage5_no_ml_regression.py`, 9 tests): `Stage5Pipeline`
  with `ml_filter=None` reproduces the exact committed Stage 5 decision history, signals and `result_hash` —
  confirmed on the full `tests/pipeline tests/decision tests/regime tests/strategies tests/risk` suite too
  (191 passed, 4 skipped, unchanged from before Stage 6).
- **Full suite:** **1523 passed, 13 skipped** in ≈254 s (skips are all opt-in real-data checks — up from 8
  skips at the Stage 5 commit because the one `arven.ml`-doesn't-exist-yet static check now runs for real).
  All 13 pass together with `ARVEN_REAL_DATA_TESTS=1` (≈123 s): the original 7 (Stage 3/4/5) plus 6 new Stage
  6 real-data checks (both model families: train+verify, determinism, sealed-test refusal, honest
  insufficient-data reporting).

**Real development+validation data results** (`config/ml.yaml` + repo Stage 3-5 configs, git `2298e5a` +
Stage 6 working tree, `touched_test_set=false` on every training run and backtest below):
- **Dataset:** 7 572 raw candidates → 350 rejected by non-portfolio-state risk rules, 26 unresolvable labels
  (horizon past stored data) → **7 196 eligible** (4 790 train rows before the development/validation split,
  2 406 calibration rows in validation). This is far healthier than the pessimistic "a few thousand" planning
  estimate, precisely because D3 evaluates every candidate independently of the single capital path a real
  backtest follows (which only produced 111 trades over the same period).
- **Walk-forward:** 17 chronological expanding-window folds (3-month retrain interval, 12-month minimum
  training window, 96h embargo); logistic regression evaluated 51 fold×hyperparameter combinations (3
  configs), LightGBM evaluated 68 (4 configs); best config selected by mean fold validation log-loss.

  | model | selected hyperparameters | raw val. log-loss | calibrated val. log-loss | raw val. ROC-AUC | calibrated ECE |
  |---|---|---:|---:|---:|---:|
  | logistic | `l2=10.0` | 0.634 | 0.623 | 0.518 | ≈0 |
  | lightgbm | `num_leaves=15, max_depth=4, lr=0.03, min_data_in_leaf=30, feature_fraction=0.7, bagging_fraction=0.7, l1=1.0, l2=1.0` | 0.630 | 0.788 | 0.538 | 0.032 |

  LightGBM's calibrated log-loss is *worse* than its raw log-loss — traced to a single 36-sample calibration
  bin that isotonic regression pinned to exactly `p=0.0` despite a 41.7% actual positive rate in that bin: a
  genuine small-edge-bin isotonic failure mode (confirmed not a `_pava` bug via separate hand tests), reported
  honestly rather than silently discarded or worked around.
- **Backtest A/B** (`arven backtest run --provider pipeline --period development`, real database, same
  period as the Stage 5 baseline above):

  | run | trades | total_return | max_drawdown | win_rate | profit_factor | sharpe |
  |---|---:|---:|---:|---:|---:|---:|
  | Stage 5 only (no ML) | 111 | −20.3% | 20.6% | 33.3% | 0.566 | −1.43 |
  | + logistic MetaFilter (`threshold=0.50`, selected — see the threshold-selection note below) | 44 | **+9.0%** | 2.8% | 54.5% | 1.730 | 0.81 |
  | + LightGBM MetaFilter (`threshold=0.50`, fallback selection — see below) | 0 | 0% | 0% | n/a | n/a | n/a |
  | + shuffled-label logistic control | 0 | 0% | 0% | n/a | n/a | n/a |
  | + random filter, matched to the logistic model's ≈98% empirical reject rate | 77 | −15.1% | 20.2% | 28.6% | 0.579 | −1.13 |

  **Threshold selection (Stage 6 pre-commit audit's BLOCKER 2 fix, implemented 2026-09-29):** the threshold is
  no longer a hardcoded config default — `arven.ml.train.select_threshold` genuinely selects it from
  `config/ml.yaml`'s 5 fixed candidates (`[0.50, 0.55, 0.60, 0.65, 0.70]`) by maximizing precision
  `P(label=1 | p≥threshold)` on validation-period predictions only, restricted to candidates with ≥20
  validation rows passing (never optimizing Sharpe/return/drawdown, never touching the sealed test period,
  never depending on this table's own backtest result — selection happens once, at training time, before any
  backtest using the model is ever run). On real data: logistic's candidates 0.50–0.65 are **exact ties**
  (28 rows, precision 0.679 each — the isotonic calibrator's step function has no achieved value strictly
  between them); the lowest tied candidate (0.50) wins by the documented tie-break rule. Candidate 0.70 has
  a higher precision (0.75) but only 4 rows — correctly excluded by the coverage floor. LightGBM's every
  candidate has 0 validation rows passing (its calibrated scores never reach even 0.50), so it falls back to
  the smallest candidate, honestly flagged `used_fallback=true` in its manifest — its 0-trade backtest result
  is unchanged by this fix, for the same underlying calibration-quality reason documented above.

  The LightGBM filter and the shuffled-label control both reject essentially everything (the poorly-calibrated
  LightGBM scores never reach 0.55; the shuffled-label model, as intended, learned nothing so its scores are
  also below threshold) — 0 trades in both cases, so no trade statistics are meaningful for them. The
  matched-rate random filter (same ≈98% reject rate as the real logistic model, but rejecting *at random*
  rather than by score) still loses money (−15.1%) though less than the unfiltered baseline (fewer trades ⇒
  less cost exposure) — worse than the trained logistic model's result on every metric. This is a **single
  run on one development-period slice**, not a validated edge: it is reported as suggestive, single-run
  evidence that the logistic filter's score carries real information beyond "trade less often," consistent
  with CLAUDE.md's rule against claiming or implying guaranteed profitability. The 111→44 trade drop for the
  real model on a real backtest (vs the model passing 143 of 7 196 dataset rows, ≈98.01% rejection) reflects
  portfolio-state risk vetoes that only apply in the real one-position-at-a-time backtest, not in dataset
  construction (D3) — expected, not a bug.
- **Methodological limitation, found by the Stage 6 pre-commit audit (2026-09-29): the A/B comparison above
  conflates two distinct mechanical effects, and neither Stage 5's risk parameters nor the drawdown halt were
  changed to investigate this.** Instrumenting `Stage5Pipeline.history` directly (not just the trade ledger)
  shows the Stage 5-only baseline's `max_drawdown_halt` circuit breaker (risk rule 7, unmodified) fired for
  **4 358 of its 5 037 risk vetoes (86.5%)**, and **all 111 of its executed trades occurred in 2020** — zero
  trades in 2021, 2022, or the first half of 2023, because the 20%-drawdown halt (which only releases once
  drawdown recovers to ≤15%) was never satisfied again for the rest of the development period. The
  logistic-filtered run's 44 trades are spread across the whole period (2020: 7, 2021: 17, 2022: 10, 2023: 10)
  because it never triggered a sustained drawdown in the first place. **The observed −20.3% vs +8.6%
  difference therefore combines (a) trade-selection effects from the meta-filter and (b) a different
  interaction with the existing portfolio risk circuit breakers — not filtering-quality alone** — and the two
  are not separated in the table above. This is not evidence the logistic filter "wins" or "beats" the
  baseline; it is a description of what mechanically produced the two numbers. Separating these two effects
  (e.g., measuring the same filter's effect starting from a portfolio that never breached the drawdown halt)
  was not attempted here and would need its own controlled comparison, not a parameter change to Stage 5.
- **Model artifacts on disk:** `data/models/logistic-20260929T104905Z-50c98444/`,
  `data/models/lightgbm-20260929T104943Z-50c98444/` (both `arven ml verify`-clean, post-BLOCKER-1/2/3-fix); a
  shuffled-label control model and various earlier exploratory/pre-fix runs are also present, all gitignored
  (`/data/` root-anchored rule).

**Known limitations, all deliberate MVP scope or honestly-reported findings (not bugs)**
- **The A/B table's −20.3%/+8.6% comparison combines trade-selection and circuit-breaker effects** (see the
  methodological-limitation bullet above) — not interpreted as proof either model "wins."
- LightGBM's isotonic calibration underperforms on this dataset size (see above) — the model is trained,
  saved, and verifiable, but its backtest result (0 trades) is not usable as-is; a larger dataset, fewer
  calibration bins, or Platt scaling as a fallback are the natural next steps, not attempted here (no
  hyperparameter/calibration-method search against real-data results, per the "no sealed-test optimization,
  no manufacturing samples" instruction — and this is development+validation, not even the sealed test).
- All A/B and control results are a **single run over one fixed period** — no repeated-seed distribution
  exists for the ML-filtered backtests (unlike Stage 4's baselines, which use many seeded runs). Multiple
  seeds/periods would strengthen the evidence but were not requested for Stage 6.
- The diagnostics described in planning (SHAP summaries, calibration reliability diagrams, per-regime/
  per-strategy `P(success)` breakdowns) are computed and printable via the existing metrics functions and
  LightGBM's native Tree-SHAP, but are not yet formalised as a saved report artifact the way
  `arven.reports.per_regime_breakdown` is for Stage 5 — left for a follow-up, not blocking Stage 6 review.
- The A/B comparison above was produced by four separate `arven ml train`/`arven backtest run` invocations,
  not a single reusable `arven ml` subcommand — also left for a follow-up.

## Stage 7 — walk-forward evaluation (WFO)

**What was built:** `src/arven/wfo.py` (pure functions, no I/O) and `src/arven/wfo_runs.py` (the composition
root, mirroring `runs.py`/`ml_runs.py`) answer the question Stage 6's own limitations section raised: *does
the single-run +8.6% result hold up if measured independently, many times, across time?* WFO re-evaluates
Stage 5 (baseline) and Stage 6 (MetaFilter) **causally, window by window**, over the real 17-window
expanding-window schedule Stage 6 already uses — not a new calendar, not a new model, not a parameter search.
`cli.py` gained two additive subcommands: `arven wfo run` (executes the full schedule, both model families)
and `arven wfo show <run_id>` (prints a stored report). No existing Stage 0–6 file's logic changed.

**Methodology**
- **Schedule:** the exact, unmodified `arven.ml.splits.generate_folds(dev.start, val.end, min_train_months=12,
  retrain_interval_months=3)` Stage 6 already uses — **17 windows**, expanding, over 2020-01-01 → 2025-01-01
  (development ∪ validation only; the sealed test period, 2025-01-01 onward, is never resolved — see
  "Leakage protection" below). `MINIMUM_WINDOWS = 12`: `run_stage7` raises `InsufficientWindowsError` rather
  than silently reporting a distribution from too few windows (not hit on the real schedule: 17 ≥ 12).
- **Causal hyperparameter selection (the central design point):** for evaluation window `N`,
  `select_hyperparameters_causally` calls Stage 6's own `run_walk_forward` restricted to `folds[:N]` — every
  fold *strictly before* `N`, never `folds[N]` itself. Window 0 has no preceding fold, so it falls back to
  `hp_grid[0]` (`run_walk_forward`'s own existing empty-fold behaviour, not a new special case).
- **Causal calibration/threshold selection:** `fit_window_model` fits the model on
  `purge_and_embargo_train_mask(fold N)` **minus** a calibration block, then calibrates (isotonic, D6) and
  selects a threshold (from the same 5 fixed candidates Stage 6 uses) on that calibration block — the union of
  `validation_mask` over the **last `CALIBRATION_LOOKBACK_FOLDS = 4` folds strictly before `N`** (capped, not
  padded, when fewer than 4 preceding folds exist). Training and calibration rows are disjoint by
  construction. Requires `window_index >= 1`; returns `None` for window 0 and for any degenerate split
  (fewer than 2 label classes on either side) — reported honestly via `ml_skip_reason`, never hidden.
- **Why a 4-fold calibration lookback, not 1:** a single preceding fold (~150–250 rows) was found, during this
  stage's own pre-commit audit, to be too small for stable isotonic calibration (PAVA collapses scores toward
  the block's base rate, so almost nothing crosses even the most permissive threshold). Widening to 4 folds is
  a purely statistical fix — same method (isotonic), same threshold candidates, still strictly prior to `N`.
- **Corrected causal design, 2026-10-01 (superseded before any commit):** the first implementation selected
  hyperparameters from **all 17 folds** (window `N`'s own held-out loss contributed to the hyperparameters
  then evaluated on it) and calibrated/thresholded each window **on its own labels**. Both were found and
  fixed during this stage's own development, before being run on real data or committed — see
  `tests/wfo/test_wfo_causality.py` for the regression tests this directly enables (perturbing window `N`'s
  own rows provably does not change its hyperparameters or its fitted model; perturbing the legitimate prior
  calibration source provably *does* change them, proving the invariance tests are meaningful, not vacuous).
- **Fold 10 (the one dev/validation-boundary-crossing window):** confirmed by test to be the *only* one of the
  17 folds whose evaluation block straddles the 2023-07-01 development/validation config boundary. A single
  `SplitGuard`-resolved `AllowedWindow` cannot cross a period boundary by design, and splitting this one window
  into two separately-initialized sub-backtests was considered and rejected (it would require inventing an
  equity-chaining rule the specification never asked for, for one edge case). Fold 10 is therefore **excluded
  from backtesting only** — it stays in the schedule and still contributes to later windows' causal
  hyperparameter-selection history, since that role needs no `SplitGuard` window. Net effect: **17 windows
  generated, 16 backtested, 15 with any ML-vs-baseline comparison** (window 0 is baseline-only).
- **Leakage protection:** `tests/leakage/test_wfo_leakage.py` mirrors the Stage 6 pattern exactly — a static
  source scan proves the literal `BacktestPeriod.TEST` and `allow_sealed` never appear in `wfo.py`/
  `wfo_runs.py`; `resolve_window_for_fold` is proven to return `None` (never resolve `TEST`) even for a fold
  constructed to fall entirely inside the sealed period; a direct `SplitGuard.resolve(TEST)` call still raises
  `SealedAccessError` (belt-and-suspenders, unmodified `SplitGuard`); and the real 17-fold schedule is proven
  to never extend past `validation.end_ms` (the sealed period's start).
- **Reuse, not reimplementation** (`tests/wfo/test_wfo_static_rules.py`): `wfo.py`/`wfo_runs.py` import
  `generate_folds`, `purge_and_embargo_train_mask`, `validation_mask`, `select_threshold`, `fit_isotonic` and
  `run_walk_forward` from their existing Stage 6 modules — none are redefined locally. Neither file imports
  `arven.backtest.execution`/`accounting` or `duckdb` directly. `wfo_runs.py` imports and runs the real
  `Stage5Pipeline`, never a copy. One-directional dependency: no Stage 3–6 package imports `arven.wfo`.
- **Per-window variants:** each backtested window runs (a) the Stage-5-only baseline (no filter), and for each
  model family — logistic and LightGBM — (b) the real causally-fit MetaFilter, (c) a shuffled-label control
  (labels permuted independent of time; same causal fitting procedure, D20's existing technique), and (d) a
  matched-rate `RandomFilter` control seeded to the real filter's own empirical reject rate for that window.
- **Determinism:** schedule generation and per-window model fits are deterministic for fixed inputs (tested);
  LightGBM reuses Stage 6's `deterministic=True, force_row_wise=True, num_threads=1` fixed-seed settings.

**Validation**
- **36 new tests**, all passing: `tests/wfo/` (32: schedule, static rules, causality/perturbation, determinism,
  fit/calibration-lookback, backtest window resolution incl. the real fold-10 check and a regime-hysteresis-
  reset-across-windows check) + `tests/leakage/test_wfo_leakage.py` (4).
- **Full suite: 1565 passed, 13 skipped** (same opt-in real-data skips as before Stage 7; no regressions
  anywhere in Stages 1–6), ≈7 minutes.
- No implementation bug was found during review of the *committed* design (the causal-selection and
  calibration-lookback issues above were found and fixed during this stage's own development, before the real
  run or any commit — see the corrected-design note above).

**Real development+validation data run** (`arven wfo run`, git `e9b7c72` + Stage 7 working tree,
`touched_test_set=false`, seed 42, run `wfo-20261001T075132Z-50c98444`, 2m26s wall time, artifacts in
`data/wfo/wfo-20261001T075132Z-50c98444/`):

| | windows generated | backtested | boundary-excluded | with ML comparison |
|---|---:|---:|---:|---:|
| Schedule | 17 | 16 | 1 (fold 10) | 15 (window 0 is baseline-only) |

*Trades (sum over backtested windows):*

| Variant | Total trades | Mean/window |
|---|---:|---:|
| Baseline (Stage 5 only) | 1281 (16 windows) | 80.1 |
| Logistic MetaFilter | 25 (15 windows) | 1.67 |
| LightGBM MetaFilter | 29 (15 windows) | 1.93 |
| Logistic shuffled-label control | 20 | 1.33 |
| LightGBM shuffled-label control | 0 | 0 |
| Logistic matched-rate random control | 47 | 3.13 |
| LightGBM matched-rate random control | 72 | 4.80 |

Both real filters reject ≈97–98% of candidates per window (consistent with Stage 6's single-run finding, now
shown across 15 independent windows rather than one).

*Performance (mean across backtested windows):*

| Metric | Baseline (n=16) | Logistic ML (n=15) | LightGBM ML (n=15) |
|---|---:|---:|---:|
| total_return | **−11.22%** (range −3.1% to −20.5%, negative in **every** window) | −0.08% (median 0.0%) | −0.10% (median 0.0%) |
| net_pnl (USDT, per-window fresh $10k) | −1121.96 | −7.98 | −9.81 |
| max_drawdown | 13.8% | 0.76% | 0.72% |
| sharpe | −3.54 | +0.49 (n=6 non-null) | −0.54 (n=7 non-null) |
| win_rate | 32.6% | 43.2% (n=7) | 38.7% (n=7) |
| raw ROC-AUC (classification, all 15 windows) | — | 0.42–0.55 | 0.44–0.60 |

**Key finding: Stage 6's single-run "+9.0% / logistic MetaFilter, −20.3% baseline" result does not replicate
under genuine walk-forward evaluation.** Two things are now shown with much stronger evidence than Stage 6's
one continuous backtest could provide:
1. **The unoptimized Stage 5 strategies have no edge, consistently**, not just in one 3.5-year run: the
   baseline loses money in every one of the 16 independently-evaluated, independently-capitalized ~3-month
   windows across 2021–2025. This also rules out the Stage 5/6 single-run result being an artifact of the
   `max_drawdown_halt` circuit breaker getting stuck after 2020 (each WFO window starts with fresh portfolio
   state, so there is no multi-year halt to get stuck in).
2. **Neither MetaFilter shows real discriminative skill**: raw ROC-AUC sits in a tight ~0.42–0.60 band in
   *every* window for *both* model families — indistinguishable from chance. This fully explains both the
   ~98% rejection rate and why the filtered mean return is flat (≈0%) rather than positive.

**Weaknesses and anomalies found (reported honestly, not tuned away)**
- **LightGBM's isotonic calibration is unstable in most windows**, not just the single case Stage 6 flagged:
  calibrated log-loss is *worse* than raw in several windows (e.g. window 7: 0.618→1.742; window 13:
  0.639→2.684) — the same small-sample isotonic-overfit failure mode, now shown recurring across the majority
  of the 15 causal windows rather than appearing once.
- **The logistic shuffled-label control shows a spurious positive mean return** (+0.27%, +$408 total) purely
  from sampling noise: only 4 of 15 windows produced any trades at all under the shuffled model, and one
  window's 11 trades dominate the mean. This is far smaller and far less consistent than the baseline's
  reliably negative signal, and the dedicated perturbation tests already prove the causal mechanism does not
  leak — it is noted here so the number isn't misread as evidence of a leak when reviewing the raw report.
- **Most per-variant distribution statistics (sharpe, profit_factor, win_rate) are built from only 4–7 of the
  15 windows**, because most windows produce zero ML-filtered trades. The report records each metric's own `n`
  (`arven.backtest.metrics.summarize_distribution`); these are not well-powered distributions and should not
  be read as one when cited.
- **Fold 10's exclusion removes one quarter (2023 H2) entirely** from the backtested evidence, baseline
  included — a real, small, and intentional coverage gap (see "fold 10" above).
- Window 0 (2021 Q1) has no ML comparison by construction (no preceding fold to calibrate on) — expected, not
  a defect.

**Known limitations, all deliberate MVP scope or honestly-reported findings (not bugs)**
- This is a single real-data run with one fixed random seed, same as Stage 6's own A/B table — no repeated-
  seed distribution across WFO runs exists (the within-run, across-window distribution above is a different,
  complementary kind of evidence, not a substitute).
- No saved report artifact beyond the one `report.json` per run yet; no dashboard/plot of the per-window
  trajectory — `arven wfo show <run_id>` prints the stored JSON, nothing more polished, left for a follow-up.
- The real run was only executed once (not re-run for a second determinism check on real data, though
  `tests/wfo/test_wfo_determinism.py` and Stage 6's own determinism precedent cover this at the unit level).

## Stage 8 — the paper-signal loop

**What was built:** `src/arven/paper/` (composition root), `src/arven/data/adapters/binance_rest.py` (a new
public-REST client) and `src/arven/data/rest_ingestion.py` (the REST-tail counterpart of Stage 2's bulk
loader), plus a new `BacktestPeriod.FORWARD` in `core/splitguard.py`. The headline design result: **no new
execution or decision logic was needed anywhere** - two things already in place from earlier stages made
this possible. `backtest.clock.Clock` was always a `Protocol`, documented since Stage 4 as "a live loop
implements the same protocol with real time, so backtest and live share one code path". And
`features.builder.build_features` was always documented (Stage 3) as serving "the live loop (one decision
time, on inputs truncated with `MarketInputs.available_until`)". Stage 8 is therefore almost entirely data
plumbing: it REST-updates the database and feeds the *unmodified* `Backtester`/`Stage5Pipeline` a new kind of
period.

**The forward period**
- `BacktestPeriod.FORWARD` resolves `[splits.forward_start, end_ms)`, where `end_ms` is supplied explicitly
  by the caller (there is no fixed upper bound to default to, unlike development/validation/test) - `SplitGuard`
  itself still never reads the wall clock; only `arven.paper` ever computes "now" (one read per tick, via
  `core.timeframes.last_closed_bar_open`, the same point-in-time rule Stage 2/3 already use for bar
  availability). FORWARD is never sealed: there is no future beyond "now" to leak, so nothing here needs
  acknowledgement or logging, and it cannot be used to reach backward into development/validation/test (a
  range crossing into an earlier period is refused, exactly like every other period).
- `docs/architecture.md`'s own "Data periods" table already listed "2026-07 -> onward: Forward paper-trading"
  as a fourth row from the start - Stage 8 implements that row, not a new design decision.

**REST-tail updates** (`data/adapters/binance_rest.py`, `data/rest_ingestion.py`)
- Public Binance USDⓈ-M futures REST endpoints only (`/fapi/v1/klines`, `/fapi/v1/fundingRate`) - no API key,
  no account/order endpoint is ever referenced (enforced by a static test; CLAUDE.md rule 12). `RestIngestor`
  writes into the exact same `ohlcv_1m`/`funding_rates` tables the bulk pipeline uses (one market-data
  history, not a separate "live" copy), continuing from whatever is already stored - it is a *tail* updater,
  not a historical backfill tool (that remains `arven ingest`'s job).
- **Open interest / top-trader / taker long-short ratios are not REST-updated** (Stage 8 scope decision):
  these are the same optional, NaN-tolerant feature group Stage 3 already handles for any other data gap
  (`oi_available`), so they simply go stale for the forward period rather than gaining new live-fetch code.
- **A real performance bug was found and fixed before this was usable**: the first implementation wrote REST
  pages with `con.executemany(...)` directly into `ohlcv_1m`/`funding_rates` (both PRIMARY-KEY-indexed) -
  measured at ~33 seconds per 1000-row page (the exact "executemany into a PK ART index is pathologically
  slow" pitfall this project's own test infrastructure had already hit and documented, see "Operational
  notes" below). Catching up the real ~3-month data gap (see below) at that rate would have taken the better
  part of an hour. Fixed by switching to the same staged bulk-load idiom `ingestion.py` already uses for bulk
  files (CSV -> `read_csv` -> temp table -> one `INSERT OR REPLACE`): **0.045 s for the same 1000-row page**,
  a ~740x speedup, verified by both a direct before/after benchmark and the real catch-up run below.

**The composition root** (`paper/runs.py`, mirrors `runs.py`'s own role for Stage 4)
- `run_paper_tick`: REST-tail klines/funding up to the latest fully-closed, available 1m bar -> resample just
  the trailing window the new bars could affect (not the whole multi-year history) -> resolve the FORWARD
  window -> build that window's feature rows **in memory** with the unmodified `build_features` (Stage 3's
  persisted `data/features/<version>/` cache, and its documented content hash, is never touched - a second,
  parallel live cache would have risked exactly the kind of drift the project's reproducibility story depends
  on not having) -> run the real `Stage5Pipeline` through `runs.execute_run` **unchanged**, the identical
  function `arven backtest run` itself calls -> write a run artifact (`data/paper/<run_id>/run.json` +
  ledgers), indexed in its own `data/paper/runs.jsonl` (kept separate from `data/backtests/runs.jsonl` so
  paper runs are never mixed into the Stage 4 backtest index).
- **The "paper-trade tracker" is not new code**: every tick replays the *entire* forward history from
  `forward_start` through "now" via Stage 4's own `Simulator` (inside `execute_run`), exactly like re-running
  `arven backtest run --period forward` with a later end each time. This is simpler and safer than
  incremental state checkpointing between ticks (no serialization format to get wrong, trivially
  reproducible, and cheap at the scale a few months of 1m bars implies - the real run below took well under
  a minute for the simulation itself).
- **`arven paper run` is idempotent and catch-up capable** (its one design requirement): every invocation
  resolves `[forward_start, now)` fresh and is safe to run from Task Scheduler/cron at any cadence, by hand,
  or after a gap, without missing or double-processing a decision time - there is no per-tick state to
  corrupt, only the growing market database.

**CLI** (`cli.py`, additive only): `arven paper run [--ml-model <id> | --random-filter-rate <p>]`,
`arven paper show <run_id>`, `arven paper status`. No dashboard/Streamlit view (architecture's own A9 answer:
"CLI + persisted signal log first; optional Streamlit dashboard later").

**Module separation, enforced mechanically** (`tests/paper/test_paper_static_rules.py`): no Stage 3-7 package
imports `arven.paper` (one-directional dependency); `paper/runs.py` defines none of
`Backtester`/`Simulator`/`Stage5Pipeline` itself and never imports `arven.backtest.execution`/`accounting`
directly (it drives everything through the real `Backtester` via `runs.execute_run`); `binance_rest.py` and
`rest_ingestion.py` never reference an API-key header, a signature parameter, or any order/account endpoint
path.

**A second real bug, found by the real run itself (not by any test), before the result below was trusted:**
`update_market_data`'s first implementation resampled only a fixed 2-day lookback window after a REST tail,
on the (wrong) assumption that a tick only ever adds about an hour of new 1m data. The real catch-up below
added ~94 days in one call; the fixed lookback silently left all but the last 2 days of that range's derived
5m/15m/1h/4h bars unbuilt. The real forward run's first result, with this bug still present, showed **0
trades over 94.4 days** - surprising against Stage 7's baseline (32-106 trades per similarly-sized window in
every one of 16 historical windows, never 0) and investigated rather than accepted: a direct query found only
49 of the expected 2266 hourly bars existed for the period, and the rest were simply missing, starving every
feature after them of data (`feat_ready` could never reach 1). Fixed by resampling from a small buffer before
whatever 1m data already existed through the new data's end - the *entire* newly-tailed range, regardless of
its size - and covered by a new regression test (`test_update_market_data_resamples_the_whole_new_range_not_
just_a_fixed_lookback`) that seeds a small prior range, REST-tails nine more days (far past the old 2-day
buffer) and asserts every one of those 216 hours gets a complete derived bar. The already-corrupted real
database was repaired with the existing `arven resample` command before re-running.

**Validation**
- **32 new tests**: `tests/unit/test_binance_rest.py` (6, offline fake-opener response parsing/pagination),
  `tests/unit/test_rest_ingestion.py` (7, DB upsert correctness, idempotency, alignment/drift validation,
  continuation from an existing last-stored row), `tests/leakage/test_paper_leakage.py` (6, FORWARD never
  resolves or falls back to TEST, cannot reach backward into earlier periods, the sealed-access log is never
  touched), `tests/paper/test_paper_runs.py` (9, a full synthetic DB -> REST tail -> resample -> forward
  window -> real `Stage5Pipeline` -> written artifact round trip, plus the resample-range regression test
  above) and `tests/paper/test_paper_static_rules.py` (5, import-boundary and no-reimplementation checks).
- `tests/backtest/test_splitguard_and_loading.py` gained 8 tests for the new FORWARD branch (default end
  behaviour, explicit end required, refuses a start before `forward_start`, no upper bound, never sealed,
  needs no log, still rejects non-hour-aligned bounds, `period_bounds` does not resolve it) and lost the one
  pre-Stage-8 test that asserted FORWARD did *not* exist as a period (superseded, not just deleted - the new
  tests assert the actual behaviour instead) - a net +7 in that existing file, +32 in new files, +39 overall.
- **Full suite: 1605 passed, 13 skipped** (same opt-in real-data skips as before Stage 8; no regressions
  anywhere in Stages 1-7), confirmed after both the `executemany` performance fix and the resample-range fix
  above, and after repairing the real database.

**Real run** (`arven paper run`, live Binance REST data, run 2026-10-03; forward_start = 2026-07-01, window
`[2026-07-01, 2026-10-03T06:00)`, 94.4 days, `touched_test_set=false`):

| provider | trades | total_return | max_drawdown | sharpe | win_rate | profit_factor |
|---|---:|---:|---:|---:|---:|---:|
| Stage 5 baseline (no filter) | 89 | −14.9% | 15.8% | −4.89 | 32.6% | 0.53 |
| + logistic MetaFilter (`logistic-20260929T104905Z-50c98444`) | 2 | +0.06% | 1.1% | 0.10 | 50.0% | 1.07 |

This is the **first genuinely forward, out-of-sample evidence** the project has produced (every other result
so far is historical, however carefully split) - and it reproduces, on live data the model has never seen in
any form, exactly the pattern found throughout Stage 5-7: the unoptimized baseline strategies lose money
(consistent with all 16 of Stage 7's historical windows), and the logistic MetaFilter is flat-to-slightly-
positive on very few trades (2, well under the 30-trade statistical-meaningfulness threshold the metrics
module itself warns about) rather than reproducing Stage 6's single-run +8.6% - consistent with Stage 7's
finding that that result does not generalize. This is one 94-day sample, not a validated result either way;
it is reported as a first data point for the forward paper-trading record the thesis will keep accumulating.

**Known limitations, all deliberate MVP scope (not bugs)**
- Open interest and the top-trader/taker long-short ratios are not updated live (see above) - `oi_available`
  correctly reflects this as staleness, exactly as the policy already specifies for any other gap.
- No dashboard/Streamlit view yet - CLI only, per architecture's own stated ordering.
- Every tick replays the full forward history rather than checkpointing incrementally - simple and safe now;
  would need revisiting only if the forward period grows large enough (many years) for a full replay to
  become slow, which is not the case at the scale paper trading runs at.
- `arven paper run` must be invoked by something external (Task Scheduler, cron, or by hand) - Stage 8 does
  not add a persistent background daemon (deliberately, per the D7 design discussion: a laptop that sleeps or
  reboots would otherwise silently stop producing signals without the catch-up design being exercised).

## Full backfill results (per yearly chunk)

Procedure per chunk:
1. `ingest`, split into four quarterly foreground calls, run strictly one at a time with a memory guard.
2. `resample`.
3. Native cross-check on one sample month.
4. `quality`.
5. Report, including a stored-vs-recorded row verification per file.

Memory: ARVEN's peak working set was about 200 MB for ingest steps and 360 MB for the full-period quality run.
Other applications were holding most of the machine's 7.2 GB.

| Chunk | Files ingested | Not avail. | Failed / checksum | Exact dups dropped | Conflicting dups | 1m rows | Funding | OI rows (expected) | OI source gaps | Incomplete derived bars | Cross-check |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2020 | 146 | 244 | 0 / 0 | 35 103 | 0 | 527 040 | 1 098 | 35 103 (from 2020-09-01) | 4 gaps / 33 | 0 | 2020-03 PASS |
| 2021 | 389 | 0 | 0 / 0 | 40 152 | 0 | 525 600 | 1 095 | 104 652 (105 120) | 148 gaps / 468 | 0 | 2021-05: 1 bar differs (source anomaly, below) |
| 2022 | 389 | 0 | 0 / 0 | 0 | 0 | 525 600 | 1 095 | 105 120 (105 120) | 0 | 0 | 2022-11 PASS |
| 2023 | 389 | 0 | 0 / 0 | 0 | 0 | 525 600 | 1 095 | 105 117 (105 120) | 1 gap / 3 | 0 | 2023-03 PASS |
| 2024 | 390 | 0 | 0 / 0 | 0 | 0 | 527 040 | 1 098 | 105 281 (105 408) | 2 gaps / 127 | 0 | 2024-08 PASS (2024-01/02 also) |
| 2025 | 389 | 0 | 0 / 0 | 0 | 0 | 525 600 | 1 095 | 105 117 (105 120) | 1 gap / 3 | 0 | 2025-04 PASS |
| 2026 H1 | 193 | 0 | 0 / 0 | 0 | 0 | 260 640 | 543 | 52 128 (52 128) | 0 | 0 | 2026-06 PASS |

Notes on the table:
- 1m and funding rows equal the expected count in every chunk.
- 2024 counts 390 files because Jan–Feb were already ingested in step 1.
- Every cross-check "PASS" means all bars present on both sides, identical prices and trade counts, and volume within about 1 ULP.

## Final verification (2026-09-28)

- **Tests:** 109 passed.
- **Final quality run** over [2020-01-01, 2026-07-01): 0 errors.
  - 1m: 3 417 120 rows = expected; 0 gaps, 0 duplicates, 0 OHLC/volume violations, 0 unit problems.
  - Derived 5m/15m/1h/4h: all expected counts, 0 incomplete, totals equal to 1m.
  - Funding: 7 119 rows = expected; always 8h; 3 190 rows had 1–47 ms jitter, normalised with the raw value kept.
  - OI: 612 518 rows. The only warnings are the OI gaps below.
  - `source_files.consistency` re-read all 2 285 raw files: 0 inconsistent.
- **Stored vs recorded rows:** 2 321 ingested files, 0 mismatches.
- **Idempotency:**
  - A full-period `ingest` re-run planned 2 529 files: 2 285 skipped, 244 known `not_available`, 0 downloaded.
    Content fingerprints of all tables were identical before and after. The same held for the 2020–2021 re-run before resuming.
- **Clean state:** 0 `.part` files, 0 temp CSVs, 0 WAL files, and no run left in `running`.
  All 26 ingest and 9 crosscheck runs `succeeded`.

**Total rows by table**

| Table | Rows |
|---|---|
| `ohlcv_1m` | 3 417 120 |
| `ohlcv` | 982 422 (5m 683 424, 15m 227 808, 1h 56 952, 4h 14 238; 0 incomplete) |
| `ohlcv_native` | 113 436 (9 sample months × 4 TFs, cross-check only) |
| `funding_rates` | 7 119 |
| `open_interest` | 612 518 |
| `source_files` | 2 565 (2 321 ingested, 244 not_available) |
| `data_gaps` | 157 |

**Storage**

| Item | Size |
|---|---|
| raw zips | 173 MB (klines 145, metrics 28, funding 0.35) |
| Parquet | 202 MB (ohlcv 184.3, OI 26.5, funding 0.1; 43 files) |
| DuckDB | 475 MB (not compacted) |
| `data/` total | 828 MB |

## Gap and anomaly classification (full period)

1. **OI 2020-01-01 → 2020-09-01 (70 272 intervals): expected source boundary.** Binance metrics start on 2020-09-01,
   and the 244 days before are recorded as `not_available`.
2. **OI: 156 real source-data gaps, 634 missing 5-minute snapshots.**
   - By year: 2020 4/33, 2021 148/468, 2023 1/3, 2024 2/127, 2025 1/3.
   - The largest: 2024-02-16 13:35 (125), 2021-02-19 20:05 (63), 2021-06-22 18:30 (52), 2021-06-22 00:25 (37),
     2021-04-27 11:10 (30). Most others are 1–2 snapshots, heavily clustered in 2021.
   - They are source gaps, not pipeline gaps: stored rows equal the raw files exactly, and the 2024-02-16 file was
     inspected and ends at 13:30.
   - All are recorded in `data_gaps` and none are repaired. Stage 3 must turn them into NaN or explicit staleness,
     never interpolation.
3. **Exact duplicate rows in early metrics files: source anomaly, handled deterministically.** 75 255 rows dropped
   in total (all 2020 files and 2021 files up to 2021-05-21), counted per file in `source_files.duplicate_rows_dropped`.
   There were no conflicting duplicates anywhere.
4. **369 zero-volume 1m bars: genuine source bars.** By year: 2020 2, 2021 59, 2022 64, 2023 118, 2024 89, 2025 37,
   2026 0. Reported as info only; relevant for volume features.
5. **Native 5m mismatch at 2021-05-15 00:20 UTC: source inconsistency, preserved, not repaired.**
   - Binance's native 5m bar shows 2 720.216 volume and 24 040 trades.
   - Its 1m bars sum to 2 402.234 and 21 331. The monthly 1m file, the daily 1m file and the REST 1m endpoint all agree
     on this, and REST 5m agrees with the native bar.
   - Our 1m-derived values are kept. Prices are identical.
   - Open item for the later volume-feature decision.
6. **1m OHLCV and funding: no gaps** in the whole period.

## Operational notes

- The first attempt at 2021 ran as a background job and was stopped by Claude Code's memory-pressure protection after
  the chunk had finished. It was verified intact.
- During the resume, a batch of rejected tool calls still started one 2023 Q1 ingest (PID 27556). It was the correct
  next step and a single writer, so it was left to finish, then verified: run `succeeded`, 96 files, and a re-run skipped all 96.
  No concurrent writes happened: a second process was refused by DuckDB's file lock and exited without touching data.
- **The Parquet `export` is the memory-heavy step** (1.56 GB peak working set; global sort of 4.4M bars). It succeeded.
  If memory becomes a problem, per-partition export or a DuckDB `memory_limit` setting could help. Not changed (storage design frozen).

Architecture (`docs/architecture.md`) is approved as the *target* architecture, with these user constraints:
- **Storage:** DuckDB + Parquet only; no PostgreSQL unless a concrete need appears. No Docker.
- **Timeframes:** 1h decision, 4h context, 5m/15m as features.
- **MVP priority:** data, quality checks, features, 3 baseline strategies, rule-based regime, realistic backtesting,
  ML filter, risk engine, LONG/SHORT/NO_TRADE.
- **Deferred:** news, macro, LLM, Telegram, dashboard and paper trading come only after the quantitative core works.
- **Costs:** all configurable.
- **Execution:** none, ever, in the MVP.
- **Priorities:** correctness, reproducibility and leakage prevention over profitability.
- **Process:** explain each stage and the files it changes before implementing; ask before large architecture changes;
  keep the docs current.

## What exists

```
.gitignore                  # .venv, /data/ (root-anchored!), .env, caches, *.duckdb
pyproject.toml              # deps: duckdb, numpy, pydantic, pyyaml, lightgbm; dev: pytest; script `arven`; installed editable (pip -e); pytest path src+tests, marker real_data
config/
  default.yaml              # project, market, data (data_dir, history_start/end, bar + OI availability delays), download (retry policy, crosscheck TFs)
  costs.yaml                # maker/taker fee bps, order types, slippage model params, funding assumptions
  splits.yaml               # dev 2020-01-01→2023-07-01, val →2025-01-01, sealed test →2026-07-01, forward_start 2026-07-01
  features.yaml             # feature version, warm-up factor, every window/period of the v1 features (own hash; not part of AppConfig.config_hash)
  backtest.yaml              # Stage 4: initial equity, leverage, margin/liquidation, lot rules, latency, metric conventions, baseline params (own hash)
  regime.yaml                # Stage 5: trend/vol/stress thresholds, volatility window, dwell bars (own hash)
  strategies.yaml            # Stage 5: decision weights/thresholds + each of the 3 strategies' parameters and regime gates (own hash)
  risk.yaml                  # Stage 5: the 8 risk rules' thresholds/limits (own hash; leverage/mmr read from backtest.yaml, not duplicated)
  ml.yaml                    # Stage 6: labels, dataset, walk-forward (D4), hyperparameter grids (D5), calibration (D6), threshold, determinism (own hash)
src/arven/
  __main__.py, cli.py       # python -m arven {ingest|resample|crosscheck|quality|export|status|features ...|backtest ...}
  core/                     # time.py, timeframes.py, types.py, config.py (Stage 1); series.py (columnar BarSeries/FundingSeries/OpenInterestSeries/MarketInputs
                            #   with available_until + regularized), features_config.py (Stage 3)
                            # signal.py (Signal: the decision->backtest contract), backtest_config.py, splitguard.py (Stage 4)
                            # regime_config.py, strategies_config.py, risk_config.py (Stage 5); ml_config.py (Stage 6)
  features/                 # Stage 3, pure numpy (no I/O, no DB, no later-stage imports; enforced by tests)
    indicators.py             # causal primitives: shift, rolling sum/mean/std/max/min, EMA, Wilder RMA, ATR, RSI, ADX, MACD, Bollinger, Donchian, Parkinson
    asof.py                   # backward as-of join on available_at with staleness limit
    spec.py, registry.py      # FeatureSpec (name, group, source, warmup_bars, required) and the ordered registry + definition hash
    bars.py                   # 5m/15m/1h/4h features, each defined once next to its spec
    futures.py                # funding, open-interest and time features
    builder.py                # build_features(MarketInputs, decision times, config) -> FeatureTable; decision_grid
    checks.py                 # value-range invariants
  data/
    adapters/binance_bulk.py  # Binance bulk layout, SourceFile, plan_files, parse_checksum, has_header
    adapters/binance_rest.py  # Stage 8: public REST klines/fundingRate fetch (no API key, no order endpoints)
    download.py               # Downloader: retries + exponential backoff with jitter, SHA-256 verify, .part + atomic rename
    storage/schema.py         # DuckDB DDL (authoritative schema)
    storage/db.py             # connect(), provenance record helpers, run ids, git commit lookup
    ingestion.py              # Ingestor: plan → download → normalise → upsert; one transaction per file; run log
    rest_ingestion.py         # Stage 8: RestIngestor.tail() - REST-tail klines/funding into the same tables,
                              #   staged bulk INSERT OR REPLACE (never row-by-row; see "Operational notes")
    resample.py               # 1m → 5m/15m/1h/4h (exact DECIMAL sums, is_complete flag)
    crosscheck.py             # derived bars vs Binance native klines (ohlcv_native)
    quality.py                # QualityChecker → quality_results, data_gaps
    export.py                 # Parquet export (atomic swap)
    reader.py                 # read-only DuckDB -> MarketInputs (bars with delay applied, funding, OI)  (Stage 3)
                               # + load_1m_bars/load_funding_window (Stage 4): take an AllowedWindow, assert results lie inside it
    storage/feature_store.py  # feature cache: Parquet via in-memory DuckDB (NaN <-> NULL) + manifest.json  (Stage 3)
                               # + read_window_parquet (Stage 4): reads only rows inside a window
  backtest/                   # Stage 4, pure numpy/stdlib (no I/O, no DB, no wall-clock, no strategy/risk/ML imports; enforced by tests)
    types.py                    # frozen records: Order, OrderEvent, Fill, FundingEvent, Position, Trade, EquityPoint, AccountState
    costs.py, margin.py         # fee/slippage and isolated-margin arithmetic (pure)
    accounting.py               # entry/funding/exit state transitions; the accounting equations (docstring)
    marketdata.py                # validated 1m OHLC + funding-grid arrays; gap detection; fingerprint
    clock.py                     # SimulationClock: the only source of "now"; pre-computed decision grid, no wall-clock
    provider.py                  # FeatureView (clock-bound, raises LookAheadError), PortfolioSnapshot, DecisionContext, SignalProvider protocol
    execution.py                 # 1m event-driven Simulator: funding -> liquidation/stop/gap/time-stop -> fill -> intrabar barriers, per bar
    engine.py                    # Backtester: clock loop, decision -> order -> Simulator; BacktestResult
    baselines.py                 # NoTrade, BuyAndHold, RandomEntry (seeded via SeedSequence(base_seed).spawn)
    metrics.py                   # return/vol/Sharpe/Sortino/drawdown/trade stats/turnover/exposure; summarize_distribution (no ranking)
    report.py                    # canonical CSV serialisation, table/result hashes
  runs.py                     # composition root (Stage 4): load_inputs (window-scoped), execute_run/run_baselines, artifact + index writers, verify_run
  regime/detector.py          # Stage 5: RegimeDetector (stateful, causal, hysteresis), classify_series (batch, for reporting)
  strategies/                 # Stage 5, pure numpy/stdlib (no risk/decision/regime/backtest.margin imports; enforced by tests)
    base.py                     # CandidateSignal, Strategy/RegimeGate protocols
    trend_momentum.py, breakout.py, mean_reversion.py   # the 3 strategies (one file each, independently testable)
  decision/
    engine.py                   # DecisionEngine: regime gate -> weighted vote -> conflict/threshold -> ProposedDecision (no portfolio access)
    pipeline.py                  # Stage5Pipeline: implements SignalProvider, wires regime+strategies+decision+risk; DecisionRecord history
  risk/engine.py               # RiskEngine: the 8 ordered rules, stateful circuit breakers (daily loss/drawdown/cooldown); imports only
                                #   arven.backtest.provider (types) and arven.backtest.margin (one pure function), never engine/execution/accounting
  reports.py                   # Stage 5, deliberately outside arven.decision: per_regime_breakdown (post-hoc only, one-directional dependency)
  ml/                          # Stage 6, imports the real regime/strategies/decision/risk (never a copy) + pure Stage 4 cost functions;
                                #   never the execution/accounting engine or duckdb directly (enforced by tests)
    labels.py                    # triple-barrier resolution on 1m bars, net of costs (reuses arven.backtest.costs, not the engine)
    dataset.py                   # replays the real RegimeDetector/strategies/DecisionEngine/RiskEngine with a fixed flat portfolio (D3)
    splits.py                    # purged, embargoed, expanding-window walk-forward folds; date-agnostic (no SplitGuard/config import)
    model.py                     # numpy logistic regression (Newton's method) + LightGBM adapter (deterministic, model_str-based)
    calibration.py               # isotonic regression (stack-based PAVA)
    metrics.py                   # log-loss, Brier, ROC-AUC, PR-AUC, calibration curve/ECE, precision-coverage (pure numpy)
    train.py                     # feature-column selection (D7), walk-forward hyperparameter selection, final fit + calibration
    artifact.py                  # ModelArtifact, full-provenance manifest, save/load/verify (content-hash pattern)
    filter.py                    # MetaFilter (pass/veto only) and RandomFilter (matched-rate control)
  ml_runs.py                    # Stage 6 composition root (mirrors runs.py): dataset -> walk-forward -> final model -> saved artifact;
                                 #   never resolves BacktestPeriod.TEST (checked by test and by a static string scan)
  wfo.py                         # Stage 7, pure functions, no I/O: causal (prior-folds-only) hyperparameter selection,
                                  #   causal (last-4-prior-folds) calibration/threshold selection, fold-10 boundary resolution;
                                  #   imports Stage 6's generate_folds/purge_and_embargo_train_mask/validation_mask/
                                  #   run_walk_forward/select_threshold/fit_isotonic unmodified, never reimplements them
  wfo_runs.py                    # Stage 7 composition root (mirrors runs.py/ml_runs.py): loads dev+val data, builds the
                                  #   combined dataset once, drives the 17-window schedule, runs baseline/ml/shuffled/random
                                  #   backtests per window via the real Stage5Pipeline/Backtester, writes report.json
  paper/
    runs.py                        # Stage 8 composition root: REST tail -> resample -> resolve BacktestPeriod.FORWARD ->
                                    #   build forward-period features in memory -> runs.execute_run (unmodified) -> write
                                    #   data/paper/<run_id>/ + its own runs.jsonl (kept separate from data/backtests/)
tests/
  conftest.py               # make_config fixture (isolated tmp data_dir)
  synthetic_market.py, leakage_harness.py   # deterministic synthetic bars/funding/OI; generic truncation + perturbation checks
  bt_helpers.py, bt_scenarios.py            # Stage 4: tiny hand-made markets, scripted/random providers, the independent oracle engine,
                                             #   bulk_insert_1m/bulk_insert_funding (COPY-based; see "Operational notes")
  unit/                     # time, timeframes, types, config, binance_bulk, download, resample
                             #   test_binance_rest.py, test_rest_ingestion.py (Stage 8, offline fake REST opener)
  rest_helpers.py           # Stage 8: shared offline fake for Binance's public REST API (no sockets)
  integration/test_ingestion_pipeline.py   # local fake-Binance HTTP server: formats, resets, 404, checksum, rollback, idempotency, quality
  features/                 # indicators, series + as-of, bar features (warm-up, alignment, delay, gaps), funding/OI/time, config/registry/builder, cache
  backtest/                 # config/Signal/MarketData, costs/margin, hand-computed accounting (~30 cases), oracle (300 seeds), invariants,
                             #   baselines, metrics, report/determinism (golden hashes), splitguard+loaders, runs integration, static rules
  leakage/                  # test_no_lookahead (every feature), test_canary, test_static_rules, test_real_data (opt-in),
                             #   test_backtest_leakage.py (Stage 4: FeatureView/clock, prefix invariance, perturbation, cheater vs random)
                             #   test_ml_leakage.py (Stage 6: all 5 canary types - future label, future feature, shuffling,
                             #   full-period normalisation, sealed-test contamination)
                             #   test_wfo_leakage.py (Stage 7: static scan for BacktestPeriod.TEST/allow_sealed, fold-inside-test
                             #   returns None, direct TEST resolve still raises SealedAccessError, real schedule stays in dev+val)
  stage5_helpers.py, pipeline_helpers.py    # Stage 5: exact-value FeatureView builder (real Stage 3 column names); synthetic-market-driven
                                             #   pipeline runner, truncate/garbage helpers for both the feature and 1m-market sides
  regime/, strategies/, decision/, risk/    # hand-computed unit tests per rule/branch, plus each package's own config-validation tests
  pipeline/                 # test_pipeline_wiring, test_stage5_static_rules, test_leakage, test_determinism,
                             #   test_backtest_integration (accounting invariants via the real engine), test_pipeline_real_data (opt-in)
                             #   test_stage5_no_ml_regression.py (Stage 6: Stage5Pipeline with ml_filter=None is byte-identical)
  ml/                       # Stage 6: test_labels (hand-computed triple-barrier), test_splits (purge/embargo property test, 20 seeds),
                             #   test_model, test_calibration (PAVA), test_ml_metrics, test_dataset (regression vs a direct Stage5
                             #   replay), test_artifact (round trip, manifest completeness, hash verification/determinism), test_filter
                             #   (30-seed property test), test_ml_config, test_ml_static_rules (import boundaries), test_ml_real_data (opt-in)
  wfo/                      # Stage 7: test_wfo_schedule (the real 17-window schedule, minimum-windows gate, partial-window
                             #   flagging), test_wfo_causality (direct instrumentation + perturbation-invariance of causal
                             #   hyperparameter/calibration selection), test_wfo_determinism, test_wfo_fit (purge/embargo-minus-
                             #   calibration mask, degenerate-split handling, calibration-lookback capping), test_wfo_backtest
                             #   (window resolution incl. the real fold-10 check, regime-hysteresis reset across windows),
                             #   test_wfo_static_rules (import boundaries, no reimplementation of Stage 6 primitives)
  paper/                    # Stage 8: test_paper_runs (synthetic DB -> REST tail -> resample -> forward window ->
                             #   real Stage5Pipeline -> written artifact; the resample-range regression test),
                             #   test_paper_static_rules (import boundaries, no reimplementation of Backtester/Simulator)
  test_reports.py           # per-regime breakdown (hand-built fixtures)
```
Full suite: **1605 passed, 13 skipped** (`.venv/Scripts/python.exe -m pytest`, about 7 minutes), all passing.
Stage 8 adds 39 net new tests (32 in new files across `tests/unit/`, `tests/leakage/`, `tests/paper/`, plus a
net +7 in the existing `tests/backtest/test_splitguard_and_loading.py` for the new FORWARD period); the 13
skips are unchanged opt-in real-data checks — Stage 8 adds no new opt-in real-data test, since its real-data
run is exercised directly via `arven paper run` (documented in the "Stage 8" section above) rather than as a
pytest-collected check, the same choice Stage 7 made for `arven wfo run`.
Stage 7 added 36 tests (`tests/wfo/`: 32, `tests/leakage/test_wfo_leakage.py`: 4); the 13 skips are unchanged
opt-in real-data checks (7 from Stages 3-5 + 6 from Stage 6 — Stage 7 adds no new opt-in real-data test, since
its real-data run is exercised directly via `arven wfo run`, documented in the "Stage 7" section above, rather
than as a pytest-collected check). All 13 pass together:
`ARVEN_REAL_DATA_TESTS=1 .venv/Scripts/python.exe -m pytest tests/leakage/test_real_data.py
tests/pipeline/test_pipeline_real_data.py tests/ml/test_ml_real_data.py` (about 123 s; add
`ARVEN_REAL_DATA_SAMPLES=200` for the fuller Stage 3 sample count).

### Conventions (all later stages must follow)

**Bars and timestamps**
- Bars cover `[open_time, close_time)` with `close_time = open_time + duration`, aligned to the UTC epoch (valid for timeframes ≤ 4h).
- In DuckDB every time column is a **BIGINT UTC epoch-ms** with an `_ms` suffix.
- A bar is usable from `close_time_ms + data.bar_availability_delay_seconds`. This delay is applied when reading and is not stored.
- `core.timeframes.last_closed_bar_open(t, tf, delay)` returns the latest usable bar at `t`. Use it (or an equivalent as-of join) for every multi-timeframe lookup.

**Funding and OI**
- Funding: `funding_time_ms` is rounded to the whole hour, and the raw value is kept in `raw_funding_time_ms`. Ingestion fails if the drift exceeds 1 s. `available_at_ms = max(raw, normalised)`.
- OI (`open_interest`): `available_at_ms = ts_ms + data.open_interest_availability_delay_seconds`, default 300 s. This is a conservative choice because Binance's publication lag is unknown.
- Missing OI (before 2020-09-01, or days Binance lacks) = **no rows**. Never fill it with zeros or back-filled values. Stage 3 must turn it into NaN.

**Derived bars**
- `ohlcv` rows with `is_complete = false` exist when 1m minutes are missing. Consumers must exclude them or treat them explicitly.

**Config and periods**
- Periods in config are half-open `[start, end)`. A date without a time means 00:00 UTC; a datetime without an offset is rejected.
- Costs are in basis points per side (`cfg.costs.fees.fee_bps(order_type)`).
- `config_hash()` excludes `data_dir` and the `download` section. It is recorded in `ingestion_runs`.

**Ingestion contract** (a violation fails the whole file, rolled back)
- Every row must fall inside the file's period.
- Klines: `close_time` must equal `open + duration − 1ms`, and `open_time` must be aligned.
- Funding: drift must be ≤ 1 s.
- Metrics: the symbol must match.
- Duplicates: exact duplicate rows are dropped and counted in `source_files.duplicate_rows_dropped`. Duplicate keys with different values fail the file.

### How to run

```
.venv/Scripts/python.exe -m arven ingest     --start 2024-01-01 --end 2024-03-01
.venv/Scripts/python.exe -m arven resample   --start 2024-01-01 --end 2024-03-01
.venv/Scripts/python.exe -m arven crosscheck --start 2024-01-01 --end 2024-03-01
.venv/Scripts/python.exe -m arven quality    --start 2024-01-01 --end 2024-03-01
.venv/Scripts/python.exe -m arven export
.venv/Scripts/python.exe -m arven status
.venv/Scripts/python.exe -m arven features build     # full history -> data/features/v1/ (about 7 s, 282 MB peak; DB opened read-only)
.venv/Scripts/python.exe -m arven features check     # cache hash/invariants + development-period statistics only
.venv/Scripts/python.exe -m arven features status
.venv/Scripts/python.exe -m arven backtest run --provider no_trade|buy_and_hold|random_entry|pipeline --period development
.venv/Scripts/python.exe -m arven backtest baselines --period development   # no_trade + buy_and_hold + random_entry, side by side, no ranking
.venv/Scripts/python.exe -m arven backtest verify <run_id>                  # recompute hashes from the written files
.venv/Scripts/python.exe -m arven backtest show <run_id>
.venv/Scripts/python.exe -m arven wfo run                                   # Stage 7: full 17-window causal walk-forward schedule
.venv/Scripts/python.exe -m arven wfo show <run_id>                         # print a stored WFO report.json
```
`--provider pipeline` runs the full Stage 5 regime+strategies+decision+risk pipeline and additionally prints a
per-regime breakdown after the usual metrics.
`backtest run`/`baselines` take `--start`/`--end` (must lie inside `--period`, default the whole period),
`--stress` (multiplies slippage by `costs.slippage.stress_multiplier`), and, for the sealed `test` period only,
`--allow-sealed --reason "..."` (logged permanently before any data is read).
`wfo run` takes no arguments — it always covers the full development+validation range with both model families
and writes to `data/wfo/<run_id>/report.json`; it never touches the sealed test period (see "Stage 7" above).

The data examples above use the 2024-01 → 2024-03 slice. Without `--start`/`--end`, commands use
`data.history_start`/`history_end` (the full 2020-01 → 2026-07 period).

The full backfill is already completed and verified (see "Full backfill results"), so there is nothing left to
backfill. A full-period `ingest` re-run is idempotent: it skips all already-ingested files and downloads nothing
(verified in "Final verification"). Use `--start`/`--end` to limit a run to a sub-range. `crosscheck` has so far only
been run on sample months.

## Historical: Step-1 test-slice results (2024-01-01 → 2024-03-01, run 2026-09-28)

_These are the results of the small Step-1 test slice, kept for reference. They are **not** the final results; for
those see "Full backfill results" and "Final verification" above. The sizes and full-period estimate at the end of this
section are superseded by the actual full-backfill figures._

**Ingestion**
- 64 files: 2 monthly 1m klines, 2 monthly funding, 60 daily metrics.
- 64 downloaded, 64 ingested, 0 failed. About 2.5 minutes, mostly the 60 daily metrics requests.

**Row counts**

| Table | Rows |
|---|---|
| `ohlcv_1m` | 86 400 (= expected) |
| `ohlcv` 5m / 15m / 1h / 4h | 17 280 / 5 760 / 1 440 / 360 (0 incomplete) |
| `funding_rates` | 180 (= expected), 26 rows had 1–4 ms jitter |
| `open_interest` | 17 155 of 17 280 expected |
| `ohlcv_native` | 24 840, from 8 native files |

The missing OI rows are a **real source gap**: Binance's own `BTCUSDT-metrics-2024-02-16.zip` ends at 13:30. There are
125 missing snapshots from 2024-02-16 13:35 to 2024-02-17 00:00, recorded in `data_gaps`.

**Quality**
- 36 of 38 checks PASS. The 2 WARNINGs are the OI gap above.
- 0 errors.
- The source-consistency check re-read all 64 raw files: row counts and value sums match the DB.

**Cross-check against Binance native klines**
- 5m, 15m, 1h and 4h: 100% of bars present on both sides.
- 0 price mismatches, 0 trade-count mismatches.
- Maximum relative volume difference 3e-16 (1 ULP).

**Idempotency**
- A second `ingest` run skipped all 64 files in about 1 s, with no network.
- `ingest --refresh` re-verified the checksums online and re-ingested all 64 files.
- Content fingerprints of all tables were identical before and after both runs.

**Sizes**

| Item | Size |
|---|---|
| raw zips (incl. native cross-check files) | 5.4 MB |
| Parquet | 5.2 MB (ohlcv 4.58 MB, OI 0.80 MB) |
| DuckDB file | 30.4 MB (18.1 MB compacted) |

The DuckDB file is larger than the Parquet export because of primary-key ART indexes, 256 KB block granularity,
and space not reclaimed after the `--refresh` re-ingest.
- **Revised full-period estimate:** DuckDB ≈ 0.4–0.8 GB, Parquet ≈ 0.2 GB, raw ≈ 0.17 GB. This replaces the preflight's
  150–300 MB DuckDB guess.
- Options, not yet decided:
  - compact periodically with `COPY FROM DATABASE`
  - drop PK indexes on bulk tables and rely on the quality duplicate checks instead

## Preflight facts (2026-09-28)

**Connectivity**
- `data.binance.vision` and `fapi.binance.com` are reachable.
- About 10% of TCP connections get reset. The downloader handles this with retries.

**Bulk data**
- Monthly 1m klines and funding files exist for 2020-01 … 2026-08.
- Daily metrics start **2020-09-01**.
- Old kline CSVs have no header row.
- Funding timestamps carry ms jitter.
- Early metrics files contain exact duplicate rows (e.g. 2020-09-01 has every row twice).

**Full-period download:** 78 + 78 + 2 129 files ≈ 171 MB zipped. The daily metrics requests dominate the time: about 1 h
sequentially, based on this run's rate of roughly 2.3 s per file.

## Open issues / decisions for the user

1. ~~Full backfill~~: done. ~~Stage 3 features~~: done and approved. ~~Stage 4 backtester~~: done and approved
   (including the final `liquidation_includes_funding=true` decision, #13 below). ~~Stage 5 pipeline~~: done and
   approved, committed `2298e5a`. ~~Stage 6 ML meta-filter~~: done, approved and committed `e9b7c72`.
   ~~Stage 7 walk-forward evaluation (WFO)~~: done, approved and committed `aa43c1b`. Headline finding:
   **Stage 6's single-run +8.6% result does not replicate**; the baseline loses money in all 16 backtestable
   windows, and neither the logistic nor the LightGBM MetaFilter shows a replicated predictive edge (raw
   ROC-AUC 0.42–0.60 throughout). **Stage 8 paper-signal loop**: implemented, validated (39 net new tests,
   full suite 1605 passed/13 skipped) and run on live Binance data — see "Stage 8" above. First forward
   result: baseline −14.9% over 94.4 days (consistent with every Stage 7 window), logistic MetaFilter flat at
   +0.06% on 2 trades (consistent with Stage 7's non-replication finding, not a new positive result).
2. ~~`forward_start = 2026-07-01` is already in the past~~: **resolved by Stage 8** — it needed no relabelling.
   The gap between `history_end`/`forward_start` (2026-07-01) and the day Stage 8 actually ran (2026-10-03,
   ~94 days) was simply backfilled via the new REST-tail path (the same public endpoints, just incremental)
   before the first forward decision; `forward_start` itself stays exactly as originally configured, and the
   forward period's own definition (`[forward_start, now)`, growing) makes any future gap between runs
   self-healing the same way, by construction.
3. ~~Contiguous splits with no embargo~~: **resolved by Stage 6's purged, embargoed expanding-window
   walk-forward** (`src/arven/ml/splits.py` — 96-hour embargo, purges any training row whose label horizon
   overlaps a validation block; 20-seed exhaustive property test). The underlying Stage 4/5 chronological
   development/validation/test split dates are still contiguous with no embargo between them (unchanged,
   as instructed) — Stage 6 only adds embargo *within* its own walk-forward folds, on top of that.
4. **DuckDB size and compaction.** The DB is 475 MB uncompacted for the full period; the storage design is frozen for now.
5. ~~Stage 3 input decisions~~: resolved by the missing-data policy in "Stage 3 — features" (OI gaps and the pre-2020-09 boundary
   are NaN with staleness, never interpolated; zero-volume ratios are NaN; the 2021-05-15 anomaly is left as is).
6. LLM provider (later). Thesis success criterion.
7. **Top-trader and taker long/short ratios are empty in the source from 2021-12 to 2022-12 (taker: to 2022-05).** `oi_top_ls_log` /
   `oi_taker_ls_log` are therefore NaN for a large part of the development period. **None of the Stage 5 strategies or the
   regime detector read either column** (the regime stress flag uses `oi_chg_1h`, not the ratios), so Stage 5 did not need to
   resolve this. **Stage 6:** both columns are included in LightGBM's full 78-column feature set (they are among the 60
   causal Stage 3 columns) but excluded from logistic regression's 69-column set, since neither is Stage-3 `required=True`
   (D7 — the required/optional split, not an ad hoc Stage 6 selection). No NaN-imputation or dropping was added; a NaN
   value flows into LightGBM's native missing-value handling the same way it would in any other Stage 6 row.
8. ~~The feature cache covers the whole history, including validation and sealed-test rows~~: **enforced by Stage 4's
   `SplitGuard`/`AllowedWindow`** — every backtest data read (1m bars, funding, feature rows) is confined to one configured
   period; a range crossing a period boundary is refused; the sealed test period additionally needs `--allow-sealed` and a
   `--reason`, logged to `data/backtests/sealed_test_log.jsonl` before any data loads. Verified: a development run's reader
   never queries at or after 2023-07-01 (`test_loaders_return_only_rows_inside_the_window_and_log_the_ranges`).
   **Stage 6 extends this, not replaces it:** `arven.ml_runs.train_and_save` resolves only `DEVELOPMENT`/`VALIDATION`
   through the same `SplitGuard`, and never resolves `TEST` (verified by test and by a static scan for the literal
   `BacktestPeriod.TEST` in `ml_runs.py`); a Stage-6-specific sealed-test evaluation log (analogous to
   `sealed_test_log.jsonl`) does not exist yet because no Stage 6 code path reaches the test period at all — left for
   whichever later stage first evaluates a trained model against the sealed test.
9. **Warm-up costs the first 167 days** of the development period for `feat_ready` (`h4_ema_dist_200` needs 1 000 4h bars).
   Lowering `warmup_factor` or dropping the 4h EMA200 is possible via `config/features.yaml`, at the price of a new feature version.
10. ~~Feature cache manifest recorded the pre-commit git hash~~: resolved — rebuilt once after the Stage 3 commit; the content
    hash (`c06b09e7…`) was verified unchanged and the manifest now records `git_commit = 6ac57d47…`.
11. `features build` always rebuilds the full history (about 7 s); there is still no incremental update to Stage 3's
    persisted cache (not added by Stage 8 either — the paper loop builds its own forward-period features fresh in
    memory each tick instead, see "Stage 8" above, deliberately leaving the canonical cache untouched). If bars are
    re-ingested, rebuild: the manifest's `source_fingerprint` identifies the data a cache was built from.
12. **Stage 4 assumptions not verified against Binance's live schedule:** `maintenance_margin_rate` (0.4%, single flat tier,
    no tiered schedule), `qty_step_btc` (0.001), `min_notional_usdt` (100). All are in `config/backtest.yaml`, clearly labelled,
    and easy to correct once checked. They affect margin/liquidation levels and rejection thresholds, not the accounting logic.
13. ~~`liquidation_includes_funding` needs your confirmation~~ — **resolved, final decision (2026-09-29):
    `liquidation_includes_funding = true`.** `liquidation_includes_funding` (config/backtest.yaml) was added beyond
    the approved D11 model. The first real buy-and-hold run (held ~3.5 years) showed the plan's fixed-liquidation-price
    model lets a persistently-paying long drain the wallet **below zero** without ever being liquidated — no real
    exchange allows negative equity on an isolated position. With the confirmed setting, funding is debited from the
    position's isolated margin and the liquidation price moves with it, so equity can no longer go negative. The
    alternative (`false`: fixed liquidation price, funding never triggers it, matching D11 to the letter) remains
    implemented and tested for reference (`test_funding_can_liquidate_when_it_is_debited_from_the_margin`,
    `test_long_hold_through_persistent_positive_funding_is_liquidated_not_negative`) but is not the configured
    behaviour. `config/backtest.yaml` and `docs/architecture.md` §9 reflect this as final, not provisional.
14. ~~Stage 5's ML filter step (architecture §13 step 4)~~ — **resolved: implemented in Stage 6** as
    `arven.ml.filter.MetaFilter`, wired optionally into `Stage5Pipeline` (see "Stage 6" above). The macro-event
    blackout (risk rule 2) **remains genuinely absent, not stubbed** — the risk engine still has no calendar
    check; it is explicitly Stage 9 (renumbered 2026-10-01 — was Stage 8 before the Stage 7 WFO insertion).
15. **Stage 5's regime/strategy/risk parameters are architecture-derived defaults, not fitted or searched**
    (CLAUDE.md: "do not optimize parameters"). The real development-period result (−20.3% over 3.5 years, 111
    trades) is a measurement of the framework, not evidence the three unoptimized strategies have an edge —
    see "Stage 5" above for the per-regime breakdown.
16. **Stage 6's LightGBM calibration underperforms on this dataset (0.630 raw → 0.788 calibrated log-loss)** —
    reported honestly rather than tuned away; see "Stage 6" above for the traced cause (a single small,
    isotonic-overfit calibration bin) and the resulting 0-trade backtest for that model family. A fix (fewer
    bins, Platt fallback, more data) is a candidate for a later stage, not attempted here.
17. **Stage 6's A/B and control backtests are each a single run over one fixed development-period slice**, not
    a seeded distribution the way Stage 4's baselines are. The logistic MetaFilter's +8.6% result is reported
    as single-run, suggestive evidence against its own controls (shuffled-label, matched-rate random filter),
    not a validated edge — consistent with CLAUDE.md's rule against implying guaranteed profitability.

## What does NOT exist yet

- Macro/news ingestion, LLM, dashboard. (The paper-signal loop now exists — Stage 8.)
- `MarketSnapshot` as a separate class (its job is done by `core.series.MarketInputs.available_until` and
  `data.reader`), and the `feature_sets` DuckDB table (replaced by `manifest.json`).
- ~~REST incremental updates (only bulk files are supported so far)~~: implemented in Stage 8
  (`data/adapters/binance_rest.py`, `data/rest_ingestion.py` — klines and funding only, see "Stage 8" above).
- The macro-event blackout (risk rule 2) — explicitly Stage 9 (renumbered 2026-10-01), not implemented, not
  stubbed. (The ML probability gate, decision step 4, now exists — Stage 6.)
- A saved, dedicated Stage 7 WFO report format beyond the one `report.json` per run, and any dashboard/plot of
  per-window results over time — left for a follow-up (see "Stage 7" above).
- A 4th strategy (funding/positioning contrarian, architecture §13 item 4) — out of the explicit Stage 5 scope.
- A formalised, saved Stage 6 diagnostics report (SHAP summary, calibration reliability diagram, per-regime/
  per-strategy `P(success)` breakdown as a report artifact, mirroring `arven.reports.per_regime_breakdown`)
  and a reusable `arven ml` A/B-comparison subcommand — the underlying metrics/SHAP/comparison all run today,
  just via separate ad hoc invocations, not one saved artifact or command.
- A Stage-6-specific sealed-test evaluation log (`arven.ml_runs` never reaches the test period at all yet, so
  there is nothing to log — see open issue #8).
- Git: branch `feat/historical-data`; commits `efb6677` (Stage 1+2), `4be9329` (docs), `6ac57d4` (Stage 3),
  `8009719` (Stage 4), `a6da56b` (docs), `2298e5a` (Stage 5), `e9b7c72` (Stage 6), `aa43c1b` (Stage 7). Stage 8
  (paper-signal loop) is included in this commit.

## Environment

- `.venv`: Python 3.13.12.
  - Added in Stage 1: `pyyaml`, `pytest`.
  - Added in Stage 2: `duckdb 1.5.5`, plus the project itself installed editable (`pip install -e .`).
  - Added in Stage 3: `numpy 2.5.3` (the only new dependency; the install needed several retries because of connection resets).
  - Stage 4 and Stage 5 added no new dependencies.
  - Added in Stage 6: `lightgbm 4.7.0` (pulled in `scipy 1.18.1`, `narwhals 2.26.0`); the install needed retries
    (`--retries 15 --timeout 60`) because of the same connection-reset behaviour seen with `numpy` in Stage 3.
  - Stage 7 added no new dependencies.
  - Stage 8 added no new dependencies: REST calls reuse `Downloader.fetch_bytes` (stdlib `urllib.request`),
    exactly as the bulk downloader already does.
  - Not installed: pandas, pyarrow.
- Pre-existing packages from the user: `openai`, `pydantic`, `httpx2`, `python-dotenv`.

## Decisions log

| Date | Decision | Status |
|---|---|---|
| 2026-09-28 | Point-in-time `available_at` on all data; as-of joins only | approved |
| 2026-09-28 | Store 1m bars as canonical; derive higher TFs; resolve SL/TP intrabar on 1m | approved |
| 2026-09-28 | DuckDB + Parquet for research/backtesting; no PostgreSQL for now | approved |
| 2026-09-28 | Decision TF 1h, context 4h, 5m/15m as features | approved |
| 2026-09-28 | Target historical period 2020-01-01 → 2026-07-01 (`data.history_end`) | approved |
| 2026-09-28 | ML as meta-labelling filter (triple-barrier), LightGBM + logistic baseline, purged walk-forward | approved (target) |
| 2026-09-28 | Rule-based regime detection first; HMM later as comparison | approved (target) |
| 2026-09-28 | Risk engine can only reduce/veto; default action NO_TRADE | approved (target) |
| 2026-09-28 | LLM only for news structuring, explanations, chat — after the quantitative core works | approved (target) |
| 2026-09-28 | Bar convention `[open, open+duration)`; costs in bps per side in config; strict frozen config with hash | implemented (Stage 1) |
| 2026-09-28 | Times stored as BIGINT epoch ms; bar availability applied on read; funding/OI store `available_at_ms` | implemented (Stage 2) |
| 2026-09-28 | DuckDB = source of truth, Parquet = fully rewritten export; raw zips kept immutable under `data/raw/<bucket key>` | implemented (Stage 2) |
| 2026-09-28 | Exact duplicate source rows dropped and counted; conflicting duplicates fail the file | implemented (Stage 2) |
| 2026-09-28 | OI availability delay 300 s (conservative, configurable) | implemented (Stage 2) |
| 2026-09-28 | Only new dependency is `duckdb` (stdlib for HTTP/zip/hash); no pandas/pyarrow yet | implemented (Stage 2) |
| 2026-09-28 | Stage 3 plan: numpy only; 1h bar-close decision grid; 5x configurable warm-up for recursive indicators; Parquet + manifest cache; v1 feature set; regime/strategy features left to Stage 5 | approved |
| 2026-09-28 | Features are pure numpy under `features/`; DB reading (`data/reader.py`) and cache I/O (`data/storage/feature_store.py`) live in `data/`; shared columnar types in `core/series.py` | implemented (Stage 3) |
| 2026-09-28 | Builds always start at the first stored bar (recursive indicators are seeded there); the cache is the canonical form | implemented (Stage 3) |
| 2026-09-28 | Missing data is NaN, never interpolated or carried forward; OI/funding staleness limits in `config/features.yaml` | implemented (Stage 3) |
| 2026-09-28 | Feature config has its own hash; `AppConfig.config_hash()` unchanged | implemented (Stage 3) |
| 2026-09-28 | Stage 4 plan: D1-D27 decision register (initial equity 10 000, leverage 3x, isolated margin, latency 0, run registry as files not a DuckDB table, ...) | approved |
| 2026-09-28 | Backtester implemented: SimulationClock, 1m Simulator, accounting equations, SplitGuard-enforced periods, hash-verified run artifacts, 3 baselines | implemented (Stage 4) |
| 2026-09-29 | `liquidation_includes_funding = true`: funding debited from isolated margin, so equity can never go negative (the D11 fixed-price alternative remains implemented for reference, not used) | approved (final) |
| 2026-09-29 | Stage 5 scope: rule-based regime (trend x vol + stress flag), 3 strategies (trend/momentum, breakout, mean-reversion — the 4th, funding contrarian, excluded), decision engine (regime gate + weighted vote, no ML filter), risk engine (8 ordered rules, no macro blackout) | approved |
| 2026-09-29 | Regime/strategy/risk gating and reporting kept in 4 separate packages (`regime`, `strategies`, `decision`, `risk`) plus `reports.py` outside `decision` for post-hoc analysis; boundaries enforced by static AST tests | implemented (Stage 5) |
| 2026-09-29 | No ML, no parameter optimization, no bypass of the Stage 4 engine — Stage 5 talks to Stage 4 only via `SignalProvider`/`Signal` | implemented (Stage 5) |
| 2026-09-29 | Stage 5 review approved, committed `2298e5a` | approved (final) |
| 2026-09-29 | Stage 6 D1: add LightGBM as the new dependency | approved |
| 2026-09-29 | Stage 6 D2: `MetaFilter` sits after `DecisionEngine.decide()` and before `RiskEngine.apply()`, resolving the architecture's diagram-vs-steps ambiguity in favour of operating on the single consolidated candidate | approved |
| 2026-09-29 | Stage 6 D3: dataset eligibility ignores portfolio-state risk rules only (position-open/daily-loss/drawdown/cooldown); all other risk rules still apply | approved |
| 2026-09-29 | Stage 6 D4: `retrain_interval_months=3`, `embargo_hours=96`, `min_train_months=12` | approved |
| 2026-09-29 | Stage 6 D5: fixed hyperparameter grid, ≤4 configurations per model family, no open-ended search | approved |
| 2026-09-29 | Stage 6 D6: isotonic calibration, fitted per walk-forward fold on held-out rows | approved |
| 2026-09-29 | Stage 6 D7: LightGBM uses all 60 causal Stage 3 columns; logistic regression uses only the 51 `required=True` Stage 3 columns (both + all 18 Stage 5 context columns) | approved |
| 2026-09-29 | Stage 6 implemented: labels, dataset construction (real regime/strategies/decision/risk replay), purged/embargoed walk-forward, numpy logistic regression + LightGBM, isotonic calibration, model artifacts with full provenance, `MetaFilter`/`RandomFilter`, CLI, 1523 tests incl. 5 leakage-canary types and determinism; real development+validation data: 7572/7196 eligible, logistic model +8.6% vs −20.3% baseline with shuffled-label and matched-rate-random controls (single run, not a validated edge) | implemented (Stage 6), approved, committed `e9b7c72` |
| 2026-10-01 | Roadmap renumbered to insert Stage 7 (walk-forward evaluation, WFO) between the ML meta-filter and the paper-signal loop; the former Stage 7 "Paper-signal loop" and everything after it shift to Stage 8-11 unchanged in scope | approved |
| 2026-10-01 | Stage 7 design: reuse Stage 6's `generate_folds` schedule unchanged (no separate Stage 7 calendar); hyperparameter selection for window `N` restricted to `folds[:N]`; calibration/threshold selection restricted to the union of the last 4 folds strictly before `N`; fold 10 (the one dev/validation-boundary-crossing window) excluded from backtesting only, kept in the schedule | approved (implemented) |
| 2026-10-01 | Stage 7's own pre-commit audit found and fixed a causal-leakage bug in its first implementation (hyperparameters/calibration had been selected using all folds, including the window under evaluation) before any real-data run or commit | implemented (Stage 7) |
| 2026-10-01 | Stage 7 real walk-forward result: Stage-5-only baseline negative in all 16 backtestable windows (mean total_return −11.2%); neither logistic nor LightGBM MetaFilter showed a replicated predictive edge (mean total_return ≈0%, raw ROC-AUC 0.42-0.60 in every window) — Stage 6's single-run +8.6% result does not replicate under genuine walk-forward evaluation | implemented (Stage 7), approved (final) |
| 2026-10-01 | Stage 7 review approved, committed `aa43c1b` | approved (final) |
| 2026-10-03 | Stage 8 design: add `BacktestPeriod.FORWARD` (implements `architecture.md`'s own "Data periods" table, not a new decision) rather than inventing a parallel paper-trading data path; the live loop computes "now" itself (one wall-clock read per tick) and is the only new thing that ever does; the real `Backtester`/`Stage5Pipeline` is reused unmodified via `runs.execute_run`, never a bespoke paper-trade tracker | approved (implemented) |
| 2026-10-03 | Stage 8 D2: REST-tail scope is klines + funding only; open interest and the top-trader/taker long-short ratios are not live-updated (optional, NaN-tolerant feature group already) | approved |
| 2026-10-03 | Stage 8 found and fixed two real bugs before trusting its first real run: (1) `con.executemany` into the PK-indexed `ohlcv_1m`/`funding_rates` tables measured ~33s per 1000-row REST page (fixed with the same staged-bulk-load idiom `ingestion.py` already uses, ~740x speedup); (2) a fixed 2-day resample lookback silently left most of a large REST catch-up's derived bars unbuilt, producing a false "0 trades over 94 days" result that was investigated rather than accepted, and fixed with a regression test | implemented (Stage 8) |
| 2026-10-03 | Stage 8 real forward run (live Binance data, forward_start=2026-07-01, 94.4 days): Stage-5-only baseline −14.9% (consistent with every Stage 7 historical window); logistic MetaFilter flat at +0.06% on 2 trades (consistent with Stage 7's non-replication finding) — the project's first genuinely forward, out-of-sample data point | implemented (Stage 8), approved (final) |

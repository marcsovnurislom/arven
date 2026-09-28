# ARVEN — Architecture

Status: **approved as target architecture** (2026-09-28). Not every module is built in the MVP; see `roadmap.md`.
Constraint: DuckDB + Parquet only — no PostgreSQL unless a concrete requirement appears.

---

## 1. Requirements analysis

ARVEN is a *decision-support* system: given the state of the BTC/USDT perpetual market at a
decision time `t`, it emits `LONG`, `SHORT` or `NO_TRADE`, plus the context a human needs
(suggested stop, target, size, confidence, reasons). Its scientific value for the diploma lies in
**how honestly it is evaluated**, not in a headline return number. The architecture is therefore
built around one central idea:

> **Point-in-time correctness.** Every piece of information carries the time at which it became
> known (`available_at`). Every computation for decision time `t` sees only information with
> `available_at <= t`. The same code runs in backtest and live.

### Functional requirements (MVP)
- Ingest historical and live public market data for BTCUSDT perpetual (klines, funding, open interest).
- Store it reproducibly; detect gaps and bad data.
- Compute features on 5m/15m/1h/4h, aligned point-in-time.
- Classify market regime.
- Run several independent rule-based strategies.
- Train/evaluate an ML model under walk-forward validation.
- Combine everything in a decision engine; apply a risk engine with veto power.
- Backtest the full pipeline with fees, slippage and funding.
- Produce live **paper** signals and log them for forward (out-of-sample) evaluation.

### Non-functional requirements
- Reproducible (config + data range + code version ⇒ identical result).
- Testable in isolation per module.
- Simple to run on one laptop (Windows 11, Python 3.13). No servers required.

---

## 2. Ambiguities and proposed defaults

These need your confirmation; the design uses the default until told otherwise.

| # | Question | Proposed default |
|---|---|---|
| A1 | Which exchange? | **Binance USDⓈ-M futures** public data: best free history (`data.binance.vision` bulk files: klines, funding, OI "metrics"). Keep an exchange adapter interface so Bybit/OKX can be added. Check that Binance public endpoints are reachable from your location. |
| A2 | What is the *decision timeframe* / holding horizon? | Decide on **1h bar close**; 4h gives trend/regime context; 15m/5m give short-term momentum/volatility context. Target holding time: hours to ~2 days. 5m-level trading is not the primary goal because fees+slippage dominate at that horizon. |
| A3 | One consolidated signal or one per timeframe? | **One consolidated signal** per decision time, with per-timeframe evidence shown in the explanation. |
| A4 | What does "signal" contain? | Action, reference entry price, stop-loss, take-profit, suggested position size (as % equity risk), confidence, regime, contributing strategies, risk-check results, versions. |
| A5 | How much history? | From 2020-01-01 (futures klines exist from late 2019; OI "metrics" data only from 2020-09-01 (verified in preflight) — features using OI start later or are optional). Target period: 2020-01-01 → 2026-07-01. |
| A6 | Liquidations? | **Deferred.** Free historical liquidation data is not reliably available (Binance only streams live, throttled liquidation snapshots). Can start *recording* the live stream later; cannot be backtested fairly for past years. |
| A7 | News sources? | Deferred to a later stage. Candidates: RSS feeds of crypto media, CryptoPanic-like APIs, official FOMC/CPI calendars. Cost/licensing to be checked. |
| A8 | LLM provider? | Undecided (the `.venv` currently contains the `openai` package). Provider must be swappable behind an interface. Only used in late stages. |
| A9 | User interface? | CLI + persisted signal log first; optional Streamlit dashboard later. |
| A10 | Success criterion for the thesis? | Proposed: pipeline beats *no-trade*, *buy-and-hold (risk-adjusted)* and *random-entry* baselines **after costs** on the sealed test period and on forward paper trading — **or** a well-documented negative result. Both are valid diploma outcomes. |

---

## 3. Technical risks

| Risk | Why it matters | Mitigation |
|---|---|---|
| Look-ahead bias via multi-timeframe joins | Joining a 4h bar to 1h rows by `open_time` leaks up to 3h of future | Join on `available_at = close_time`; leakage tests (truncation test) for every feature |
| Leakage via normalisation / percentiles | Full-sample z-scores, rolling ranks computed with future data | Only trailing windows or fit-on-train transformers |
| Label overlap in ML | Triple-barrier labels span many bars → neighbouring samples share outcome | Purged walk-forward CV with embargo |
| Overfitting via repeated test-set use | Iterating on the test set turns it into training data | Sealed test period, run log, limit on number of evaluations, report number of configurations tried |
| Fees & slippage eat the edge | Taker 0.05% per side (Binance default tier) ⇒ ≥0.1% round trip before slippage | Decide on 1h, not 5m; cost model in every backtest; report gross vs net |
| Funding payments | Holding perps across funding timestamps costs/earns funding every 8h | Funding applied in backtest portfolio accounting |
| Intrabar stop/target ambiguity | Can't know if SL or TP hit first inside one bar | Resolve with 1m data; if still ambiguous assume worst case |
| Data quality | Gaps, exchange outages, duplicate/missing bars | Quality checks at ingestion; gap table; stale data ⇒ NO_TRADE |
| Non-stationarity / regime shifts | A 2021 model may fail in 2024 | Walk-forward retraining, regime conditioning, monitoring |
| LLM knowledge contamination | An LLM trained on 2020–2025 "knows" what happened after a news item → news backtests before the model's cutoff are biased | Only trust LLM-derived features in backtests after the LLM's training cutoff, or on forward data; store the model version |
| Scope creep | Many requested components; limited time | Staged roadmap; strict "not in month 1" list |
| Survivorship / single-asset bias | Results on BTC alone can be luck | Report confidence intervals, multiple periods, and baselines; optional sanity run on ETHUSDT later |

---

## 4. Architecture

The proposed pipeline keeps your concept but makes three changes:

1. **Point-in-time data layer** under everything (every record has `available_at`).
2. **ML sits after the strategies as a meta-filter** (predicts whether a candidate signal is worth taking),
   rather than being a parallel direction predictor. This is more robust and easier to evaluate.
3. **News/Macro feed both the features (context) and the risk engine (event blackout)** — they never
   generate a trade on their own in the MVP.

```
                      ┌─────────────────────────────── offline / batch ─────────────────────────────┐
 Exchange adapters ──▶ Ingestion ──▶ Quality checks ──▶ Storage (DuckDB + Parquet, point-in-time)
 (REST, bulk files,                                           │
  later WebSocket)                                            ▼
 News / macro feeds ─▶ News ingestion ─▶ (LLM structuring) ─▶ Storage
                                                              │
                     ┌────────────────────────────────────────┘
                     ▼                          (same code in backtest and live)
         ┌──────── MarketSnapshot(t) ─────────────────────────────────────────────┐
         │  as-of view of all data with available_at <= t                         │
         └───────┬────────────────────────────────────────────────────────────────┘
                 ▼
         Feature Engineering (per TF, multi-TF aligned, futures metrics, event features)
                 ▼
         Regime Detection ───────────────┐
                 ▼                       │
         Strategy Engine (N independent strategies → candidate signals)
                 ▼                       │
         ML Meta-filter (P(candidate succeeds))
                 ▼                       ▼
         Decision Engine (regime-gated aggregation, thresholds, default NO_TRADE)
                 ▼
         Risk Engine (sizing, stops, limits, event blackout, data-quality gate; veto only)
                 ▼
         Signal (persisted, explained)  ──▶  Backtest portfolio simulator  |  Paper-signal log / dashboard
```

Driving loop:
- **Backtest:** a `Clock` iterates over historical decision times; `MarketSnapshot(t)` is served from storage.
- **Live/paper:** a scheduler wakes at each 1h bar close (+ small delay), refreshes data, builds `MarketSnapshot(now)`,
  runs the identical pipeline, stores the signal. Later, a paper-trade tracker marks signals to market.

---

## 5. Directory structure (proposed)

```
arven/
├── CLAUDE.md
├── README.md
├── pyproject.toml                # added in Stage 1
├── config/
│   ├── default.yaml              # symbol, timeframes, paths
│   ├── costs.yaml                # fees, slippage model params
│   ├── strategies.yaml           # per-strategy parameters
│   ├── risk.yaml                 # risk limits
│   └── splits.yaml               # train/val/test date boundaries (test sealed)
├── docs/
│   ├── architecture.md
│   ├── roadmap.md
│   ├── current_state.md
│   └── experiments/              # one markdown log per experiment (later)
├── src/arven/
│   ├── core/                     # shared types, enums, time utils, config loading, Clock
│   ├── data/
│   │   ├── adapters/             # exchange adapters (binance_bulk, binance_rest, later ws)
│   │   ├── ingestion/            # download/update jobs, idempotent upserts
│   │   ├── storage/              # DuckDB schema, repositories, Parquet I/O
│   │   ├── quality/              # gap/duplicate/outlier checks
│   │   └── snapshot.py           # MarketSnapshot: point-in-time view at time t
│   ├── features/                 # indicators, futures metrics, multi-TF alignment, registry
│   ├── regime/                   # regime classifier(s)
│   ├── strategies/               # base interface + independent strategies
│   ├── ml/                       # labels, datasets, splits (purged WF), models, calibration, eval
│   ├── news/                     # (later) news/macro ingestion, LLM structuring, event features
│   ├── decision/                 # aggregation of strategies + ML + regime → proposed action
│   ├── risk/                     # sizing, stops, limits, veto rules
│   ├── backtest/                 # event loop, execution & cost model, portfolio, metrics, reports
│   ├── signals/                  # Signal model, persistence, explanation payload
│   ├── live/                     # (later) paper-signal scheduler
│   ├── llm/                      # (later) provider interface, prompts, explanation/chat
│   └── cli.py                    # entry points: ingest, backtest, train, signal
├── tests/
│   ├── unit/                     # per-module tests
│   ├── leakage/                  # truncation / point-in-time tests for features, labels, splits
│   ├── integration/              # pipeline end-to-end on small fixture data
│   └── fixtures/                 # small deterministic CSV/Parquet samples
├── scripts/                      # one-off utilities (never imported by src)
├── notebooks/                    # exploration only (optional)
└── data/                         # git-ignored: raw/, parquet/, arven.duckdb, models/, reports/
```

---

## 6. Module responsibilities

| Module | Responsibility | Does **not** |
|---|---|---|
| `core` | Domain types (`Timeframe`, `Action`, `Bar`, `Signal`, …), UTC time helpers, bar open/close arithmetic, config loading, `Clock` | Contain business logic |
| `data.adapters` | Talk to one data source; return normalised records with `event_time` and `available_at` | Store or transform data |
| `data.ingestion` | Idempotent backfill and incremental updates; record ingestion runs | Compute features |
| `data.storage` | Schema, reads/writes, as-of queries | Know about strategies |
| `data.quality` | Detect gaps, duplicates, zero-volume or anomalous bars; write `data_gaps` | Silently "fix" data (only flag; any repair is explicit and logged) |
| `data.snapshot` | Build `MarketSnapshot(t)`: all bars closed at or before `t` on every TF, latest funding/OI known at `t`, events known at `t` | Allow access to anything after `t` |
| `features` | Pure, versioned feature functions; feature registry with declared lookback and source TF | Fit on the full dataset |
| `regime` | Label the market state at `t` (trend/range/volatility) | Decide trades |
| `strategies` | Each strategy maps `features(t)` → `CandidateSignal(direction, strength, stop_hint, rationale)` | Size positions or know about other strategies |
| `ml` | Build labelled datasets, purged walk-forward splits, train/calibrate models, produce `P(success)` for a candidate | Decide trades directly; see test data during development |
| `news` | (Later) ingest news & macro calendar, map to structured events with `available_at`; event features | Produce trades |
| `decision` | Combine regime + candidates + ML probability + event context into a *proposed* action with confidence and reasons | Size or override risk |
| `risk` | Position sizing, stop/target placement, exposure/loss limits, blackout windows, data-quality gate; may reduce or veto, never increase or flip | Generate direction |
| `backtest` | Drive the pipeline over history; simulate fills, fees, slippage, funding; track portfolio; compute metrics; write reports | Contain strategy logic |
| `signals` | Final `Signal` schema, persistence, human-readable explanation payload | Recompute anything |
| `live` | (Later) bar-close scheduler for paper signals; paper-trade tracker | Place real orders |
| `llm` | (Later) provider-agnostic client; news structuring; explanations; chat over stored data | Compute indicators, prices, sizes or decisions |

Key interfaces (sketch, not code yet):

```
MarketSnapshot(t)            -> bars[tf], funding, open_interest, events   (all available_at <= t)
FeatureBuilder.build(snap)   -> FeatureVector(t)            # also batch mode for backtests
RegimeDetector.detect(fv)    -> Regime
Strategy.evaluate(fv, regime)-> CandidateSignal | None
MetaModel.predict(fv, cand)  -> probability in [0,1]
DecisionEngine.decide(...)   -> ProposedDecision(action, confidence, reasons)
RiskEngine.apply(decision, portfolio_state, snap) -> Signal (possibly NO_TRADE with veto reason)
```

Performance note: for backtests, features are computed **vectorised over the whole history** (fast), but
every feature function must be *causal* so that the vectorised result equals the bar-by-bar result. The
truncation leakage test enforces this equivalence.

---

## 7. Database structure

**Storage choice:** **DuckDB** (single embedded file, SQL, excellent for analytical time-series queries,
reads Parquet natively). Raw bulk downloads kept as Parquet/zip in `data/raw/` for reproducibility.
No database server needed. (PostgreSQL/TimescaleDB would be the upgrade path if ever required.)

Conventions: timestamps are UTC; every market/event table has `event_time` semantics plus an explicit
`available_at`; primary keys make ingestion idempotent.

### Market data

> **As implemented in Stage 2** (`src/arven/data/storage/schema.py` is authoritative): all times are BIGINT
> UTC epoch ms with an `_ms` suffix. Bars do not store `available_at`; it is `close_time_ms` + the configured
> bar delay, applied when reading. `funding_rates` and `open_interest` store `available_at_ms` explicitly.
> Also implemented: `ohlcv_native` (Binance's own higher-TF klines, for cross-checking only),
> `source_files` (per-file provenance), `quality_results`, `data_gaps`. The sketch below is the original design.
```
instruments(symbol PK, exchange, contract_type, tick_size, step_size, listed_at)

ohlcv_1m(                          -- canonical base data (also used to resolve intrabar SL/TP)
  symbol, open_time, close_time, available_at,     -- available_at = close_time (+ latency margin)
  open, high, low, close, volume, quote_volume, trade_count,
  taker_buy_volume, taker_buy_quote_volume, source, ingested_at,
  PRIMARY KEY (symbol, open_time))

ohlcv(                             -- derived 5m/15m/1h/4h, resampled deterministically from 1m
  symbol, timeframe, open_time, close_time, available_at, ...same columns..., is_complete,
  PRIMARY KEY (symbol, timeframe, open_time))
  -- validated against exchange-native klines for the same TF

funding_rates(symbol, funding_time, funding_rate, mark_price, available_at, PRIMARY KEY(symbol, funding_time))
open_interest(symbol, ts, sum_open_interest, sum_open_interest_value, available_at,
              top_trader_ls_ratio, taker_ls_vol_ratio, PRIMARY KEY(symbol, ts))   -- from Binance "metrics"
mark_price_klines / premium_index_klines (optional; basis features)
liquidations(symbol, ts, side, price, qty, available_at)   -- LATER, live recording only
```

### Operational / quality
```
ingestion_runs(run_id PK, source, dataset, start, end, rows, status, started_at, finished_at, error)
data_gaps(symbol, dataset, gap_start, gap_end, detected_at, resolution)
```

### News & macro (later stages)
```
news_items(news_id PK, source, url, title, body_hash, published_at, ingested_at, available_at)
news_events(news_id, llm_model, prompt_version, event_type, direction_bias, relevance, severity,
            confidence, processed_at, PRIMARY KEY(news_id, llm_model, prompt_version))
macro_events(event_id PK, name, country, scheduled_time, importance, forecast, previous,
             actual, actual_available_at)
```

### Research & outputs
```
feature_sets(feature_version PK, definition_hash, feature_list, created_at)   -- features cached as Parquet
regime_labels(symbol, ts, detector_version, regime, scores_json)
strategy_signals(run_id, ts, strategy_id, strategy_version, direction, strength, stop_hint, meta_json)
models(model_id PK, model_type, feature_version, label_spec, train_start, train_end,
       params_json, metrics_json, artifact_path, git_commit, created_at)
decisions(run_id, ts, action, confidence, regime, model_id, contributors_json, reasons_json)
signals(signal_id PK, run_id, mode['backtest'|'paper'], ts, symbol, action, entry_ref,
        stop_loss, take_profit, risk_fraction, confidence, veto_reason, explanation_json, versions_json)
backtest_runs(run_id PK, config_hash, config_json, git_commit, data_start, data_end, split,
              started_at, metrics_json, touched_test_set BOOLEAN)
backtest_trades(run_id, trade_id, side, entry_time, entry_price, exit_time, exit_price, qty,
                fees, slippage_cost, funding_cost, pnl, exit_reason)
paper_trades(signal_id, entry_time, entry_price, exit_time, exit_price, pnl, exit_reason)
```

---

## 8. Data flow

1. **Backfill:** download monthly/daily bulk files (1m klines, funding, metrics) → verify checksums → load into
   DuckDB → run quality checks → resample 1m → 5m/15m/1h/4h → cross-check with native klines.
2. **Incremental update:** REST pulls the missing tail since the last stored bar; only *closed* bars are stored
   as complete.
3. **Feature build:** from `ohlcv` + futures tables, compute causal features per TF; align higher TFs to the
   decision grid with an **as-of join on `available_at`**; cache to Parquet keyed by `feature_version`.
4. **Research:** regime labels, strategy candidate signals, ML labels and datasets are produced from cached features.
5. **Decision pipeline:** regime → strategies → ML filter → decision → risk → signal.
6. **Evaluation:** backtester consumes signals + 1m bars for execution simulation → trades, equity curve, metrics, report.
7. **Live/paper (later):** at each 1h close + delay: update data → build snapshot → same pipeline → store signal →
   paper tracker resolves outcomes from subsequent bars.

---

## 9. Backtesting architecture

**Event-driven over decision times, with 1m execution simulation.**

- **Clock:** iterates decision times = 1h bar close times inside the requested period.
- **Snapshot/Features:** precomputed causal features looked up at `t` (equivalent to recomputing at `t`).
- **Pipeline:** identical objects to live (strategy, ML, decision, risk).
- **Execution model:**
  - Signal decided at `t` (bar close) ⇒ market order filled at the **open of the next 1m bar after `t` + latency**
    (configurable, default: first 1m bar after `t`).
  - **Fees:** taker 0.05% / maker 0.02% (configurable, VIP0 defaults); MVP assumes taker for entries and stops.
  - **Slippage:** base bps + volatility-scaled component (e.g. `k × ATR%` of the 1m bar) — configurable, and
    backtests are also run at 2× slippage as a stress test.
  - **Funding:** position notional × funding rate charged/credited at each funding timestamp while open.
  - **Stops/targets:** checked on 1m bars; if both hit in the same 1m bar ⇒ assume stop first (worst case).
  - Optional time stop (max holding bars).
- **Portfolio:** single position in BTCUSDT (long, short or flat), equity accounting in USDT, leverage cap,
  no pyramiding in MVP.
- **Metrics:** net & gross return, CAGR, max drawdown, Sharpe/Sortino (on daily returns), profit factor,
  win rate, average win/loss, exposure time, number of trades, turnover, fees/slippage/funding totals,
  per-regime breakdown, and **comparison to baselines**: no-trade, buy-and-hold, random-entry (same trade
  count & holding time, many seeds → distribution).
- **Robustness:** walk-forward (rolling re-fit), parameter-sensitivity grids (report neighbourhood, not the peak),
  cost stress tests, sub-period analysis (2020–21 bull, 2022 bear, 2023–24 recovery, …).
- **Reproducibility:** each run writes `backtest_runs` row with config hash + git commit; `touched_test_set`
  flag makes every use of the sealed period visible.

### Data periods (proposed, adjustable in `config/splits.yaml`)
| Period | Use |
|---|---|
| 2020-01 → 2023-06 | Development: training + walk-forward validation, strategy design |
| 2023-07 → 2024-12 | Validation / model selection / threshold tuning |
| 2025-01 → 2026-06 | **Sealed test** — evaluated only for final results |
| 2026-07 → onward | Forward paper-trading (true out-of-sample) |

---

## 10. Preventing look-ahead bias and data leakage

1. **`available_at` on every record.** Bars: `close_time` (+ configurable safety margin). Funding: the
   funding timestamp. OI metrics: the period end. News: `max(published_at, ingested_at)` for live; for
   historical news, `published_at` + conservative delay. Macro actuals: release time.
2. **As-of joins only.** Multi-TF alignment and all auxiliary data use `available_at <= t` joins
   (`merge_asof(direction="backward")` / DuckDB `ASOF JOIN`). A 4h bar opened at 08:00 is visible only from 12:00.
3. **Incomplete bars are never features.** The live loop uses only closed bars.
4. **Causal feature functions only:** trailing rolling windows, EWMs, `shift(+k)`. Forbidden in `features/`:
   `shift(-k)`, `center=True`, `bfill`, full-series `mean/std/rank/quantile`. Enforced by code review and a
   simple static grep test.
5. **Truncation test** for every registered feature: `f(data[:t])[t] == f(data)[t]` for many random `t`.
6. **Labels live only in `ml/labels`**, are explicitly forward-looking, and can never be imported by `features/`
   (import-boundary test).
7. **Fit-on-train transformers:** scalers, percentile thresholds, feature selection and hyperparameters are
   fitted inside each training fold only.
8. **Purged walk-forward + embargo:** training samples whose label window overlaps the validation window are
   removed; an embargo gap (≥ label horizon) follows each validation block.
9. **Sealed test set** and logging of every access; number of tried configurations reported in the thesis.
10. **Execution realism:** fill at the next bar, never at the signal bar's close.
11. **LLM contamination rule:** LLM-derived news features are only evaluated historically on periods after the
    LLM's training cutoff, otherwise only in forward paper trading.
12. **Data revisions:** raw downloads are immutable; re-ingestion never overwrites without a logged run.

---

## 11. ML approach for the MVP

**Role:** *meta-labelling* filter. Strategies propose direction; ML estimates the probability that a given
candidate trade reaches its take-profit before its stop-loss (or time limit). Low probability ⇒ skip.
This keeps ML a supporting module, reduces the prediction problem to a well-posed binary task, and allows a
clean A/B comparison "strategies alone" vs "strategies + ML".

- **Labels:** triple-barrier on 1h decision grid, barriers in ATR units matching the risk engine's stop/target,
  vertical barrier = max holding time (e.g. 24–48h), resolved on 1m bars with worst-case tie rule.
  Label = 1 if TP first, 0 otherwise (net of costs ⇒ TP must exceed round-trip cost).
- **Features (~30–60, tabular):** returns over multiple horizons per TF, volatility (ATR%, realized vol,
  Parkinson), trend (EMA distances/slopes, ADX), momentum (RSI, MACD hist), volume (relative volume,
  taker-buy ratio), futures (funding rate level/z-score vs trailing window, OI change, basis if available),
  time (hour-of-day, day-of-week, time-to-next-funding), regime label, candidate's strategy id & strength.
- **Models:** baseline **logistic regression** (with trailing standardisation) and **LightGBM** (shallow trees,
  strong regularisation, early stopping on the inner validation fold). Probability calibration (isotonic/Platt)
  on held-out folds.
- **Validation:** purged, embargoed **expanding-window walk-forward** (e.g. retrain every 3 months).
- **Metrics:** log-loss, Brier, ROC-AUC, calibration curve, precision/coverage at thresholds — and most importantly
  **net backtest improvement** vs strategies-without-ML and vs a shuffled-label control.
- **Explainability:** feature importance / SHAP summary for the thesis.
- **Not in MVP:** LSTMs/Transformers, RL, AutoML, large hyperparameter searches.
- **Optional later:** a direct direction model (3-class) as an additional "strategy" feeding the decision engine.

---

## 12. Market regime detection

Start **rule-based and interpretable**, computed on 4h (context) with 1h confirmation, using only trailing data:

| Axis | Measure | States |
|---|---|---|
| Trend | ADX(14) on 4h, EMA(50) slope, price vs EMA(200) | `TREND_UP`, `TREND_DOWN`, `NO_TREND` |
| Volatility | Realized vol / ATR% percentile vs trailing 1-year window | `LOW`, `NORMAL`, `HIGH` |
| Stress (optional) | Extreme funding z-score, OI shock, gap/outage flags | `STRESS` flag |

Combined regime examples: `TREND_UP/NORMAL`, `RANGE/LOW`, `ANY/HIGH+STRESS`.
- **Hysteresis** (enter at threshold X, exit at Y) and minimum dwell time to avoid flip-flopping.
- Thresholds fixed from the development period only.
- Evaluate: regime persistence, distribution over time, and whether strategy performance differs by regime
  (that is the actual purpose).
- **Later alternative:** Gaussian HMM on returns/volatility, fitted per training fold; compared against rules.

---

## 13. Combining multiple strategies

Initial strategy set (simple, independent, well-known — the point is the framework, not secret alpha):
1. **Trend following** — EMA crossover / Donchian breakout on 1h with 4h trend filter.
2. **Mean reversion** — Bollinger/RSI extremes, only in `RANGE` regimes.
3. **Volatility breakout** — range compression followed by expansion.
4. **Funding/positioning contrarian** — extreme funding + OI build-up (optional, data from 2021).

Combination in the **decision engine** (transparent, testable):
1. **Regime gating:** each strategy declares the regimes where it is allowed (config). Others are ignored.
2. **Weighted vote:** `score = Σ w_s(regime) × direction_s × strength_s` over allowed strategies;
   weights estimated on the development period only (start with equal weights; later, weights ∝ validated
   risk-adjusted performance per regime, shrunk towards equal).
3. **Conflict rule:** strong disagreement (long & short both above threshold) ⇒ `NO_TRADE`.
4. **ML filter:** candidate direction passes only if `P(success) ≥ threshold` (threshold chosen on validation).
5. **Threshold:** `|score| < θ` ⇒ `NO_TRADE`. Default outcome is always `NO_TRADE`.
6. **Output:** proposed action, confidence, list of contributing strategies and reasons.

Stacking (ML over all strategy outputs) is a later option once enough data exists; it is more prone to overfit.

---

## 14. Risk-management architecture

The risk engine is the **last gate**. It receives a proposed decision and the portfolio/market state and
returns a final `Signal`. It can only **reduce size or veto** — never create or flip a direction.

Pipeline of independent, individually testable rules (each returns pass / reduce / veto + reason):
1. **Data-quality gate:** stale data, recent gap, missing funding/OI where required ⇒ veto.
2. **Event blackout:** within a window around high-impact macro events (FOMC, CPI, NFP) ⇒ veto or reduce (later stage).
3. **Volatility guard:** extreme volatility regime ⇒ reduce or veto.
4. **Funding guard:** entering in the direction that pays extreme funding ⇒ reduce/veto.
5. **Stop & target:** stop = k × ATR from entry (from strategy hint, bounded by risk config); target from reward/risk ratio.
6. **Position sizing:** fixed-fractional — risk 0.5–1% of equity per trade: `size = (equity × risk%) / stop_distance`,
   capped by max leverage (e.g. 3×) and max notional.
7. **Portfolio limits:** one position at a time; max daily loss (e.g. −2%) and max drawdown circuit breaker ⇒ stop
   issuing signals until reset; cooldown after N consecutive losses.
8. **Liquidation-distance check:** stop must be well inside estimated liquidation price at the chosen leverage.

All limits in `config/risk.yaml`; every veto is recorded with its reason (valuable for the thesis).

---

## 15. Where LLMs are useful — and where they are not

**Useful (later stages):**
- Turning unstructured news into a **fixed structured schema** (event type, asset relevance, direction bias,
  severity, confidence) — stored with `available_at`, model id and prompt version.
- Deduplicating/clustering news stories.
- Writing **explanations** of a signal from the already computed structured payload (features, regime,
  strategy votes, ML probability, risk checks).
- Natural-language Q&A over stored signals/backtests ("why was there no trade yesterday at 14:00?").
- Assisting with documentation.

**Not used for:**
- Indicator or feature computation, price levels, stops, sizes, PnL, backtest results.
- Making or overriding the final `LONG/SHORT/NO_TRADE` decision.
- Price prediction.
- Any historical evaluation where the LLM may already know the future (knowledge contamination).
- Anything that must be deterministic and reproducible without storing its output.

Rule: LLM outputs are **data**, stored and versioned; they pass through the same point-in-time layer and can only
influence decisions through features or risk blackout flags that are separately validated.

---

## 16. Testing strategy

| Level | What | Examples |
|---|---|---|
| Unit | Pure functions per module | indicator values vs hand-computed / reference values; bar-time arithmetic; resampling; sizing formula; each risk rule |
| Leakage | Point-in-time guarantees | truncation test for every feature; multi-TF as-of alignment; labels not importable from features; purged split has no overlap; `available_at <= t` asserted in snapshot |
| Data quality | Ingestion correctness | no duplicate keys; gap detection on synthetic gaps; resampled 1h == exchange 1h |
| Backtest engine | Accounting correctness | hand-made scenarios: known entry/exit ⇒ exact PnL with fees, slippage, funding; SL/TP same-bar tie ⇒ worst case; no trade ⇒ flat equity |
| Property-based (optional, `hypothesis`) | Invariants | equity never changes without a position except by fees; risk engine never flips direction |
| Integration | Pipeline end-to-end | small fixture dataset (few weeks) → signals → backtest → deterministic metrics snapshot |
| Sanity / statistical | Guard against fooling ourselves | random-signal strategy should lose ≈ costs; shuffled labels ⇒ ML AUC ≈ 0.5; a deliberately leaky feature must be caught by the leakage test |
| Regression | Reproducibility | same config + data ⇒ same metrics (golden files) |

Tests run offline on fixtures; no network in unit tests.

---

## 17. Difficulty estimate

| Component | Difficulty | Notes |
|---|---|---|
| Historical data download & storage | Easy–Medium | Bulk files are straightforward; care with timestamps, gaps, idempotency |
| Technical indicators | Easy | Standard formulas; testing is the work |
| Multi-TF point-in-time alignment | **Medium–Hard** | Most common source of subtle bias |
| Rule-based strategies | Easy | Finding *real* edge is hard; implementing is easy |
| Regime detection (rules) | Easy–Medium | Threshold choice without leakage |
| Backtester with realistic execution | **Hard** | 1m execution, funding, tie rules, accounting correctness |
| ML labels + purged walk-forward | **Hard** | Conceptually subtle; easy to leak |
| ML model training itself | Easy | LightGBM is routine |
| Achieving robust positive net edge | **Very hard / uncertain** | May not exist; honest evaluation is the deliverable |
| Decision engine | Easy–Medium | Mostly config + tests |
| Risk engine | Medium | Many small rules; straightforward to test |
| Live paper-signal loop | Medium | Scheduling, restarts, data freshness, Windows environment |
| News ingestion + LLM structuring | Medium–Hard | Source licensing, timestamp reliability, contamination, cost |
| Liquidation data | Hard (availability) | Deferred |
| Dashboard | Easy–Medium | Streamlit |

# ARVEN — Current state

_Last updated: 2026-09-28 (Stage 3 complete)_

## Phase

**Stage 3 (features) is complete: reviewed and approved by the user on 2026-09-28 as implemented, no redesign required. It is not committed yet.**
- Stage 2 is complete: the full backfill 2020-01-01 → 2026-07-01 is ingested and verified (see below).
- Stage 4 (backtester) has not been started.
- Split dates, `forward_start`, the DuckDB index/storage design and the 300 s OI availability delay are unchanged.
  No Stage 0–2 behaviour changed: the only edits to existing files are `cli.py` (new `features` command),
  `pyproject.toml` (`numpy` dependency, pytest path/marker) and doc updates.
- Stage 1 + Stage 2 are committed on branch `feat/historical-data` (commit `efb6677`, "feat(data): complete historical
  market data pipeline"), followed by a docs commit (`4be9329`). Stage 3 changes are in the working tree.

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
  so the cache is the canonical form; a live loop must compute over the same history (Stage 7).
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
pyproject.toml              # deps: duckdb, numpy, pydantic, pyyaml; dev: pytest; script `arven`; installed editable (pip -e); pytest path src+tests, marker real_data
config/
  default.yaml              # project, market, data (data_dir, history_start/end, bar + OI availability delays), download (retry policy, crosscheck TFs)
  costs.yaml                # maker/taker fee bps, order types, slippage model params, funding assumptions
  splits.yaml               # dev 2020-01-01→2023-07-01, val →2025-01-01, sealed test →2026-07-01, forward_start 2026-07-01
  features.yaml             # feature version, warm-up factor, every window/period of the v1 features (own hash; not part of AppConfig.config_hash)
src/arven/
  __main__.py, cli.py       # python -m arven {ingest|resample|crosscheck|quality|export|status|features build|check|status}
  core/                     # time.py, timeframes.py, types.py, config.py (Stage 1); series.py (columnar BarSeries/FundingSeries/OpenInterestSeries/MarketInputs
                            #   with available_until + regularized), features_config.py (Stage 3)
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
    download.py               # Downloader: retries + exponential backoff with jitter, SHA-256 verify, .part + atomic rename
    storage/schema.py         # DuckDB DDL (authoritative schema)
    storage/db.py             # connect(), provenance record helpers, run ids, git commit lookup
    ingestion.py              # Ingestor: plan → download → normalise → upsert; one transaction per file; run log
    resample.py               # 1m → 5m/15m/1h/4h (exact DECIMAL sums, is_complete flag)
    crosscheck.py             # derived bars vs Binance native klines (ohlcv_native)
    quality.py                # QualityChecker → quality_results, data_gaps
    export.py                 # Parquet export (atomic swap)
    reader.py                 # read-only DuckDB -> MarketInputs (bars with delay applied, funding, OI)  (Stage 3)
    storage/feature_store.py  # feature cache: Parquet via in-memory DuckDB (NaN <-> NULL) + manifest.json  (Stage 3)
tests/
  conftest.py               # make_config fixture (isolated tmp data_dir)
  synthetic_market.py, leakage_harness.py   # deterministic synthetic bars/funding/OI; generic truncation + perturbation checks
  unit/                     # time, timeframes, types, config, binance_bulk, download, resample
  integration/test_ingestion_pipeline.py   # local fake-Binance HTTP server: formats, resets, 404, checksum, rollback, idempotency, quality
  features/                 # indicators, series + as-of, bar features (warm-up, alignment, delay, gaps), funding/OI/time, config/registry/builder, cache
  leakage/                  # test_no_lookahead (every feature), test_canary, test_static_rules, test_real_data (opt-in)
```
403 tests, all passing (`.venv/Scripts/python.exe -m pytest`, about 40 s). Real-data leakage checks are opt-in:
`ARVEN_REAL_DATA_TESTS=1 ARVEN_REAL_DATA_SAMPLES=200 .venv/Scripts/python.exe -m pytest tests/leakage/test_real_data.py`.

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
```

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

1. ~~Full backfill~~: done. ~~Stage 3 features~~: done and approved (final review re-run: 403 tests green, 3 opt-in real-data tests pass).
2. **`forward_start = 2026-07-01` is already in the past** (unchanged as instructed). It needs relabelling before paper trading.
3. **Contiguous splits with no embargo.** To be handled by purging/embargo in Stage 6.
4. **DuckDB size and compaction.** The DB is 475 MB uncompacted for the full period; the storage design is frozen for now.
5. ~~Stage 3 input decisions~~: resolved by the missing-data policy in "Stage 3 — features" (OI gaps and the pre-2020-09 boundary
   are NaN with staleness, never interpolated; zero-volume ratios are NaN; the 2021-05-15 anomaly is left as is).
6. LLM provider (later). Thesis success criterion.
7. **Top-trader and taker long/short ratios are empty in the source from 2021-12 to 2022-12 (taker: to 2022-05).** `oi_top_ls_log` /
   `oi_taker_ls_log` are therefore NaN for a large part of the development period. **Carried to Stage 5 (strategy inputs) and Stage 6
   (ML feature selection, fitted on training folds only):** decide whether to use, drop or restrict them; `oi_chg_*`, `oi_z` and the open-interest level itself are unaffected.
8. **The feature cache covers the whole history, including validation and sealed-test rows** (features are a causal transform with
   no fitting, and only development-period statistics were inspected). **Carried to Stage 4 (backtest data loader must enforce the split
   rules and log every read of the sealed period) and Stage 6 (purged walk-forward, sealed-test evaluation log).**
9. **Warm-up costs the first 167 days** of the development period for `feat_ready` (`h4_ema_dist_200` needs 1 000 4h bars).
   Lowering `warmup_factor` or dropping the 4h EMA200 is possible via `config/features.yaml`, at the price of a new feature version.
10. The manifest records `git_commit` = `4be9329` because Stage 3 code was uncommitted when the cache was built. After the Stage 3 commit,
    rebuild once so the manifest points at the commit that contains the code (the content hash `c06b09e7…` must not change).
11. `features build` always rebuilds the full history (about 7 s); there is no incremental update yet (Stage 7). If bars are
    re-ingested, rebuild: the manifest's `source_fingerprint` identifies the data a cache was built from.

## What does NOT exist yet

- Regime, strategies, ML, decision, risk, backtest, live/paper, news, LLM, dashboard.
- Labels (`ml/labels`), `MarketSnapshot` as a separate class (its job is done by `core.series.MarketInputs.available_until` and
  `data.reader`), and the `feature_sets` DuckDB table (replaced by `manifest.json`).
- REST incremental updates (only bulk files are supported so far).
- `config/strategies.yaml`, `config/risk.yaml`.
- Git: branch `feat/historical-data`; commits `efb6677` (Stage 1 + 2) and `4be9329` (docs). Stage 3 is uncommitted.

## Environment

- `.venv`: Python 3.13.12.
  - Added in Stage 1: `pyyaml`, `pytest`.
  - Added in Stage 2: `duckdb 1.5.5`, plus the project itself installed editable (`pip install -e .`).
  - Added in Stage 3: `numpy 2.5.3` (the only new dependency; the install needed several retries because of connection resets).
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

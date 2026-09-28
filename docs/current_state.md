# ARVEN — Current state

_Last updated: 2026-09-28_

## Phase

**Stage 2 is complete: the full backfill 2020-01-01 → 2026-07-01 is ingested, verified and awaiting user review.**
- Stage 3 has not been started.
- Split dates, `forward_start`, the architecture, the DuckDB index/storage design and the 300 s OI availability delay
  are all unchanged.
- Stage 1 + Stage 2 are committed on branch `feat/historical-data` (commit `efb6677`, "feat(data): complete historical
  market data pipeline"). The working tree was clean at that commit.

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
pyproject.toml              # deps: duckdb, pydantic, pyyaml; dev: pytest; script `arven`; installed editable (pip -e)
config/
  default.yaml              # project, market, data (data_dir, history_start/end, bar + OI availability delays), download (retry policy, crosscheck TFs)
  costs.yaml                # maker/taker fee bps, order types, slippage model params, funding assumptions
  splits.yaml               # dev 2020-01-01→2023-07-01, val →2025-01-01, sealed test →2026-07-01, forward_start 2026-07-01
src/arven/
  __main__.py, cli.py       # python -m arven {ingest|resample|crosscheck|quality|export|status}
  core/                     # time.py, timeframes.py, types.py, config.py (Stage 1)
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
tests/
  conftest.py               # make_config fixture (isolated tmp data_dir)
  unit/                     # time, timeframes, types, config, binance_bulk, download, resample
  integration/test_ingestion_pipeline.py   # local fake-Binance HTTP server: formats, resets, 404, checksum, rollback, idempotency, quality
```
109 tests, all passing (`.venv/Scripts/python.exe -m pytest`, about 30 s).

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
```

The examples above use the 2024-01 → 2024-03 slice. Without `--start`/`--end`, commands use
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

1. ~~Full backfill~~: done (see above). Review pending.
2. **`forward_start = 2026-07-01` is already in the past** (unchanged as instructed). It needs relabelling before paper trading.
3. **Contiguous splits with no embargo.** To be handled by purging/embargo in Stage 6.
4. **DuckDB size and compaction.** The DB is 475 MB uncompacted for the full period; the storage design is frozen for now.
5. **Stage 3 input decisions:**
   - how volume features treat the 2021-05-15 source anomaly and the zero-volume bars
   - how OI features represent the 156 source gaps and the pre-2020-09 boundary (NaN/staleness, never interpolation)
6. LLM provider (later). Thesis success criterion.

## What does NOT exist yet

- Features, regime, strategies, ML, decision, risk, backtest, live/paper, news, LLM, dashboard.
- REST incremental updates (only bulk files are supported so far).
- `config/strategies.yaml`, `config/risk.yaml`.
- Git: current branch `feat/historical-data`; one commit so far, `efb6677` (Stage 1 + Stage 2).

## Environment

- `.venv`: Python 3.13.12.
  - Added in Stage 1: `pyyaml`, `pytest`.
  - Added in Stage 2: `duckdb 1.5.5`, plus the project itself installed editable (`pip install -e .`).
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

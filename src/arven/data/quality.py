"""Data-quality checks over a UTC range ``[start, end)``.

Results are returned and persisted to ``quality_results``; detected gaps are written to ``data_gaps``.
Checks only flag problems — they never modify market data.

Severity: ``error`` = the data violates a contract downstream code relies on;
``warning`` = real-world imperfection that must be visible (gaps, incomplete bars, outliers);
``info`` = descriptive facts (row counts, ranges).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb

from arven.core.config import AppConfig
from arven.core.time import from_ms, to_ms
from arven.core.timeframes import Timeframe
from arven.data.download import sha256_file
from arven.data.ingestion import (
    FUNDING_CSV_TYPES,
    KLINE_CSV_TYPES,
    METRICS_CSV_TYPES,
    first_line,
    read_csv_sql,
    extract_single_csv,
)
from arven.data.adapters.binance_bulk import Dataset, has_header
from arven.data.resample import DERIVED_TIMEFRAMES
from arven.data.storage.db import new_run_id, now_ms

# Earliest/latest plausible epoch-ms values: catches second/microsecond unit mistakes.
_MIN_PLAUSIBLE_MS = to_ms(datetime.fromisoformat("2017-01-01T00:00:00+00:00"))
_MAX_PLAUSIBLE_MS = to_ms(datetime.fromisoformat("2100-01-01T00:00:00+00:00"))
MAX_ABS_FUNDING_RATE = 0.03  # sanity bound per interval; larger values are flagged, not rejected
OI_STEP_MS = 5 * 60_000


@dataclass
class CheckResult:
    check_id: str
    dataset: str
    severity: str
    passed: bool
    observed: str
    details: dict = field(default_factory=dict)


def _iso(ms: int | None) -> str | None:
    return None if ms is None else from_ms(int(ms)).isoformat().replace("+00:00", "Z")


class QualityChecker:
    def __init__(self, cfg: AppConfig, con: duckdb.DuckDBPyConnection) -> None:
        self.cfg = cfg
        self.con = con
        self.symbol = cfg.market.symbol
        self.results: list[CheckResult] = []
        self.gaps: list[tuple] = []
        self.run_id = new_run_id()

    # -- infrastructure --------------------------------------------------------------------------

    def _one(self, sql: str, params: list | dict | None = None) -> tuple:
        return self.con.execute(sql, params or []).fetchone()

    def _add(self, check_id: str, dataset: str, severity: str, passed: bool, observed: str, **details) -> None:
        self.results.append(CheckResult(check_id, dataset, severity, bool(passed), observed, details))

    def run(self, start: datetime, end: datetime) -> list[CheckResult]:
        lo, hi = to_ms(start), to_ms(end)
        self._check_ohlcv_1m(lo, hi)
        for tf in DERIVED_TIMEFRAMES:
            self._check_derived(tf, lo, hi)
        self._check_funding(lo, hi)
        self._check_open_interest(lo, hi)
        self._check_source_consistency(lo, hi)
        self._persist(lo, hi)
        return self.results

    def _persist(self, lo: int, hi: int) -> None:
        checked_at = now_ms()
        self.con.execute("BEGIN TRANSACTION")
        try:
            for r in self.results:
                self.con.execute(
                    "INSERT INTO quality_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [self.run_id, r.check_id, r.dataset, r.severity, r.passed, r.observed,
                     json.dumps(r.details, default=str), checked_at],
                )
            datasets = {g[0] for g in self.gaps} | {"ohlcv_1m", "open_interest"}
            for ds in datasets:
                self.con.execute(
                    "DELETE FROM data_gaps WHERE dataset = ? AND symbol = ? AND gap_start_ms >= ? AND gap_start_ms < ?",
                    [ds, self.symbol, lo, hi],
                )
            for g in self.gaps:
                self.con.execute("INSERT INTO data_gaps VALUES (?, ?, ?, ?, ?, ?, ?)", [*g, self.run_id])
            self.con.execute("COMMIT")
        except BaseException:
            self.con.execute("ROLLBACK")
            raise

    # -- shared checks -----------------------------------------------------------------------------

    def _gaps(self, dataset: str, table: str, ts_col: str, step_ms: int, lo: int, hi: int,
              where: str = "", timeframe: str = "") -> CheckResult:
        rows = self.con.execute(
            f"""
            WITH t AS (
                SELECT {ts_col} AS ts, lag({ts_col}) OVER (ORDER BY {ts_col}) AS prev
                FROM {table} WHERE symbol = ? AND {ts_col} >= ? AND {ts_col} < ? {where}
            )
            SELECT prev + {step_ms}, ts, (ts - prev) // {step_ms} - 1 FROM t WHERE ts - prev > {step_ms}
            ORDER BY ts
            """,
            [self.symbol, lo, hi],
        ).fetchall()
        first, last = self._one(
            f"SELECT min({ts_col}), max({ts_col}) FROM {table} WHERE symbol = ? AND {ts_col} >= ? AND {ts_col} < ? {where}",
            [self.symbol, lo, hi],
        )
        gaps = [tuple(r) for r in rows]
        if first is None:
            gaps = [(lo, hi, (hi - lo) // step_ms)]
        else:
            if first > lo:
                gaps.insert(0, (lo, first, (first - lo) // step_ms))
            if last + step_ms < hi:
                gaps.append((last + step_ms, hi, (hi - last - step_ms) // step_ms))
        for g_start, g_end, missing in gaps:
            self.gaps.append((dataset, self.symbol, timeframe, g_start, g_end, missing))
        missing_total = sum(g[2] for g in gaps)
        self._add(f"{dataset}.gaps", dataset, "warning", not gaps,
                  f"{len(gaps)} gaps, {missing_total} missing intervals",
                  gaps=[{"start": _iso(a), "end": _iso(b), "missing": m} for a, b, m in gaps[:20]])
        return self.results[-1]

    # -- ohlcv_1m ----------------------------------------------------------------------------------

    def _check_ohlcv_1m(self, lo: int, hi: int) -> None:
        ds, step = "ohlcv_1m", Timeframe.M1.ms
        rng = "symbol = $sym AND open_time_ms >= $lo AND open_time_ms < $hi"
        p = {"sym": self.symbol, "lo": lo, "hi": hi}
        n, n_keys, t_min, t_max = self._one(
            f"SELECT count(*), count(DISTINCT open_time_ms), min(open_time_ms), max(open_time_ms) FROM ohlcv_1m WHERE {rng}", p
        )
        expected = (hi - lo) // step
        self._add(f"{ds}.row_count", ds, "warning", n == expected, f"{n} rows, expected {expected}",
                  rows=n, expected=expected)
        self._add(f"{ds}.time_range", ds, "info", t_min == lo and t_max == hi - step,
                  f"min={_iso(t_min)} max={_iso(t_max)}", min=_iso(t_min), max=_iso(t_max))
        self._add(f"{ds}.duplicates", ds, "error", n == n_keys, f"{n - n_keys} duplicate timestamps")

        misaligned, bad_close, implausible = self._one(
            f"""SELECT count(*) FILTER (open_time_ms % {step} <> 0),
                       count(*) FILTER (close_time_ms <> open_time_ms + {step}),
                       count(*) FILTER (open_time_ms < {_MIN_PLAUSIBLE_MS} OR open_time_ms > {_MAX_PLAUSIBLE_MS})
                FROM ohlcv_1m WHERE {rng}""", p)
        self._add(f"{ds}.cadence", ds, "error", misaligned == 0 and bad_close == 0,
                  f"{misaligned} off-grid open times, {bad_close} rows with close != open + 1m",
                  misaligned=misaligned, bad_close=bad_close)
        self._add(f"{ds}.utc_ms_units", ds, "error", implausible == 0,
                  f"{implausible} timestamps outside plausible UTC-ms range")
        self._gaps(ds, "ohlcv_1m", "open_time_ms", step, lo, hi, timeframe="1m")
        self._ohlc_validity(ds, "ohlcv_1m", rng, p)

        neg, taker_gt, zero_vol = self._one(
            f"""SELECT count(*) FILTER (volume < 0 OR quote_volume < 0 OR trade_count < 0
                                         OR taker_buy_volume < 0 OR taker_buy_quote_volume < 0),
                       count(*) FILTER (taker_buy_volume > volume * (1 + 1e-12)
                                         OR taker_buy_quote_volume > quote_volume * (1 + 1e-12)),
                       count(*) FILTER (volume = 0)
                FROM ohlcv_1m WHERE {rng}""", p)
        self._add(f"{ds}.volume_validity", ds, "error", neg == 0 and taker_gt == 0,
                  f"{neg} negative, {taker_gt} taker-buy > total", negative=neg, taker_gt_total=taker_gt)
        self._add(f"{ds}.zero_volume_bars", ds, "info", True, f"{zero_vol} bars with zero volume", count=zero_vol)

    def _ohlc_validity(self, ds: str, table: str, rng: str, p: dict) -> None:
        bad_range, non_positive, non_finite = self._one(
            f"""SELECT count(*) FILTER (low > least(open, close) OR high < greatest(open, close) OR low > high),
                       count(*) FILTER (least(open, high, low, close) <= 0),
                       count(*) FILTER (NOT (isfinite(open) AND isfinite(high) AND isfinite(low) AND isfinite(close)
                                             AND isfinite(volume) AND isfinite(quote_volume)))
                FROM {table} WHERE {rng}""", p)
        self._add(f"{ds}.ohlc_validity", ds, "error", bad_range == 0 and non_positive == 0 and non_finite == 0,
                  f"{bad_range} inconsistent OHLC, {non_positive} non-positive prices, {non_finite} non-finite values",
                  inconsistent=bad_range, non_positive=non_positive, non_finite=non_finite)

    # -- derived timeframes ------------------------------------------------------------------------

    def _check_derived(self, tf: Timeframe, lo: int, hi: int) -> None:
        ds = f"ohlcv_{tf.value}"
        rng = "symbol = $sym AND timeframe = $tf AND open_time_ms >= $lo AND open_time_ms < $hi"
        p = {"sym": self.symbol, "tf": tf.value, "lo": lo, "hi": hi}
        n, incomplete, misaligned, bad_close = self._one(
            f"""SELECT count(*), count(*) FILTER (NOT is_complete), count(*) FILTER (open_time_ms % {tf.ms} <> 0),
                       count(*) FILTER (close_time_ms <> open_time_ms + {tf.ms})
                FROM ohlcv WHERE {rng}""", p)
        expected = (hi - lo) // tf.ms
        self._add(f"{ds}.row_count", ds, "warning", n == expected and incomplete == 0,
                  f"{n} bars ({incomplete} incomplete), expected {expected}", rows=n, incomplete=incomplete)
        self._add(f"{ds}.cadence", ds, "error", misaligned == 0 and bad_close == 0,
                  f"{misaligned} off-grid, {bad_close} bad close times")
        self._ohlc_validity(ds, "ohlcv", rng, p)
        d = self._one(
            f"""SELECT sum(CAST(volume AS DECIMAL(38,8))), sum(trade_count), max(high), min(low), sum(bar_count)
                FROM ohlcv WHERE {rng}""", p)
        m = self._one(
            """SELECT sum(CAST(volume AS DECIMAL(38,8))), sum(trade_count), max(high), min(low), count(*)
               FROM ohlcv_1m WHERE symbol = $sym AND open_time_ms >= $lo AND open_time_ms < $hi""",
            {"sym": self.symbol, "lo": lo, "hi": hi})
        self._add(f"{ds}.consistency_with_1m", ds, "error", tuple(d) == tuple(m),
                  "totals match 1m" if tuple(d) == tuple(m) else "totals differ from 1m",
                  derived=[str(x) for x in d], base_1m=[str(x) for x in m])

    # -- funding -----------------------------------------------------------------------------------

    def _check_funding(self, lo: int, hi: int) -> None:
        ds = "funding_rates"
        rng = "symbol = $sym AND funding_time_ms >= $lo AND funding_time_ms < $hi"
        p = {"sym": self.symbol, "lo": lo, "hi": hi}
        n, n_keys, t_min, t_max, max_drift, jitter_rows, off_grid, bad_avail, intervals = self._one(
            f"""SELECT count(*), count(DISTINCT funding_time_ms), min(funding_time_ms), max(funding_time_ms),
                       max(abs(raw_funding_time_ms - funding_time_ms)),
                       count(*) FILTER (raw_funding_time_ms <> funding_time_ms),
                       count(*) FILTER (funding_time_ms % (funding_interval_hours * 3600000) <> 0),
                       count(*) FILTER (available_at_ms < funding_time_ms OR available_at_ms < raw_funding_time_ms),
                       list(DISTINCT funding_interval_hours)
                FROM funding_rates WHERE {rng}""", p)
        interval_h = intervals[0] if intervals and len(intervals) == 1 else None
        expected = (hi - lo) // (interval_h * 3_600_000) if interval_h else None
        self._add(f"{ds}.row_count", ds, "warning", expected is not None and n == expected,
                  f"{n} rows, expected {expected} (interval hours seen: {intervals})",
                  rows=n, min=_iso(t_min), max=_iso(t_max))
        self._add(f"{ds}.duplicates", ds, "error", n == n_keys, f"{n - n_keys} duplicate funding times")
        self._add(f"{ds}.timestamp_normalisation", ds, "error", (max_drift or 0) <= 1000 and bad_avail == 0,
                  f"{jitter_rows} rows had ms jitter (max {max_drift} ms), normalised; {bad_avail} bad available_at",
                  jitter_rows=jitter_rows, max_drift_ms=max_drift)
        self._add(f"{ds}.grid", ds, "warning", off_grid == 0, f"{off_grid} funding times off the interval grid")
        if interval_h:
            irregular = self._one(
                f"""SELECT count(*) FROM (SELECT funding_time_ms - lag(funding_time_ms) OVER (ORDER BY funding_time_ms) AS d
                                         FROM funding_rates WHERE {rng}) WHERE d IS NOT NULL AND d <> {interval_h * 3600000}""", p)[0]
            self._add(f"{ds}.spacing", ds, "warning", irregular == 0, f"{irregular} irregular spacings")
        non_finite, extreme, r_min, r_max = self._one(
            f"""SELECT count(*) FILTER (NOT isfinite(funding_rate)), count(*) FILTER (abs(funding_rate) > {MAX_ABS_FUNDING_RATE}),
                       min(funding_rate), max(funding_rate) FROM funding_rates WHERE {rng}""", p)
        self._add(f"{ds}.values", ds, "warning", non_finite == 0 and extreme == 0,
                  f"rate range [{r_min}, {r_max}], {extreme} beyond +/-{MAX_ABS_FUNDING_RATE}, {non_finite} non-finite")

    # -- open interest -----------------------------------------------------------------------------

    def _check_open_interest(self, lo: int, hi: int) -> None:
        ds = "open_interest"
        rng = "symbol = $sym AND ts_ms >= $lo AND ts_ms < $hi"
        p = {"sym": self.symbol, "lo": lo, "hi": hi}
        delay = self.cfg.data.open_interest_availability_delay_seconds * 1000
        n, n_keys, t_min, t_max, off_grid, bad_avail, nulls, negative = self._one(
            f"""SELECT count(*), count(DISTINCT ts_ms), min(ts_ms), max(ts_ms),
                       count(*) FILTER (ts_ms % {OI_STEP_MS} <> 0),
                       count(*) FILTER (available_at_ms <> ts_ms + {delay}),
                       count(*) FILTER (sum_open_interest IS NULL OR sum_open_interest_value IS NULL),
                       count(*) FILTER (sum_open_interest < 0 OR sum_open_interest_value < 0)
                FROM open_interest WHERE {rng}""", p)
        expected = (hi - lo) // OI_STEP_MS
        self._add(f"{ds}.row_count", ds, "warning", n == expected, f"{n} rows, expected {expected}",
                  rows=n, min=_iso(t_min), max=_iso(t_max))
        self._add(f"{ds}.duplicates", ds, "error", n == n_keys, f"{n - n_keys} duplicate timestamps")
        self._add(f"{ds}.timestamp_normalisation", ds, "error", off_grid == 0 and bad_avail == 0,
                  f"{off_grid} off the 5m grid, {bad_avail} rows with available_at != ts + {delay} ms")
        self._add(f"{ds}.values", ds, "warning", nulls == 0 and negative == 0,
                  f"{nulls} rows with missing OI, {negative} negative")
        self._gaps(ds, "open_interest", "ts_ms", OI_STEP_MS, lo, hi, timeframe="5m")

    # -- stored data vs raw source files ------------------------------------------------------------

    _SOURCE_SPECS = {
        # dataset -> (table, key column in raw stage, value column in raw, key column in table, value column in table)
        "klines": ("ohlcv_1m", "open_time", "close", "open_time_ms", "close"),
        "fundingRate": ("funding_rates", "calc_time", "last_funding_rate", "raw_funding_time_ms", "funding_rate"),
        "metrics": ("open_interest", "create_time", "sum_open_interest", "ts_ms", "sum_open_interest"),
    }
    _SOURCE_TYPES = {"klines": KLINE_CSV_TYPES, "fundingRate": FUNDING_CSV_TYPES, "metrics": METRICS_CSV_TYPES}

    def _check_source_consistency(self, lo: int, hi: int) -> None:
        files = self.con.execute(
            """SELECT source_key, dataset, row_count, ingested_sha256 FROM source_files
               WHERE status = 'ingested' AND (interval IS NULL OR interval = '1m')
                 AND period_start_ms < ? AND period_end_ms > ? ORDER BY source_key""",
            [hi, lo],
        ).fetchall()
        problems: list[dict] = []
        raw_dir, tmp_dir = self.cfg.data.raw_dir, self.cfg.data.tmp_dir
        for key, dataset, row_count, sha in files:
            table, raw_key, raw_val, key_col, val_col = self._SOURCE_SPECS[dataset]
            local = raw_dir / key
            if not local.exists():
                problems.append({"file": key, "problem": "raw file missing"})
                continue
            if sha256_file(local) != sha:
                problems.append({"file": key, "problem": "raw file hash differs from ingested hash"})
                continue
            csv = extract_single_csv(local, tmp_dir)
            try:
                header = has_header(first_line(csv), Dataset(dataset))
                raw_n, raw_sum = self._one(
                    f"""SELECT count(*), sum(CAST(v AS DECIMAL(38, 12))) FROM (
                            SELECT DISTINCT {raw_key} AS k, {raw_val} AS v, * FROM {read_csv_sql(csv, self._SOURCE_TYPES[dataset], header)})""")
            finally:
                csv.unlink(missing_ok=True)
            db_n, db_sum = self._one(
                f"SELECT count(*), sum(CAST({val_col} AS DECIMAL(38, 12))) FROM {table} WHERE source_key = ?", [key])
            if not (raw_n == db_n == row_count and raw_sum == db_sum):
                problems.append({"file": key, "raw_rows": raw_n, "db_rows": db_n, "recorded_rows": row_count,
                                 "raw_sum": str(raw_sum), "db_sum": str(db_sum)})
        self._add("source_files.consistency", "source_files", "error", not problems and bool(files),
                  f"{len(files)} files re-read, {len(problems)} inconsistent", problems=problems[:20])

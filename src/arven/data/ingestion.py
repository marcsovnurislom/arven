"""Ingestion: plan -> download (verified) -> normalise -> upsert, one transaction per source file.

Idempotency:
- Each source file's rows are replaced as a unit inside one transaction (delete rows attributed to the file,
  insert the file's rows with ``INSERT OR REPLACE``), together with its ``source_files`` status. Primary keys
  make duplicate rows impossible.
- A file already ``ingested`` whose local copy still has the recorded SHA-256 is skipped without network access.
- A file recorded as ``not_available`` (HTTP 404) is not re-requested unless ``refresh=True``.

Normalisation contract (violations fail the file; nothing is partially written):
- Timestamps become epoch milliseconds (values >= 1e14 are treated as microseconds).
- Klines: ``close_time`` must equal ``open_time + duration - 1ms``; stored as ``open_time + duration``.
- Funding: raw time rounded to the whole hour; drift must be <= 1 s; ``available_at = max(raw, normalised)``.
- Metrics: ``create_time`` parsed as UTC; ``available_at = ts + configured delay``; symbol must match.
- Exact duplicate rows are dropped (and counted); duplicate keys with different values fail the file.
- Every row must fall inside the file's period.
"""

from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path

import duckdb

from arven.core.config import AppConfig
from arven.core.sessions import SessionCalendar
from arven.core.time import to_ms
from arven.core.timeframes import Timeframe
from arven.data.adapters.binance_bulk import (
    FUNDING_COLUMNS,
    KLINE_COLUMNS,
    METRICS_COLUMNS,
    Dataset,
    SourceFile,
    has_header,
    parse_checksum,
    plan_files,
)
from arven.data.download import (
    ChecksumMismatchError,
    DownloadError,
    Downloader,
    NotAvailableError,
    RetryPolicy,
    sha256_file,
)
from arven.data.storage.db import (
    SourceFileRecord,
    get_source_file,
    git_commit,
    new_run_id,
    now_ms,
    upsert_source_file,
)

MICROSECOND_THRESHOLD = 100_000_000_000_000  # 1e14: ms timestamps are ~1.7e12, µs ~1.7e15
FUNDING_GRID_MS = 3_600_000
FUNDING_MAX_DRIFT_MS = 1_000

KLINE_CSV_TYPES = {
    "open_time": "BIGINT",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "volume": "DOUBLE",
    "close_time": "BIGINT",
    "quote_volume": "DOUBLE",
    "count": "BIGINT",
    "taker_buy_volume": "DOUBLE",
    "taker_buy_quote_volume": "DOUBLE",
    "ignore": "VARCHAR",
}
FUNDING_CSV_TYPES = {"calc_time": "BIGINT", "funding_interval_hours": "INTEGER", "last_funding_rate": "DOUBLE"}
METRICS_CSV_TYPES = {name: "DOUBLE" for name in METRICS_COLUMNS} | {"create_time": "VARCHAR", "symbol": "VARCHAR"}
assert tuple(KLINE_CSV_TYPES) == KLINE_COLUMNS
assert tuple(FUNDING_CSV_TYPES) == FUNDING_COLUMNS

DEFAULT_DATASETS: tuple[Dataset, ...] = (Dataset.KLINES, Dataset.FUNDING_RATE, Dataset.METRICS)


class IngestError(Exception):
    """A source file violated the normalisation contract."""


@dataclass
class IngestSummary:
    run_id: str
    planned: int = 0
    downloaded: int = 0
    reused_local: int = 0
    ingested: int = 0
    skipped: int = 0
    not_available: int = 0
    failed: int = 0
    rows_written: int = 0
    duplicate_rows_dropped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0


# --- helpers ------------------------------------------------------------------------------------


def _sql_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def read_csv_sql(path: Path, types: dict[str, str], header: bool) -> str:
    columns = "{" + ", ".join(f"'{name}': '{typ}'" for name, typ in types.items()) + "}"
    return (
        f"read_csv('{_sql_path(path)}', header={'true' if header else 'false'}, delim=',', quote='\"', "
        f"columns={columns}, auto_detect=false)"
    )


def _to_ms_sql(column: str) -> str:
    return f"(CASE WHEN {column} >= {MICROSECOND_THRESHOLD} THEN {column} // 1000 ELSE {column} END)"


def extract_single_csv(zip_path: Path, tmp_dir: Path) -> Path:
    """Extract the single CSV member of a Binance zip into ``tmp_dir``."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
            raise IngestError(f"{zip_path.name}: expected exactly one CSV member, found {[m.filename for m in members]}")
        out = tmp_dir / f"{uuid.uuid4().hex}-{Path(members[0].filename).name}"
        with zf.open(members[0]) as src, out.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    return out


def first_line(path: Path) -> str:
    with path.open("r", encoding="utf-8") as fh:
        return fh.readline()


def _scalar(con: duckdb.DuckDBPyConnection, sql: str, params: Sequence[object] = ()) -> object:
    row = con.execute(sql, list(params)).fetchone()
    return row[0] if row else None


def _dedupe_stage(con: duckdb.DuckDBPyConnection, key_columns: str, source: str) -> int:
    """Drop exact duplicate rows from ``_stage``; fail on conflicting duplicates. Returns rows dropped."""
    total = _scalar(con, "SELECT count(*) FROM _stage")
    con.execute("CREATE OR REPLACE TEMP TABLE _stage AS SELECT DISTINCT * FROM _stage")
    distinct_rows = _scalar(con, "SELECT count(*) FROM _stage")
    distinct_keys = _scalar(con, f"SELECT count(*) FROM (SELECT DISTINCT {key_columns} FROM _stage)")
    if distinct_keys != distinct_rows:
        raise IngestError(f"{source}: {distinct_rows - distinct_keys} conflicting rows share a key with different values")
    return int(total) - int(distinct_rows)


def _check_period(con: duckdb.DuckDBPyConnection, ts_column: str, sf: SourceFile) -> None:
    lo, hi, n = con.execute(f"SELECT min({ts_column}), max({ts_column}), count(*) FROM _stage").fetchone()
    if n == 0:
        raise IngestError(f"{sf.filename}: file contains no rows")
    start, end = to_ms(sf.period_start), to_ms(sf.period_end)
    if lo < start or hi >= end:
        raise IngestError(f"{sf.filename}: rows outside file period [{start}, {end}): min={lo} max={hi}")


def drop_closed_minutes(
    con: duckdb.DuckDBPyConnection, calendar: SessionCalendar, lo_ms: int, hi_ms: int, table: str = "_stage",
    ts_column: str = "open_time_ms",
) -> int:
    """Delete the rows of ``table`` whose minute lies in a closed window of ``calendar`` (session markets store only
    tradable minutes - see :mod:`arven.core.sessions`). Returns the number of rows deleted (0 for a 24x7 market)."""
    windows = calendar.closed_windows(lo_ms, hi_ms)
    if not windows:
        return 0
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _closed AS SELECT unnest(?::BIGINT[]) AS s, unnest(?::BIGINT[]) AS e",
        [[s for s, _ in windows], [e for _, e in windows]],
    )
    before = _scalar(con, f"SELECT count(*) FROM {table}")
    con.execute(
        f"DELETE FROM {table} WHERE EXISTS (SELECT 1 FROM _closed c WHERE {table}.{ts_column} >= c.s AND {table}.{ts_column} < c.e)"
    )
    after = _scalar(con, f"SELECT count(*) FROM {table}")
    con.execute("DROP TABLE _closed")
    return int(before) - int(after)


# --- per-dataset loaders (called inside a transaction) ------------------------------------------


def _load_klines(
    con, csv: Path, sf: SourceFile, symbol: str, ingested_at: int, calendar: SessionCalendar | None = None
) -> tuple[int, int]:
    assert sf.interval is not None
    tf_ms = sf.interval.ms
    header = has_header(first_line(csv), Dataset.KLINES)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _stage AS
        SELECT {_to_ms_sql('open_time')} AS open_time_ms,
               {_to_ms_sql('close_time')} AS raw_close_time_ms,
               open, high, low, close, volume, quote_volume, "count" AS trade_count,
               taker_buy_volume, taker_buy_quote_volume
        FROM {read_csv_sql(csv, KLINE_CSV_TYPES, header)}
        """
    )
    dropped = _dedupe_stage(con, "open_time_ms", sf.filename)
    _check_period(con, "open_time_ms", sf)
    misaligned = _scalar(con, f"SELECT count(*) FROM _stage WHERE open_time_ms % {tf_ms} <> 0")
    if misaligned:
        raise IngestError(f"{sf.filename}: {misaligned} open_time values not aligned to {sf.interval}")
    bad_close = _scalar(con, f"SELECT count(*) FROM _stage WHERE raw_close_time_ms <> open_time_ms + {tf_ms} - 1")
    if bad_close:
        raise IngestError(f"{sf.filename}: {bad_close} rows with close_time != open_time + duration - 1ms")
    if sf.interval is Timeframe.M1 and calendar is not None:
        # session market: keep only tradable minutes (native higher-TF klines are kept whole for the cross-check)
        drop_closed_minutes(con, calendar, to_ms(sf.period_start), to_ms(sf.period_end))

    columns = (
        "open, high, low, close, volume, quote_volume, trade_count, taker_buy_volume, taker_buy_quote_volume"
    )
    if sf.interval is Timeframe.M1:
        con.execute("DELETE FROM ohlcv_1m WHERE source_key = ?", [sf.key])
        con.execute(
            f"""
            INSERT OR REPLACE INTO ohlcv_1m
            SELECT ?, open_time_ms, open_time_ms + {tf_ms}, {columns}, ?, ? FROM _stage
            """,
            [symbol, sf.key, ingested_at],
        )
    else:
        con.execute("DELETE FROM ohlcv_native WHERE source_key = ?", [sf.key])
        con.execute(
            f"""
            INSERT OR REPLACE INTO ohlcv_native
            SELECT ?, ?, open_time_ms, open_time_ms + {tf_ms}, {columns}, ?, ? FROM _stage
            """,
            [symbol, sf.interval.value, sf.key, ingested_at],
        )
    return int(_scalar(con, "SELECT count(*) FROM _stage")), dropped


def _load_funding(con, csv: Path, sf: SourceFile, symbol: str, ingested_at: int) -> tuple[int, int]:
    header = has_header(first_line(csv), Dataset.FUNDING_RATE)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _stage AS
        SELECT raw_ms AS raw_funding_time_ms,
               (raw_ms + {FUNDING_GRID_MS // 2}) // {FUNDING_GRID_MS} * {FUNDING_GRID_MS} AS funding_time_ms,
               last_funding_rate AS funding_rate,
               funding_interval_hours
        FROM (SELECT {_to_ms_sql('calc_time')} AS raw_ms, * FROM {read_csv_sql(csv, FUNDING_CSV_TYPES, header)})
        """
    )
    dropped = _dedupe_stage(con, "funding_time_ms", sf.filename)
    _check_period(con, "funding_time_ms", sf)
    drift = _scalar(con, "SELECT max(abs(raw_funding_time_ms - funding_time_ms)) FROM _stage")
    if drift > FUNDING_MAX_DRIFT_MS:
        raise IngestError(f"{sf.filename}: funding time drift {drift} ms exceeds {FUNDING_MAX_DRIFT_MS} ms")
    bad = _scalar(con, "SELECT count(*) FROM _stage WHERE funding_rate IS NULL OR funding_interval_hours IS NULL")
    if bad:
        raise IngestError(f"{sf.filename}: {bad} rows with missing funding rate or interval")
    con.execute("DELETE FROM funding_rates WHERE source_key = ?", [sf.key])
    con.execute(
        """
        INSERT OR REPLACE INTO funding_rates
        SELECT ?, funding_time_ms, raw_funding_time_ms, funding_rate, funding_interval_hours,
               greatest(raw_funding_time_ms, funding_time_ms), ?, ?
        FROM _stage
        """,
        [symbol, sf.key, ingested_at],
    )
    return int(_scalar(con, "SELECT count(*) FROM _stage")), dropped


def _load_metrics(con, csv: Path, sf: SourceFile, symbol: str, ingested_at: int, delay_ms: int) -> tuple[int, int]:
    header = has_header(first_line(csv), Dataset.METRICS)
    value_columns = ", ".join(METRICS_COLUMNS[2:])
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _stage AS
        SELECT epoch_ms(strptime(create_time, '%Y-%m-%d %H:%M:%S')) AS ts_ms, symbol AS file_symbol, {value_columns}
        FROM {read_csv_sql(csv, METRICS_CSV_TYPES, header)}
        """
    )
    dropped = _dedupe_stage(con, "ts_ms", sf.filename)
    _check_period(con, "ts_ms", sf)
    wrong_symbol = _scalar(con, "SELECT count(*) FROM _stage WHERE file_symbol IS DISTINCT FROM ?", [symbol])
    if wrong_symbol:
        raise IngestError(f"{sf.filename}: {wrong_symbol} rows for a symbol other than {symbol}")
    con.execute("DELETE FROM open_interest WHERE source_key = ?", [sf.key])
    con.execute(
        f"""
        INSERT OR REPLACE INTO open_interest
        SELECT ?, ts_ms, ts_ms + ?, {value_columns}, ?, ? FROM _stage
        """,
        [symbol, delay_ms, sf.key, ingested_at],
    )
    return int(_scalar(con, "SELECT count(*) FROM _stage")), dropped


# --- orchestration ------------------------------------------------------------------------------


class Ingestor:
    def __init__(self, cfg: AppConfig, con: duckdb.DuckDBPyConnection, downloader: Downloader | None = None) -> None:
        self.cfg = cfg
        self.con = con
        self.downloader = downloader or Downloader(RetryPolicy.from_config(cfg.download))
        self.base_url = cfg.download.base_url
        self.raw_dir = cfg.data.raw_dir
        self.tmp_dir = cfg.data.tmp_dir
        self.symbol = cfg.market.symbol

    def plan(
        self,
        start: datetime,
        end: datetime,
        datasets: Iterable[Dataset] = DEFAULT_DATASETS,
        kline_intervals: Iterable[Timeframe] = (Timeframe.M1,),
    ) -> list[SourceFile]:
        files: list[SourceFile] = []
        for dataset in datasets:
            if dataset is Dataset.KLINES:
                for interval in kline_intervals:
                    files.extend(plan_files(dataset, self.symbol, start, end, interval))
            else:
                files.extend(plan_files(dataset, self.symbol, start, end))
        return files

    def ingest(
        self,
        start: datetime,
        end: datetime,
        datasets: Iterable[Dataset] = DEFAULT_DATASETS,
        kline_intervals: Iterable[Timeframe] = (Timeframe.M1,),
        refresh: bool = False,
        command: str = "ingest",
    ) -> IngestSummary:
        datasets, kline_intervals = tuple(datasets), tuple(kline_intervals)
        files = self.plan(start, end, datasets, kline_intervals)
        summary = IngestSummary(run_id=new_run_id(), planned=len(files))
        params = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "datasets": [d.value for d in datasets],
            "kline_intervals": [i.value for i in kline_intervals],
            "refresh": refresh,
        }
        self.con.execute(
            "INSERT INTO ingestion_runs VALUES (?, ?, ?, ?, ?, ?, NULL, 'running', NULL)",
            [summary.run_id, command, json.dumps(params), self.cfg.config_hash(), git_commit(), now_ms()],
        )
        try:
            for sf in files:
                self._process(sf, summary, refresh)
        except BaseException as exc:
            self._finish_run(summary, "failed", repr(exc))
            raise
        self._finish_run(summary, "succeeded" if summary.ok else "completed_with_errors")
        return summary

    def _finish_run(self, summary: IngestSummary, status: str, error: str | None = None) -> None:
        payload = asdict(summary) | ({"fatal_error": error} if error else {})
        self.con.execute(
            "UPDATE ingestion_runs SET finished_at_ms = ?, status = ?, summary_json = ? WHERE run_id = ?",
            [now_ms(), status, json.dumps(payload), summary.run_id],
        )

    def _new_record(self, sf: SourceFile, run_id: str) -> SourceFileRecord:
        return SourceFileRecord(
            source_key=sf.key,
            url=sf.url(self.base_url),
            dataset=sf.dataset.value,
            granularity=sf.granularity.value,
            symbol=sf.symbol,
            interval=sf.interval.value if sf.interval else None,
            period_start_ms=to_ms(sf.period_start),
            period_end_ms=to_ms(sf.period_end),
            status="planned",
            updated_at_ms=now_ms(),
            last_run_id=run_id,
        )

    def _save(self, record: SourceFileRecord, summary: IngestSummary, **changes: object) -> None:
        for name, value in changes.items():
            setattr(record, name, value)
        record.updated_at_ms = now_ms()
        record.last_run_id = summary.run_id
        upsert_source_file(self.con, record)

    def _process(self, sf: SourceFile, summary: IngestSummary, refresh: bool) -> None:
        local = self.raw_dir / sf.key
        record = get_source_file(self.con, sf.key) or self._new_record(sf, summary.run_id)

        if not refresh:
            if record.status == "not_available":
                summary.not_available += 1
                return
            if record.status == "ingested" and local.exists() and sha256_file(local) == record.ingested_sha256:
                summary.skipped += 1
                return

        try:
            checksum_text = self.downloader.fetch_bytes(sf.checksum_url(self.base_url)).decode("utf-8")
            expected = parse_checksum(checksum_text, sf.filename)
            if local.exists() and sha256_file(local) == expected:
                summary.reused_local += 1
                self._save(record, summary, expected_sha256=expected, actual_sha256=expected,
                           size_bytes=local.stat().st_size, error=None)
            else:
                result = self.downloader.download_file(sf.url(self.base_url), local, expected)
                summary.downloaded += 1
                self._save(record, summary, status="downloaded", expected_sha256=expected,
                           actual_sha256=result.sha256, size_bytes=result.size_bytes,
                           downloaded_at_ms=now_ms(), error=None)
        except NotAvailableError as exc:
            summary.not_available += 1
            self._save(record, summary, status="not_available", error=str(exc))
            return
        except ChecksumMismatchError as exc:
            summary.failed += 1
            summary.errors.append(str(exc))
            self._save(record, summary, status="checksum_mismatch", error=str(exc))
            return
        except (DownloadError, ValueError) as exc:
            summary.failed += 1
            summary.errors.append(f"{sf.key}: {exc}")
            self._save(record, summary, status="failed", error=str(exc))
            return

        if not refresh and record.status == "ingested" and record.ingested_sha256 == expected:
            summary.skipped += 1
            return

        try:
            rows, dropped = self._ingest_file(sf, local, expected, record, summary)
        except (IngestError, duckdb.Error, zipfile.BadZipFile, UnicodeDecodeError) as exc:
            summary.failed += 1
            summary.errors.append(f"{sf.key}: {exc}")
            self._save(record, summary, status="failed", error=str(exc))
            return
        summary.ingested += 1
        summary.rows_written += rows
        summary.duplicate_rows_dropped += dropped

    def _ingest_file(
        self, sf: SourceFile, local: Path, sha: str, record: SourceFileRecord, summary: IngestSummary
    ) -> tuple[int, int]:
        csv = extract_single_csv(local, self.tmp_dir)
        ingested_at = now_ms()
        try:
            self.con.execute("BEGIN TRANSACTION")
            try:
                if sf.dataset is Dataset.KLINES:
                    calendar = self.cfg.session_calendar()
                    rows, dropped = _load_klines(self.con, csv, sf, self.symbol, ingested_at,
                                                 None if calendar.always_open else calendar)
                elif sf.dataset is Dataset.FUNDING_RATE:
                    rows, dropped = _load_funding(self.con, csv, sf, self.symbol, ingested_at)
                else:
                    delay_ms = self.cfg.data.open_interest_availability_delay_seconds * 1000
                    rows, dropped = _load_metrics(self.con, csv, sf, self.symbol, ingested_at, delay_ms)
                # Saved on a copy so a failed COMMIT cannot leak "ingested" fields into the failure record.
                self._save(replace(record), summary, status="ingested", ingested_at_ms=ingested_at, ingested_sha256=sha,
                           row_count=rows, duplicate_rows_dropped=dropped, error=None)
                self.con.execute("COMMIT")
            except BaseException:
                self.con.execute("ROLLBACK")
                raise
        finally:
            self.con.execute("DROP TABLE IF EXISTS _stage")
            csv.unlink(missing_ok=True)
        return rows, dropped

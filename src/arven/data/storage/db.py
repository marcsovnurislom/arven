"""DuckDB connection and provenance-record helpers."""

from __future__ import annotations

import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import duckdb

from arven.core.time import to_ms, utc_now
from arven.data.storage.schema import DDL, SCHEMA_VERSION


def connect(database_path: Path | str, wait_seconds: float = 0.0) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the ARVEN database and ensure the schema exists. ``wait_seconds``: keep retrying that
    long while another process has the file open (the web app reads it many times a minute; a writer that gives up at
    once would skip its update)."""
    path = Path(database_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            con = duckdb.connect(str(path))
            break
        except duckdb.IOException:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)
    con.execute("SET TimeZone = 'UTC'")
    for statement in DDL:
        con.execute(statement)
    con.execute(
        "INSERT OR REPLACE INTO schema_info VALUES ('schema_version', ?)",
        [str(SCHEMA_VERSION)],
    )
    return con


def now_ms() -> int:
    return to_ms(utc_now())


def new_run_id() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


@dataclass
class SourceFileRecord:
    source_key: str
    url: str
    dataset: str
    granularity: str
    symbol: str
    interval: str | None
    period_start_ms: int
    period_end_ms: int
    status: str
    updated_at_ms: int
    expected_sha256: str | None = None
    actual_sha256: str | None = None
    size_bytes: int | None = None
    downloaded_at_ms: int | None = None
    ingested_at_ms: int | None = None
    ingested_sha256: str | None = None
    row_count: int | None = None
    duplicate_rows_dropped: int | None = None
    error: str | None = None
    last_run_id: str | None = None


_RECORD_FIELDS = [f.name for f in fields(SourceFileRecord)]


def get_source_file(con: duckdb.DuckDBPyConnection, source_key: str) -> SourceFileRecord | None:
    row = con.execute(
        f"SELECT {', '.join(_RECORD_FIELDS)} FROM source_files WHERE source_key = ?", [source_key]
    ).fetchone()
    return SourceFileRecord(**dict(zip(_RECORD_FIELDS, row))) if row else None


def upsert_source_file(con: duckdb.DuckDBPyConnection, record: SourceFileRecord) -> None:
    values = asdict(record)
    cols = ", ".join(_RECORD_FIELDS)
    placeholders = ", ".join("?" for _ in _RECORD_FIELDS)
    con.execute(
        f"INSERT OR REPLACE INTO source_files ({cols}) VALUES ({placeholders})",
        [values[name] for name in _RECORD_FIELDS],
    )

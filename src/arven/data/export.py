"""Parquet export of the DuckDB market tables.

DuckDB is the source of truth; Parquet is a reproducible, fully rewritten snapshot for research use:

    <parquet_dir>/ohlcv/timeframe=<tf>/year=<yyyy>/part_0.parquet     (1m and derived bars)
    <parquet_dir>/funding_rates/part_0.parquet
    <parquet_dir>/open_interest/year=<yyyy>/part_0.parquet

Each dataset is written to a temporary directory and swapped in only after the write succeeds.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb

_BAR_COLUMNS = (
    "symbol, open_time_ms, close_time_ms, open, high, low, close, volume, quote_volume, trade_count, "
    "taker_buy_volume, taker_buy_quote_volume"
)

EXPORTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "ohlcv": (
        f"""
        SELECT {_BAR_COLUMNS}, 1 AS bar_count, true AS is_complete, '1m' AS timeframe,
               year(epoch_ms(open_time_ms)) AS year
        FROM ohlcv_1m
        UNION ALL
        SELECT {_BAR_COLUMNS}, bar_count, is_complete, timeframe, year(epoch_ms(open_time_ms)) AS year
        FROM ohlcv
        ORDER BY timeframe, symbol, open_time_ms
        """,
        ("timeframe", "year"),
    ),
    "funding_rates": ("SELECT * EXCLUDE (ingested_at_ms) FROM funding_rates ORDER BY symbol, funding_time_ms", ()),
    "open_interest": (
        "SELECT * EXCLUDE (ingested_at_ms), year(epoch_ms(ts_ms)) AS year FROM open_interest ORDER BY symbol, ts_ms",
        ("year",),
    ),
}


def _dir_stats(path: Path) -> tuple[int, int]:
    files = [p for p in path.rglob("*.parquet") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def export_parquet(con: duckdb.DuckDBPyConnection, parquet_dir: Path) -> dict[str, dict[str, int]]:
    parquet_dir.mkdir(parents=True, exist_ok=True)
    stats: dict[str, dict[str, int]] = {}
    for name, (query, partition_by) in EXPORTS.items():
        final = parquet_dir / name
        tmp = parquet_dir / f".{name}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        rows = con.execute(f"SELECT count(*) FROM ({query})").fetchone()[0]
        target = str(tmp).replace("\\", "/").replace("'", "''")
        if partition_by:
            tmp.mkdir(parents=True)
            options = f"FORMAT parquet, COMPRESSION zstd, PARTITION_BY ({', '.join(partition_by)}), FILENAME_PATTERN 'part_{{i}}'"
        else:
            tmp.mkdir(parents=True)
            target += "/part_0.parquet"
            options = "FORMAT parquet, COMPRESSION zstd"
        if rows:
            con.execute(f"COPY ({query}) TO '{target}' ({options})")
        shutil.rmtree(final, ignore_errors=True)
        tmp.rename(final)
        files, size = _dir_stats(final)
        stats[name] = {"rows": int(rows), "files": files, "bytes": size}
    return stats

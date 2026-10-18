"""Backups of what cannot be re-downloaded: the forward signal record and the runtime state.

Market data can be rebuilt from Binance (``arven ingest``), but the signals the live process issued, when it issued
them, and its cursors/state exist only on this machine. ``make_backup`` zips them (and, optionally, a consistent copy
of the DuckDB file) into ``<data_dir>/backups/arven-<UTC time>.zip`` and keeps the newest ``keep`` archives.

The DuckDB copy is taken while holding a read-only connection: DuckDB then refuses a writer, so the file cannot change
during the copy. A live tick that starts in those seconds fails once and is retried at the next poll.
"""

from __future__ import annotations

import shutil
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Relative to the data dir. Directories are taken whole; for "paper" only its top-level files (the run index, cursor
# and summary), not the hourly run directories, which are re-computable artifacts.
STATE_DIRS = ("signals", "live", "telegram")
TOP_LEVEL_ONLY_DIRS = ("paper",)
SKIP_SUFFIXES = (".lock",)
MARKETS_DIR = "markets"  # further markets (gold): data/markets/<instrument>/ with its own signals/ and paper/
MARKET_STATE_DIRS = ("signals",)
CONFIG_PATTERNS = ("*.yaml", "*.csv")  # the settings and the session / macro calendars


@dataclass(frozen=True)
class BackupResult:
    path: Path
    files: int
    bytes_in: int
    database_included: bool
    removed: tuple[Path, ...]


def _state_files(data_dir: Path) -> Iterable[Path]:
    for name in STATE_DIRS:
        root = data_dir / name
        if root.is_dir():
            yield from (p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix not in SKIP_SUFFIXES)
    for name in TOP_LEVEL_ONLY_DIRS:
        root = data_dir / name
        if root.is_dir():
            yield from (p for p in sorted(root.iterdir()) if p.is_file() and p.suffix not in SKIP_SUFFIXES)
    markets = data_dir / MARKETS_DIR
    for market in sorted(m for m in markets.iterdir() if m.is_dir()) if markets.is_dir() else []:
        yield from _state_files_of(market, MARKET_STATE_DIRS, TOP_LEVEL_ONLY_DIRS)


def _state_files_of(root_dir: Path, whole: Iterable[str], top_level: Iterable[str]) -> Iterable[Path]:
    for name in whole:
        root = root_dir / name
        if root.is_dir():
            yield from (p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix not in SKIP_SUFFIXES)
    for name in top_level:
        root = root_dir / name
        if root.is_dir():
            yield from (p for p in sorted(root.iterdir()) if p.is_file() and p.suffix not in SKIP_SUFFIXES)


def make_backup(
    data_dir: Path, config_dir: Path, now: datetime, *, database_path: Path | None = None, keep: int = 10,
) -> BackupResult:
    """Write one zip; ``database_path`` adds a consistent copy of the DuckDB file. Old archives beyond ``keep`` are removed."""
    if keep < 1:
        raise ValueError("keep must be >= 1")
    out_dir = data_dir / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"arven-{now.strftime('%Y%m%dT%H%M%SZ')}.zip"
    tmp = target.with_suffix(".zip.part")
    files = bytes_in = 0
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in _state_files(data_dir):
            zf.write(p, Path("data") / p.relative_to(data_dir))
            files += 1
            bytes_in += p.stat().st_size
        if config_dir.is_dir():
            for p in sorted({q for pattern in CONFIG_PATTERNS for q in config_dir.rglob(pattern)}):
                zf.write(p, Path("config") / p.relative_to(config_dir))
                files += 1
                bytes_in += p.stat().st_size
        if database_path is not None:
            files_db, size_db = _add_database(zf, database_path, out_dir)
            files += files_db
            bytes_in += size_db
    tmp.replace(target)  # a crash mid-backup leaves only a .part file, never a truncated .zip
    archives = sorted(out_dir.glob("arven-*.zip"))
    removed = tuple(archives[:-keep])
    for p in removed:
        p.unlink()
    return BackupResult(target, files, bytes_in, database_path is not None, removed)


def _add_database(zf: zipfile.ZipFile, database_path: Path, scratch: Path) -> tuple[int, int]:
    import duckdb

    con = duckdb.connect(str(database_path), read_only=True)  # held during the copy: no writer can change the file
    try:
        copy = scratch / (database_path.name + ".copy")
        shutil.copyfile(database_path, copy)
    finally:
        con.close()
    try:
        zf.write(copy, Path("data") / database_path.name)
        return 1, copy.stat().st_size
    finally:
        copy.unlink(missing_ok=True)


__all__ = ["BackupResult", "make_backup"]

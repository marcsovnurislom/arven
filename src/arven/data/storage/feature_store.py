"""Feature cache: one Parquet file plus ``manifest.json`` per feature version.

Layout: ``<data_dir>/features/<version>/features_1h.parquet`` and ``.../manifest.json``.
The Parquet file is written through an in-memory DuckDB (no pandas / pyarrow). NaN is stored as NULL and
read back as NaN. The manifest records everything needed to reproduce and audit the build, including the
content hash of the table (independent of the file format).
"""

from __future__ import annotations

import json
import os
import platform
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from arven.core.time import to_ms, utc_now
from arven.features.builder import FeatureTable
from arven.features.spec import FeatureSpec

PARQUET_NAME = "features_1h.parquet"
MANIFEST_NAME = "manifest.json"


def cache_dir(data_dir: Path, version: str) -> Path:
    return data_dir / "features" / version


def _sql_path(p: Path) -> str:
    return str(p).replace("\\", "/").replace("'", "''")


def write_table_parquet(table: FeatureTable, path: Path) -> None:
    """Write ``table`` to ``path`` atomically (temp file in the same directory, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(table.columns)
    tmp_csv = tempfile.NamedTemporaryFile("w", suffix=".csv", dir=path.parent, delete=False, newline="\n")
    tmp_parquet = path.with_suffix(".parquet.part")
    try:
        with tmp_csv as fh:
            fh.write(",".join(["t_ms", *names]) + "\n")
            cols = [np.asarray(table.columns[n], dtype=np.float64) for n in names]
            for i in range(len(table)):
                cells = [str(int(table.t_ms[i]))]
                for col in cols:
                    v = col[i]
                    cells.append("" if v != v else repr(float(v)))
                fh.write(",".join(cells) + "\n")
        types = {"t_ms": "BIGINT", **{n: "DOUBLE" for n in names}}
        con = duckdb.connect(":memory:")
        try:
            con.execute(
                f"COPY (SELECT * FROM read_csv('{_sql_path(Path(tmp_csv.name))}', header=true, "
                f"columns={json.dumps(types).replace(chr(34), chr(39))}, nullstr='') ORDER BY t_ms) "
                f"TO '{_sql_path(tmp_parquet)}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        finally:
            con.close()
        os.replace(tmp_parquet, path)
    finally:
        Path(tmp_csv.name).unlink(missing_ok=True)
        tmp_parquet.unlink(missing_ok=True)


def read_table_parquet(path: Path, version: str, specs: tuple[FeatureSpec, ...]) -> FeatureTable:
    con = duckdb.connect(":memory:")
    try:
        d = con.execute(f"SELECT * FROM read_parquet('{_sql_path(path)}') ORDER BY t_ms").fetchnumpy()
    finally:
        con.close()
    t_ms = np.asarray(d.pop("t_ms"), dtype=np.int64)
    columns = {name: np.ma.filled(np.ma.asarray(arr).astype(np.float64), np.nan) for name, arr in d.items()}
    return FeatureTable(version, t_ms, columns, specs)


def read_window_parquet(path: Path, version: str, specs: tuple[FeatureSpec, ...], start_ms: int, end_ms: int) -> FeatureTable:
    """Read only the rows with ``start_ms <= t_ms < end_ms`` (so a caller never loads rows outside its window)."""
    con = duckdb.connect(":memory:")
    try:
        d = con.execute(
            f"SELECT * FROM read_parquet('{_sql_path(path)}') WHERE t_ms >= ? AND t_ms < ? ORDER BY t_ms", [start_ms, end_ms]
        ).fetchnumpy()
    finally:
        con.close()
    t_ms = np.asarray(d.pop("t_ms"), dtype=np.int64)
    columns = {name: np.ma.filled(np.ma.asarray(arr).astype(np.float64), np.nan) for name, arr in d.items()}
    return FeatureTable(version, t_ms, columns, specs)


def build_manifest(
    table: FeatureTable,
    *,
    definition_hash: str,
    features_config_hash: str,
    app_config_hash: str,
    source_fingerprint: str,
    input_summary: dict[str, Any],
    git_commit: str | None,
    history_start: datetime,
    history_end: datetime,
    peak_working_set_mb: float | None,
) -> dict[str, Any]:
    ready = table.columns["feat_ready"] == 1.0
    return {
        "feature_version": table.version,
        "decision_timeframe": "1h",
        "definition_hash": definition_hash,
        "features_config_hash": features_config_hash,
        "app_config_hash": app_config_hash,
        "source_fingerprint": source_fingerprint,
        "data_sha256": table.content_sha256(),
        "rows": len(table),
        "decision_time_first_ms": int(table.t_ms[0]) if len(table) else None,
        "decision_time_last_ms": int(table.t_ms[-1]) if len(table) else None,
        "history_start_ms": to_ms(history_start),
        "history_end_ms": to_ms(history_end),
        "first_ready_ms": int(table.t_ms[ready][0]) if ready.any() else None,
        "ready_rows": int(ready.sum()),
        "columns": [
            {
                "name": s.name,
                "group": s.group,
                "source": s.source,
                "warmup_bars": s.warmup_bars,
                "required": s.required,
                "description": s.description,
            }
            for s in table.specs
        ],
        "inputs": input_summary,
        "git_commit": git_commit,
        "created_at_ms": to_ms(utc_now()),
        "numpy_version": np.__version__,
        "duckdb_version": duckdb.__version__,
        "python_version": platform.python_version(),
        "peak_working_set_mb": peak_working_set_mb,
    }


def write_cache(directory: Path, table: FeatureTable, manifest: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    write_table_parquet(table, directory / PARQUET_NAME)
    tmp = directory / (MANIFEST_NAME + ".part")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, directory / MANIFEST_NAME)


def read_manifest(directory: Path) -> dict[str, Any]:
    return json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))


def read_cache(directory: Path, specs: tuple[FeatureSpec, ...]) -> tuple[FeatureTable, dict[str, Any]]:
    manifest = read_manifest(directory)
    return read_table_parquet(directory / PARQUET_NAME, manifest["feature_version"], specs), manifest

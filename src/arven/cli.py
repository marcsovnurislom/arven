"""ARVEN command line.

    python -m arven ingest     --start 2024-01-01 --end 2024-03-01 [--datasets klines,fundingRate,metrics] [--refresh]
    python -m arven resample   --start ... --end ...
    python -m arven crosscheck --start ... --end ... [--refresh]
    python -m arven quality    --start ... --end ...
    python -m arven export
    python -m arven status
    python -m arven features build      # causal 1h-grid features -> data/features/<version>/
    python -m arven features check      # verify the cache (hash, invariants) and print development-period stats
    python -m arven features status

``--start``/``--end`` default to ``data.history_start``/``data.history_end`` from the configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

import numpy as np

from arven.core.config import AppConfig, load_config
from arven.core.features_config import load_features_config
from arven.core.time import from_ms, to_ms, to_utc_datetime
from arven.data.adapters.binance_bulk import Dataset
from arven.data.crosscheck import compare
from arven.data.export import export_parquet
from arven.data.ingestion import DEFAULT_DATASETS, Ingestor
from arven.data.quality import QualityChecker
from arven.data.reader import load_feature_inputs, open_readonly
from arven.data.resample import DERIVED_TIMEFRAMES, resample
from arven.data.storage import feature_store
from arven.data.storage.db import connect, git_commit
from arven.features.builder import build_features, decision_grid
from arven.features.checks import invariant_violations
from arven.features.registry import build_registry, definition_hash


def _range(args: argparse.Namespace, cfg: AppConfig) -> tuple[datetime, datetime]:
    start = to_utc_datetime(args.start) if args.start else cfg.data.history_start
    end = to_utc_datetime(args.end) if args.end else cfg.data.history_end
    if start >= end:
        raise SystemExit("--start must be before --end")
    return start, end


def _print_summary(summary) -> None:
    fields = ["planned", "downloaded", "reused_local", "ingested", "skipped", "not_available", "failed",
              "rows_written", "duplicate_rows_dropped"]
    print(f"run {summary.run_id}: " + ", ".join(f"{f}={getattr(summary, f)}" for f in fields))
    for err in summary.errors:
        print(f"  ERROR {err}")


def cmd_ingest(cfg: AppConfig, args: argparse.Namespace) -> int:
    start, end = _range(args, cfg)
    datasets = tuple(Dataset(d) for d in args.datasets.split(",")) if args.datasets else DEFAULT_DATASETS
    with connect(cfg.data.database_path) as con:
        summary = Ingestor(cfg, con).ingest(start, end, datasets, refresh=args.refresh)
    _print_summary(summary)
    return 0 if summary.ok else 1


def cmd_resample(cfg: AppConfig, args: argparse.Namespace) -> int:
    start, end = _range(args, cfg)
    with connect(cfg.data.database_path) as con:
        written = resample(con, cfg.market.symbol, start, end)
    for tf, n in written.items():
        print(f"{tf.value:>4}: {n} bars")
    return 0


def cmd_crosscheck(cfg: AppConfig, args: argparse.Namespace) -> int:
    start, end = _range(args, cfg)
    tfs = tuple(cfg.download.crosscheck_timeframes)
    with connect(cfg.data.database_path) as con:
        summary = Ingestor(cfg, con).ingest(
            start, end, (Dataset.KLINES,), kline_intervals=tfs, refresh=args.refresh, command="crosscheck"
        )
        _print_summary(summary)
        results = [compare(con, cfg.market.symbol, tf, start, end) for tf in tfs]
    ok = summary.ok
    for r in results:
        ok &= r.passed
        print(
            f"{r.timeframe:>4}: {'PASS' if r.passed else 'FAIL'} native={r.native_bars} derived={r.derived_bars} "
            f"compared={r.compared} missing_in_derived={r.missing_in_derived} missing_in_native={r.missing_in_native} "
            f"incomplete={r.incomplete_derived} price_mismatch={r.price_mismatches} "
            f"trades_mismatch={r.trade_count_mismatches} volume_mismatch={r.volume_mismatches} "
            f"max_abs_price_diff={r.max_abs_price_diff} max_rel_volume_diff={r.max_rel_volume_diff:.3g}"
        )
        for ex in r.examples:
            print(f"      example: {ex}")
    return 0 if ok else 1


def cmd_quality(cfg: AppConfig, args: argparse.Namespace) -> int:
    start, end = _range(args, cfg)
    with connect(cfg.data.database_path) as con:
        checker = QualityChecker(cfg, con)
        results = checker.run(start, end)
    print(f"quality run {checker.run_id} for [{start.isoformat()}, {end.isoformat()})")
    errors = 0
    for r in results:
        status = "PASS" if r.passed else ("FAIL" if r.severity == "error" else r.severity.upper())
        errors += (not r.passed) and r.severity == "error"
        print(f"  {status:<7} {r.check_id:<40} {r.observed}")
        if not r.passed and r.details:
            print(f"          {json.dumps(r.details, default=str)[:500]}")
    return 1 if errors else 0


def cmd_export(cfg: AppConfig, args: argparse.Namespace) -> int:
    with connect(cfg.data.database_path) as con:
        stats = export_parquet(con, cfg.data.parquet_dir)
    for name, s in stats.items():
        print(f"{name:<14} rows={s['rows']:>9} files={s['files']:>3} size={s['bytes'] / 1e6:.2f} MB")
    return 0


def cmd_status(cfg: AppConfig, args: argparse.Namespace) -> int:
    db_path = cfg.data.database_path
    with connect(db_path) as con:
        print(f"database: {db_path}")
        for table, ts in [("ohlcv_1m", "open_time_ms"), ("funding_rates", "funding_time_ms"), ("open_interest", "ts_ms")]:
            n, lo, hi = con.execute(
                f"SELECT count(*), strftime(epoch_ms(min({ts})), '%Y-%m-%dT%H:%MZ'), "
                f"strftime(epoch_ms(max({ts})), '%Y-%m-%dT%H:%MZ') FROM {table}"
            ).fetchone()
            print(f"  {table:<14} rows={n:>9}  min={lo}  max={hi}")
        for table in ("ohlcv", "ohlcv_native"):
            for tf, n, incomplete in con.execute(
                f"SELECT timeframe, count(*), count(*) FILTER (NOT coalesce({'is_complete' if table == 'ohlcv' else 'true'}, true)) "
                f"FROM {table} GROUP BY timeframe ORDER BY min(close_time_ms - open_time_ms)"
            ).fetchall():
                print(f"  {table + '[' + tf + ']':<20} rows={n:>7}  incomplete={incomplete}")
        print("  source_files by dataset/interval/status:")
        for ds, interval, status, n, rows in con.execute(
            "SELECT dataset, coalesce(interval, '-'), status, count(*), sum(row_count) FROM source_files "
            "GROUP BY ALL ORDER BY ALL"
        ).fetchall():
            print(f"    {ds:<12} {interval:<4} {status:<16} files={n:>5} rows={rows}")
    print(f"  database file size: {db_path.stat().st_size / 1e6:.2f} MB")
    return 0


def _peak_working_set_mb() -> float | None:
    """Peak working set of this process in MB (Windows via psapi, elsewhere via resource); None if unknown."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return counters.PeakWorkingSetSize / 1e6
            return None
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:  # noqa: BLE001 - diagnostics only
        return None


def cmd_features_build(cfg: AppConfig, args: argparse.Namespace) -> int:
    fcfg = load_features_config(args.config_dir)
    with open_readonly(cfg.data.database_path) as con:
        inputs = load_feature_inputs(con, cfg)
    t_ms = decision_grid(to_ms(cfg.data.history_start), to_ms(cfg.data.history_end))
    table = build_features(inputs, t_ms, fcfg)
    problems = invariant_violations(table)
    if problems:
        for p in problems:
            print(f"  INVARIANT VIOLATION {p}")
        print("not writing the cache")
        return 1
    peak = _peak_working_set_mb()
    manifest = feature_store.build_manifest(
        table,
        definition_hash=definition_hash(fcfg),
        features_config_hash=fcfg.config_hash(),
        app_config_hash=cfg.config_hash(),
        source_fingerprint=inputs.fingerprint(),
        input_summary={
            **{f"bars_{tf.value}": len(s) for tf, s in inputs.bars.items()},
            "funding": len(inputs.funding),
            "open_interest": len(inputs.open_interest),
        },
        git_commit=git_commit(),
        history_start=cfg.data.history_start,
        history_end=cfg.data.history_end,
        peak_working_set_mb=peak,
    )
    directory = feature_store.cache_dir(cfg.data.data_dir, fcfg.version)
    feature_store.write_cache(directory, table, manifest)
    print(f"feature version {fcfg.version}: {len(table)} rows x {len(table.columns)} columns -> {directory}")
    first_ready = from_ms(manifest["first_ready_ms"]).isoformat() if manifest["first_ready_ms"] else None
    print(f"  first feat_ready decision time: {first_ready}  ready rows: {manifest['ready_rows']}")
    print(f"  data_sha256 {manifest['data_sha256']}")
    if peak is not None:
        print(f"  peak working set: {peak:.0f} MB")
    return 0


def cmd_features_check(cfg: AppConfig, args: argparse.Namespace) -> int:
    fcfg = load_features_config(args.config_dir)
    specs = build_registry(fcfg)
    directory = feature_store.cache_dir(cfg.data.data_dir, fcfg.version)
    table, manifest = feature_store.read_cache(directory, specs)
    ok = True

    def report(passed: bool, text: str) -> None:
        nonlocal ok
        ok &= passed
        print(f"  {'PASS' if passed else 'FAIL'}  {text}")

    print(f"feature cache {directory}")
    report(manifest["definition_hash"] == definition_hash(fcfg), "definition hash matches the current features.yaml and registry")
    report(list(table.columns) == [s.name for s in specs], "columns match the registry")
    report(table.content_sha256() == manifest["data_sha256"], "content hash matches the manifest")
    violations = invariant_violations(table)
    report(not violations, f"value invariants ({len(violations)} violations)")
    for v in violations[:20]:
        print(f"        {v}")

    # Statistics use the development period only: the sealed test period is never inspected.
    dev = cfg.splits.development
    mask = (table.t_ms >= to_ms(dev.start)) & (table.t_ms < to_ms(dev.end))
    ready = int((table.columns["feat_ready"][mask] == 1.0).sum())
    print(f"development period {dev.start.date()} -> {dev.end.date()}: {int(mask.sum())} rows, {ready} ready")
    print(f"  {'feature':<26}{'nan%':>7}{'mean':>12}{'std':>12}{'min':>12}{'max':>12}")
    for s in specs:
        col = table.columns[s.name][mask]
        fin = col[np.isfinite(col)]
        stats = (fin.mean(), fin.std(), fin.min(), fin.max()) if len(fin) else (np.nan,) * 4
        nan_pct = 100 * (1 - len(fin) / max(len(col), 1))
        print(f"  {s.name:<26}{nan_pct:>6.1f}%" + "".join(f"{x:>12.4g}" for x in stats))
    return 0 if ok else 1


def cmd_features_status(cfg: AppConfig, args: argparse.Namespace) -> int:
    fcfg = load_features_config(args.config_dir)
    directory = feature_store.cache_dir(cfg.data.data_dir, fcfg.version)
    if not (directory / feature_store.MANIFEST_NAME).exists():
        print(f"no feature cache at {directory}; run `arven features build`")
        return 1
    m = feature_store.read_manifest(directory)
    first_ready = from_ms(m["first_ready_ms"]).isoformat() if m["first_ready_ms"] else None
    print(f"feature cache {directory}")
    print(f"  version {m['feature_version']}  rows {m['rows']}  columns {len(m['columns'])}")
    print(f"  decision times {from_ms(m['decision_time_first_ms']).isoformat()} .. {from_ms(m['decision_time_last_ms']).isoformat()}")
    print(f"  first feat_ready {first_ready}  ready rows {m['ready_rows']}")
    print(f"  built from git {m['git_commit']}, created {from_ms(m['created_at_ms']).isoformat()}")
    print(f"  up to date with features.yaml: {m['definition_hash'] == definition_hash(fcfg)}")
    print(f"  inputs {m['inputs']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arven", description="ARVEN data pipeline (research only, no execution)")
    parser.add_argument("--config-dir", default=None, help="configuration directory (default: <project>/config)")
    sub = parser.add_subparsers(dest="command", required=True)

    def with_range(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--start", help="UTC start date, inclusive (YYYY-MM-DD)")
        p.add_argument("--end", help="UTC end date, exclusive (YYYY-MM-DD)")
        return p

    p = with_range(sub.add_parser("ingest", help="download and ingest Binance bulk files"))
    p.add_argument("--datasets", help=f"comma-separated subset of {[d.value for d in Dataset]}")
    p.add_argument("--refresh", action="store_true", help="re-check checksums and re-ingest even if already ingested")
    p.set_defaults(func=cmd_ingest)

    with_range(sub.add_parser("resample", help=f"build {[t.value for t in DERIVED_TIMEFRAMES]} bars from 1m")).set_defaults(func=cmd_resample)

    p = with_range(sub.add_parser("crosscheck", help="compare derived bars with native Binance klines"))
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_crosscheck)

    with_range(sub.add_parser("quality", help="run data-quality checks")).set_defaults(func=cmd_quality)
    sub.add_parser("export", help="export DuckDB tables to Parquet").set_defaults(func=cmd_export)
    sub.add_parser("status", help="show stored data summary").set_defaults(func=cmd_status)

    p = sub.add_parser("features", help="build and inspect the causal feature cache (Stage 3)")
    fsub = p.add_subparsers(dest="features_command", required=True)
    fsub.add_parser("build", help="compute features on the 1h grid, write the Parquet cache").set_defaults(func=cmd_features_build)
    fsub.add_parser("check", help="verify the cache and print development-period stats").set_defaults(func=cmd_features_check)
    fsub.add_parser("status", help="show the cache manifest").set_defaults(func=cmd_features_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config_dir)
    return args.func(cfg, args)


if __name__ == "__main__":
    sys.exit(main())

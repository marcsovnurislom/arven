"""ARVEN command line.

    python -m arven ingest     --start 2024-01-01 --end 2024-03-01 [--datasets klines,fundingRate,metrics] [--refresh]
    python -m arven resample   --start ... --end ...
    python -m arven crosscheck --start ... --end ... [--refresh]
    python -m arven quality    --start ... --end ...
    python -m arven export
    python -m arven status

``--start``/``--end`` default to ``data.history_start``/``data.history_end`` from the configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from arven.core.config import AppConfig, load_config
from arven.core.time import to_utc_datetime
from arven.data.adapters.binance_bulk import Dataset
from arven.data.crosscheck import compare
from arven.data.export import export_parquet
from arven.data.ingestion import DEFAULT_DATASETS, Ingestor
from arven.data.quality import QualityChecker
from arven.data.resample import DERIVED_TIMEFRAMES, resample
from arven.data.storage.db import connect


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config_dir)
    return args.func(cfg, args)


if __name__ == "__main__":
    sys.exit(main())

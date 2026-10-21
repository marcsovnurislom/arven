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
        written = resample(con, cfg.market.symbol, start, end, calendar=cfg.session_calendar())
    for tf, n in written.items():
        print(f"{tf.value:>4}: {n} bars")
    return 0


def cmd_duka_download(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.data.dukascopy_ingestion import DukascopyIngestor

    start, end = _range(args, cfg)
    summary = DukascopyIngestor(cfg).download(start, end, progress=lambda m: print(m, flush=True))
    print(f"planned={summary.planned} present={summary.present} downloaded={summary.downloaded} "
          f"not_available={summary.not_available} failed={summary.failed}")
    for err in summary.errors[:50]:
        print(f"  ERROR {err}")
    return 0 if summary.ok else 1


def cmd_duka_ingest(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.data.dukascopy_ingestion import DukascopyIngestor

    start, end = _range(args, cfg)
    with connect(cfg.data.database_path) as con:
        s = DukascopyIngestor(cfg).ingest(con, start, end, refresh=args.refresh)
    print(f"run {s.run_id}: days={s.planned_days} ingested={s.ingested} skipped={s.skipped} missing_raw={s.missing_raw} "
          f"not_available={s.not_available} failed={s.failed} rows_written={s.rows_written} "
          f"out_of_session_dropped={s.out_of_session_dropped}")
    for err in s.errors[:50]:
        print(f"  ERROR {err}")
    return 0 if s.ok else 1


def cmd_duka_closures(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Zero-volume runs that fall inside *regular* hours: candidate holiday closures / early closes."""
    from arven.core.sessions import SessionCalendar
    from arven.data.adapters.dukascopy import DukaDayFile, decode_m1, mid_candles, plan_days
    from arven.data.dukascopy_ingestion import zero_volume_runs

    start, end = _range(args, cfg)
    regular = SessionCalendar(cfg.market.session)
    assert cfg.dukascopy is not None
    print("start_utc,end_utc,minutes,weekday")
    for day in plan_days(cfg.dukascopy.instrument, start, end):
        paths = [cfg.data.raw_dir / DukaDayFile(cfg.dukascopy.instrument, day, s).key for s in ("BID", "ASK")]
        if not all(p.exists() for p in paths):
            continue
        mid = mid_candles(*(decode_m1(p.read_bytes(), day, cfg.dukascopy.point) for p in paths))
        open_ = regular.is_open(mid.time_ms)
        for s, e in zero_volume_runs(mid, 1):
            inside = int(open_[(mid.time_ms >= s) & (mid.time_ms < e)].sum())
            if inside >= args.min_minutes:
                print(f"{from_ms(s).isoformat()},{from_ms(e).isoformat()},{inside},{from_ms(s).strftime('%a')}")
    return 0


def cmd_crosscheck(cfg: AppConfig, args: argparse.Namespace) -> int:
    start, end = _range(args, cfg)
    tfs = tuple(cfg.download.crosscheck_timeframes)
    with connect(cfg.data.database_path) as con:
        summary = Ingestor(cfg, con).ingest(
            start, end, (Dataset.KLINES,), kline_intervals=tfs, refresh=args.refresh, command="crosscheck"
        )
        _print_summary(summary)
        results = [compare(con, cfg.market.symbol, tf, start, end, cfg.session_calendar()) for tf in tfs]
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
    t_ms = decision_grid(to_ms(cfg.data.history_start), to_ms(cfg.data.history_end), cfg.session_calendar())
    table = build_features(inputs, t_ms, fcfg, **cfg.feature_flags())
    problems = invariant_violations(table)
    if problems:
        for p in problems:
            print(f"  INVARIANT VIOLATION {p}")
        print("not writing the cache")
        return 1
    peak = _peak_working_set_mb()
    manifest = feature_store.build_manifest(
        table,
        definition_hash=definition_hash(fcfg, **cfg.feature_flags()),
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
    directory = feature_store.cache_dir(cfg.data.data_dir, fcfg.version, cfg.instrument)
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
    specs = build_registry(fcfg, **cfg.feature_flags())
    directory = feature_store.cache_dir(cfg.data.data_dir, fcfg.version, cfg.instrument)
    table, manifest = feature_store.read_cache(directory, specs)
    ok = True

    def report(passed: bool, text: str) -> None:
        nonlocal ok
        ok &= passed
        print(f"  {'PASS' if passed else 'FAIL'}  {text}")

    print(f"feature cache {directory}")
    report(manifest["definition_hash"] == definition_hash(fcfg, **cfg.feature_flags()), "definition hash matches the current features.yaml and registry")
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
    directory = feature_store.cache_dir(cfg.data.data_dir, fcfg.version, cfg.instrument)
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
    print(f"  up to date with features.yaml: {m['definition_hash'] == definition_hash(fcfg, **cfg.feature_flags())}")
    print(f"  inputs {m['inputs']}")
    return 0


def _print_metrics(m: dict) -> None:
    def f(x, spec=".6g"):
        return "n/a" if x is None else format(x, spec)

    print(f"  period {m['period']}  days {m['window_days']:.1f}  initial {f(m['initial_equity'], ',.2f')}  final {f(m['final_equity'], ',.2f')}")
    print(f"  total_return {f(m['total_return'])}  gross_return {f(m['gross_return'])}  net_pnl {f(m['net_pnl_usdt'], ',.2f')} USDT  cagr {f(m['cagr'])}")
    print(f"  volatility {f(m['volatility'])}  sharpe {f(m['sharpe'])}  sortino {f(m['sortino'])}")
    print(f"  max_drawdown {f(m['max_drawdown'])} (intrabar {f(m['max_intrabar_drawdown'])}, {m['max_drawdown_duration_days']:.1f} days)")
    print(f"  trades {m['n_trades']}  win_rate {f(m['win_rate'])}  profit_factor {f(m['profit_factor'])}  avg_trade {f(m['avg_trade_usdt'])} USDT")
    print(f"  fees {f(m['fees_total'], ',.2f')}  slippage {f(m['slippage_total'], ',.2f')}  funding {f(m['funding_total'], ',.2f')}  turnover {f(m['turnover'])}  exposure {f(m['exposure_time'])}")
    print(f"  exits {m['exit_reasons']}  orders {m['orders']}  liquidations {m['liquidations']}")
    for w in m["warnings"]:
        print(f"  WARNING: {w}")


def _resolve_window(cfg: AppConfig, args: argparse.Namespace, context: dict):
    from arven.core.splitguard import BacktestPeriod
    from arven.runs import make_guard

    start = to_ms(to_utc_datetime(args.start)) if args.start else None
    end = to_ms(to_utc_datetime(args.end)) if args.end else None
    return make_guard(cfg).resolve(
        BacktestPeriod(args.period), start, end, allow_sealed=args.allow_sealed, reason=args.reason, context=context
    )


def cmd_backtest_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.backtest.baselines import BuyAndHold, NoTrade, RandomEntry
    from arven.core.backtest_config import load_backtest_config
    from arven.runs import backtests_dir, execute_run, load_inputs

    bt, fcfg = load_backtest_config(args.config_dir), load_features_config(args.config_dir)
    window = _resolve_window(cfg, args, {"command": "backtest run", "provider": args.provider})
    inputs = load_inputs(cfg, fcfg, window)
    pipeline = None
    if args.provider == "no_trade":
        provider = NoTrade()
    elif args.provider == "buy_and_hold":
        provider = BuyAndHold(bt.baselines.buy_and_hold.notional_fraction)
    elif args.provider == "pipeline":
        from arven.core.regime_config import load_regime_config
        from arven.core.risk_config import load_risk_config
        from arven.core.strategies_config import load_strategies_config
        from arven.decision.pipeline import Stage5Pipeline

        ml_filter = None
        if getattr(args, "ml_model", None):
            from arven.ml_runs import load_meta_filter

            ml_filter = load_meta_filter(cfg, args.ml_model)
        elif getattr(args, "random_filter_rate", None) is not None:
            from arven.ml.filter import RandomFilter

            ml_filter = RandomFilter(args.random_filter_rate, seed=cfg.project.random_seed)
        pipeline = Stage5Pipeline(
            load_regime_config(args.config_dir), load_strategies_config(args.config_dir),
            load_risk_config(args.config_dir), bt, ml_filter=ml_filter,
        )
        provider = pipeline
    else:
        re = bt.baselines.random_entry
        provider = RandomEntry(
            base_seed=cfg.project.random_seed, spawn_index=args.seed_index, n_trades=re.n_trades,
            holding_minutes=re.holding_minutes, notional_fraction=re.notional_fraction, direction_mode=re.direction_mode,
        )
    out = execute_run(cfg, bt, fcfg, window, provider, inputs, stress=args.stress, out_dir=backtests_dir(cfg))
    print(f"run {out.run_id} ({args.provider}) -> {out.run_dir}")
    _print_metrics(out.metrics)
    print(f"  result_hash {out.result_hash}   touched_test_set={out.manifest['touched_test_set']}   git_dirty={out.manifest['git_dirty']}")
    if pipeline is not None:
        from arven.reports import format_breakdown, per_regime_breakdown

        print("\nper-regime breakdown (development-period analysis; see docs/current_state.md):")
        print(format_breakdown(per_regime_breakdown(out.result, pipeline.history)))
    return 0


def cmd_backtest_baselines(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.core.backtest_config import load_backtest_config
    from arven.runs import comparison_text, load_inputs, run_baselines

    bt, fcfg = load_backtest_config(args.config_dir), load_features_config(args.config_dir)
    window = _resolve_window(cfg, args, {"command": "backtest baselines"})
    inputs = load_inputs(cfg, fcfg, window)
    summary = run_baselines(cfg, bt, fcfg, window, inputs, stress=args.stress, n_seeds=args.seeds)
    print(comparison_text(summary))
    print(f"artifacts: {summary['dir']}")
    peak = _peak_working_set_mb()
    if peak is not None:
        print(f"peak working set: {peak:.0f} MB")
    return 0 if summary["random_entry"]["reproducibility_check_seed0"] else 1


def _find_run_dir(cfg: AppConfig, arg: str):
    from pathlib import Path

    from arven.runs import backtests_dir

    p = Path(arg)
    if p.exists():
        return p
    q = backtests_dir(cfg) / arg
    if q.exists():
        return q
    raise SystemExit(f"no such run directory: {arg}")


def cmd_backtest_verify(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.runs import verify_run

    res = verify_run(_find_run_dir(cfg, args.run))
    print(f"verify {args.run}: {'OK' if res['ok'] else 'FAILED'}  result_hash {res['result_hash']}  touched_test_set={res['touched_test_set']}")
    for p in res["problems"]:
        print(f"  PROBLEM {p}")
    return 0 if res["ok"] else 1


def cmd_backtest_show(cfg: AppConfig, args: argparse.Namespace) -> int:
    d = _find_run_dir(cfg, args.run)
    m = json.loads((d / "run.json").read_text(encoding="utf-8"))
    if "metrics" not in m:
        print(json.dumps(m, indent=2, sort_keys=True)[:4000])
        return 0
    print(f"run {m['run_id']}  provider {m['provider'].get('name')}  git {m['git_commit']}{' (dirty)' if m['git_dirty'] else ''}")
    _print_metrics(m["metrics"])
    print(f"  feature {m['feature_version']} content {m['feature_content_hash'][:12]}  result_hash {m['result_hash']}")
    return 0


def cmd_ml_train(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.core.ml_config import load_ml_config
    from arven.core.regime_config import load_regime_config
    from arven.core.risk_config import load_risk_config
    from arven.core.strategies_config import load_strategies_config
    from arven.core.backtest_config import load_backtest_config
    from arven.ml_runs import InsufficientDataError, train_and_save

    ml_cfg = load_ml_config(args.config_dir)
    fcfg = load_features_config(args.config_dir)
    bt = load_backtest_config(args.config_dir)
    regime_cfg = load_regime_config(args.config_dir)
    strategies_cfg = load_strategies_config(args.config_dir)
    risk_cfg = load_risk_config(args.config_dir)
    try:
        out = train_and_save(
            cfg, ml_cfg, fcfg, regime_cfg, strategies_cfg, risk_cfg, bt, args.model_family,
            shuffle_labels_seed=args.shuffle_labels_seed,
        )
    except InsufficientDataError as e:
        print(f"INSUFFICIENT DATA: {e}")
        print(f"  candidates_total={e.n_candidates_total} ineligible_risk={e.n_ineligible_risk} "
              f"ineligible_label={e.n_ineligible_label} eligible={e.n_eligible}")
        return 1
    print(f"model {out.model_id} -> {out.model_dir}")
    m = out.manifest
    print(f"  candidates_total={m['n_candidates_total']} ineligible_risk={m['n_ineligible_risk']} "
          f"ineligible_label={m['n_ineligible_label']} train_rows={m['n_train_rows']} calibration_rows={m['n_calibration_rows']}")
    print(f"  hyperparameters={m['hyperparameters']}")
    print(f"  folds evaluated: {len(m['fold_summary'])}")
    print(f"  validation metrics (raw): {m['metrics']['raw']}")
    print(f"  validation metrics (calibrated): {m['metrics']['calibrated']}")
    print(f"  threshold={m['threshold']}  model_artifact_hash={m['model_artifact_hash'][:16]}...")
    for w in m["warnings"]:
        print(f"  WARNING: {w}")
    return 0


def cmd_ml_verify(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.ml.artifact import verify_artifact
    from arven.ml_runs import models_dir

    res = verify_artifact(models_dir(cfg) / args.model)
    print(f"verify {args.model}: {'OK' if res['ok'] else 'FAILED'}  model_artifact_hash={res['model_artifact_hash'][:16]}...")
    for p in res["problems"]:
        print(f"  PROBLEM {p}")
    return 0 if res["ok"] else 1


def cmd_ml_show(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.ml_runs import models_dir

    m = json.loads((models_dir(cfg) / args.model / "manifest.json").read_text(encoding="utf-8"))
    print(json.dumps(m, indent=2, sort_keys=True))
    return 0


def cmd_wfo_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.core.backtest_config import load_backtest_config
    from arven.core.ml_config import load_ml_config
    from arven.core.regime_config import load_regime_config
    from arven.core.risk_config import load_risk_config
    from arven.core.strategies_config import load_strategies_config
    from arven.wfo import InsufficientWindowsError
    from arven.wfo_runs import run_stage7

    ml_cfg = load_ml_config(args.config_dir)
    fcfg = load_features_config(args.config_dir)
    bt = load_backtest_config(args.config_dir)
    regime_cfg = load_regime_config(args.config_dir)
    strategies_cfg = load_strategies_config(args.config_dir)
    risk_cfg = load_risk_config(args.config_dir)
    try:
        out = run_stage7(cfg, ml_cfg, fcfg, regime_cfg, strategies_cfg, risk_cfg, bt)
    except InsufficientWindowsError as e:
        print(f"INSUFFICIENT WINDOWS: {e}")
        return 1
    r = out.report
    sched = r["schedule"]
    print(f"wfo run {out.run_id} -> {out.run_dir}")
    print(f"  windows generated={sched['n_windows_generated']} backtested={sched['n_windows_backtested']} "
          f"boundary_excluded={sched['n_windows_boundary_excluded']} minimum={sched['minimum_windows']}")
    for family in ("logistic", "lightgbm"):
        print(f"  {family}: hyperparameters are selected per window (causally, from only prior folds) - see report.json")
        for variant in ("ml", "shuffled", "random"):
            d = r["distributions"][family][variant]["total_return"]
            print(f"    {variant}: total_return n={d['n']} mean={d['mean']} p5={d['p5']} p50={d['p50']} p95={d['p95']}")
    bd = r["distributions"]["baseline"]["total_return"]
    print(f"  baseline: total_return n={bd['n']} mean={bd['mean']} p5={bd['p5']} p50={bd['p50']} p95={bd['p95']}")
    return 0


def cmd_wfo_show(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.wfo_runs import wfo_dir

    report = json.loads((wfo_dir(cfg) / args.run / "report.json").read_text(encoding="utf-8"))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _build_pipeline(cfg: AppConfig, args: argparse.Namespace, bt):
    from arven.core.macro_config import load_macro_events
    from arven.core.regime_config import load_regime_config
    from arven.core.risk_config import load_risk_config
    from arven.core.strategies_config import load_strategies_config
    from arven.decision.pipeline import Stage5Pipeline

    ml_filter = None
    if getattr(args, "ml_model", None):
        from arven.ml_runs import load_meta_filter

        ml_filter = load_meta_filter(cfg, args.ml_model)
    elif getattr(args, "random_filter_rate", None) is not None:
        from arven.ml.filter import RandomFilter

        ml_filter = RandomFilter(args.random_filter_rate, seed=cfg.project.random_seed)
    return Stage5Pipeline(
        load_regime_config(args.config_dir), load_strategies_config(args.config_dir),
        load_risk_config(args.config_dir), bt, ml_filter=ml_filter,
        macro_events=load_macro_events(args.config_dir),
    )


def cmd_paper_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.core.backtest_config import load_backtest_config
    from arven.paper.runs import run_paper_tick

    bt, fcfg = load_backtest_config(args.config_dir), load_features_config(args.config_dir)
    pipeline = _build_pipeline(cfg, args, bt)
    outcome = run_paper_tick(cfg, fcfg, bt, pipeline)
    rs = outcome.rest_summary
    print(f"REST tail: klines +{rs.klines_written} (of {rs.klines_fetched} fetched)  "
          f"funding +{rs.funding_written} (of {rs.funding_fetched} fetched)  pages={rs.pages}")
    for err in rs.errors:
        print(f"  REST ERROR {err}")
    if outcome.window is None:
        print("forward_start has not arrived yet relative to now; nothing to decide")
        return 0 if rs.ok else 1
    print(f"forward window [{outcome.window.start_ms}, {outcome.window.end_ms})")
    if outcome.run is None:
        print("no new decision time since the last tick")
        return 0 if rs.ok else 1
    out = outcome.run
    print(f"run {out.run_id} -> {out.run_dir}")
    _print_metrics(out.metrics)
    print(f"  result_hash {out.result_hash}   git_dirty={out.manifest['git_dirty']}")
    print("Simulated fills on real market data, same cost/execution model as `backtest run` - not a real "
          "exchange account, not evidence of profitability (CLAUDE.md rule 6).")
    return 0 if rs.ok else 1


def cmd_web(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Phase 8: serve the read-only HTTP API (and the built web app, if present) on localhost."""
    from pathlib import Path

    import uvicorn

    from arven.live.instance import acquire, open_log
    from arven.web.app import create_app

    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        print(f"refusing to bind to {args.host}: ARVEN's API is local-only by default (pass --allow-remote to override).")
        return 2
    if args.log_file:  # windowless (pythonw) run: output to a file, without the per-request access lines
        sys.stdout = sys.stderr = open_log(Path(args.log_file))
    # Windows lets a second socket bind the same port, so a watchdog restart is kept single by an OS lock instead.
    lock = acquire(cfg.data.data_dir / "live" / f"web_{args.port}.lock")
    if lock is None:
        print(f"another `arven web` is already serving port {args.port} - exiting.", flush=True)
        return 0
    print(f"ARVEN web: http://{args.host}:{args.port}  (API docs at /api/docs; read-only, no order endpoints)", flush=True)
    try:
        uvicorn.run(create_app(cfg, args.config_dir), host=args.host, port=args.port, log_level="info", access_log=not args.log_file)
    finally:
        lock.close()
    return 0


def _config_dir(args: argparse.Namespace):
    from pathlib import Path

    from arven.core.config import DEFAULT_CONFIG_DIR

    return Path(args.config_dir) if args.config_dir else DEFAULT_CONFIG_DIR


def cmd_backup(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Zip the forward signal record, runtime state and config (and, with --with-db, the DuckDB file) into data/backups."""
    from arven.core.time import utc_now
    from arven.live.backup import make_backup

    res = make_backup(cfg.data.data_dir, _config_dir(args), utc_now(), keep=args.keep,
                      database_path=cfg.data.database_path if args.with_db else None)
    print(f"backup: {res.path}  ({res.files} files, {res.bytes_in / 1e6:.1f} MB before compression, "
          f"{res.path.stat().st_size / 1e6:.1f} MB zipped, database {'included' if res.database_included else 'not included'})")
    for old in res.removed:
        print(f"  removed old backup {old.name}")
    return 0


def cmd_live_tick(cfg: AppConfig, args: argparse.Namespace) -> int:
    """One pass of the live signal loop (every enabled strategy in config/live.yaml); see ``arven.live.service``."""
    from arven.core.live_config import load_live_config
    from arven.core.telegram_config import allowed_chat_ids
    from arven.core.time import from_ms
    from arven.live.service import run_live_tick

    live = load_live_config(args.config_dir)
    if cfg.instrument is not None:  # `arven --instrument XAUUSDT live tick`: that market's entry in config/live.yaml
        market = next((m for m in live.markets if m.instrument == cfg.instrument), None)
        if market is None:
            raise SystemExit(f"config/live.yaml has no market {cfg.instrument}")
        live = live.for_market(market)
    chat_ids = frozenset() if args.no_telegram or not live.telegram.enabled else allowed_chat_ids()
    out = run_live_tick(cfg, load_features_config(args.config_dir), live, _config_dir(args), chat_ids=chat_ids)
    rs = out.rest
    if rs is not None:
        print(f"REST tail: klines +{rs.klines_written}  funding +{rs.funding_written}  open interest +{rs.oi_written}  pages={rs.pages}")
        for err in rs.errors:
            print(f"  REST ERROR {err}")
    print(f"status: {out.status}" + (f" ({out.detail})" if out.detail else ""))
    if out.through_ms is not None:
        print(f"evaluated through the 15m close {from_ms(out.through_ms).isoformat()}  (newest 1m bar {from_ms(out.last_1m_ms).isoformat()})")
    for sid, st in out.strategies.items():
        line = f"  {sid}: new signals {len(st.new_signals)}, new updates {st.new_updates}"
        if out.summary:
            sm = out.summary["strategies"][sid]
            line += f" | total {sm['signals']} (closed {sm['closed']}, open {sm['open']}, pending {sm['pending']}, cancelled {sm['cancelled']}), net {sm['total_r']:+.2f} R"
        print(line + (f"  ERROR {st.error}" if st.error else ""))
        for s in st.new_signals:
            print(f"    {from_ms(s.event_time_ms).isoformat()} {'LONG' if s.side == 1 else 'SHORT'} {s.entry_type} {s.entry_reference:.2f} stop {s.stop:.2f}")
    if out.queued_alerts:
        print(f"Telegram alerts queued: {out.queued_alerts}  (pictures drawn: {out.charts})")
    for err in out.chart_errors:
        print(f"  picture not drawn, the alert goes as text: {err}")
    print("Paper signals on live data - not orders, not evidence of profitability (CLAUDE.md rules 6/12).")
    return 0 if out.status in ("ok", "not_started") else 1


def cmd_paper_strategies(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Kept for the existing scheduled task: the forward evaluation is now one pass of the live loop (every enabled strategy)."""
    return cmd_live_tick(cfg, args)


def cmd_live_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    """The always-on live signal process (see ``arven.live.loop``). Ctrl+C or the --stop-file stop it between polls."""
    import asyncio
    from pathlib import Path

    from arven.core.backtest_config import load_backtest_config
    from arven.core.live_config import load_live_config
    from arven.core.telegram_config import allowed_chat_ids, load_telegram_config
    from arven.live.app import build_deps, telegram_token_configured
    from arven.live.instance import acquire, open_log
    from arven.live.loop import live_dir, run_live_forever
    from arven.paper.runtime import run_once

    if args.log_file:  # e.g. under pythonw (no console): everything printed goes to this file instead
        sys.stdout = sys.stderr = open_log(Path(args.log_file))
    lock = acquire(live_dir(cfg) / "live.lock")
    if lock is None:
        print("another `arven live run` is already running (data/live/live.lock) - exiting.", flush=True)
        return 0
    live = load_live_config(args.config_dir)
    if args.poll_seconds is not None:
        live = live.model_copy(update={"poll_seconds": args.poll_seconds})
    fcfg, tcfg = load_features_config(args.config_dir), load_telegram_config(args.config_dir)
    chat_ids = frozenset() if args.no_telegram else allowed_chat_ids()
    bt = load_backtest_config(args.config_dir)
    legacy = (lambda now: run_once(cfg, fcfg, bt, lambda: _build_pipeline(cfg, args, bt), now=now)) if live.run_legacy_paper else None
    markets = {m.instrument: (m, load_config(args.config_dir, instrument=m.instrument)) for m in live.enabled_markets()}

    def market_legacy(m_app: AppConfig):
        return lambda now: run_once(m_app, fcfg, bt, lambda: _build_pipeline(m_app, args, bt), now=now)

    market_legacy_ticks = {name: market_legacy(a) for name, (m, a) in markets.items() if m.run_legacy_paper}
    deps = build_deps(cfg, fcfg, live, _config_dir(args), tcfg, chat_ids, legacy_tick=legacy, markets=markets,
                      market_legacy_ticks=market_legacy_ticks)
    stop_file = Path(args.stop_file) if args.stop_file else None
    if stop_file is not None and stop_file.exists():  # a stop request stays in force (the watchdog would restart us)
        print(f"stop file {stop_file} exists - not starting. Delete it to let the live process run.", flush=True)
        lock.close()
        return 0

    async def main() -> None:
        stop_event = asyncio.Event()

        async def watch() -> None:
            while not stop_event.is_set():
                if stop_file is not None and stop_file.exists():
                    print(f"stop file {stop_file} found - stopping.", flush=True)
                    stop_event.set()
                    return
                await asyncio.sleep(1.0)

        watcher = asyncio.create_task(watch())
        try:
            await run_live_forever(cfg, live, deps, stop_event=stop_event)
        finally:
            watcher.cancel()

    enabled = ", ".join(s.id for s in live.enabled()) + "".join(
        f"; {m.title or m.instrument}: " + ", ".join(s.id for s in m.strategies if s.enabled) for m, _ in markets.values())
    tg = ("off" if not live.telegram.enabled else "no chats configured (TELEGRAM_CHAT_IDS)" if not chat_ids else
          f"{len(chat_ids)} chat(s), {'DRY RUN (config/telegram.yaml)' if tcfg.dry_run else 'sending'}, "
          f"token {'set' if telegram_token_configured() else 'MISSING'}")
    print(f"ARVEN live signals: strategies [{enabled}], poll every {live.poll_seconds:g}s, Telegram: {tg}.\n"
          f"Heartbeat {live_dir(cfg) / 'heartbeat.json'}, log {live_dir(cfg) / 'live.jsonl'}. Ctrl+C to stop"
          + (f", or create {stop_file}." if stop_file else "."), flush=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("stopped (Ctrl+C).")
    finally:
        lock.close()
    return 0


def cmd_live_heartbeat(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.core.live_config import load_live_config
    from arven.core.time import from_ms, to_ms, utc_now
    from arven.live.loop import live_dir
    from arven.paper.runtime import is_stale, read_heartbeat

    live = load_live_config(args.config_dir)
    path = live_dir(cfg) / "heartbeat.json"
    hb = read_heartbeat(path)
    if hb is None:
        print(f"no heartbeat at {path} - `arven live run` has never run")
        return 1
    now_ms = to_ms(utc_now())
    stale = is_stale(hb, now_ms, max_age_ms=int(max(3 * live.poll_seconds, 60) * 1000) + 600_000)  # a tick can take minutes
    last = from_ms(hb["last_tick_ms"]).isoformat() if hb["last_tick_ms"] else "never"
    print(f"status={hb['status']}  checked {(now_ms - hb['checked_at_ms']) / 1000:.0f}s ago  last tick {last}")
    if hb["detail"]:
        print(f"  detail: {hb['detail']}")
    if stale:
        print("STALE: the live process has not checked in recently - it may have stopped.")
    return 1 if stale or hb["status"] == "error" else 0


def cmd_live_status(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.core.live_config import load_live_config
    from arven.core.time import from_ms
    from arven.paper.runs import paper_dir
    from arven.web.service import read_json

    live = load_live_config(args.config_dir)
    sections = [(cfg.market.symbol, cfg, live.strategies)] + [
        (m.title or m.instrument, load_config(args.config_dir, instrument=m.instrument), m.strategies) for m in live.markets if m.enabled]
    for title, app_cfg, strategies in sections:
        print(f"{title}:")
        for s in strategies:
            print(f"  {'ON ' if s.enabled else 'off'} {s.id:22s} kind={s.kind:20s} version={s.version}")
        summary = read_json(paper_dir(app_cfg) / "strategies_summary.json")
        if not summary:
            print("  no live summary yet; run `arven live tick`")
            continue
        print(f"  last tick {summary['generated_at']}  data through {from_ms(summary['data_through_ms']).isoformat()}  "
              f"status {summary.get('status', 'ok')}")
        for sid, st in summary["strategies"].items():
            print(f"    {sid}: signals {st['signals']}, closed {st['closed']}, open {st['open']}, pending {st.get('pending', 0)}, "
                  f"cancelled {st.get('cancelled', 0)}, net {st['total_r']:+.2f} R")
    return cmd_live_heartbeat(cfg, args) if (cfg.data.data_dir / "live" / "heartbeat.json").exists() else 0


def cmd_paper_runtime(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Phase 5 (ARVEN_MASTER_PROMPT.md): one long-running process instead of an externally-scheduled
    `paper run` per tick. Ctrl+C stops it before/after the current tick (every tick is already a complete,
    atomic unit - `run_paper_tick` writes nothing partial - so this is safe even though it is not a
    mid-tick-graceful signal handler; Windows' asyncio loop does not support those anyway). A --stop-file
    is the portable alternative for stopping it from a script or Task Scheduler action."""
    import asyncio
    from pathlib import Path

    from arven.core.backtest_config import load_backtest_config
    from arven.paper.runtime import run_forever

    bt, fcfg = load_backtest_config(args.config_dir), load_features_config(args.config_dir)
    root = cfg.data.data_dir / "paper"
    heartbeat_path, log_path = root / "heartbeat.json", root / "runtime.jsonl"
    stop_file = Path(args.stop_file) if args.stop_file else None

    async def main() -> None:
        stop_event = asyncio.Event()

        async def watch_stop_file() -> None:
            while not stop_event.is_set():
                if stop_file is not None and stop_file.exists():
                    print(f"stop file {stop_file} found - stopping (graceful shutdown).")
                    stop_event.set()
                    return
                await asyncio.sleep(1.0)

        watcher = asyncio.create_task(watch_stop_file()) if stop_file is not None else None
        try:
            await run_forever(
                cfg, fcfg, bt, lambda: _build_pipeline(cfg, args, bt),
                heartbeat_path=heartbeat_path, log_path=log_path, poll_seconds=args.poll_seconds,
                stop_event=stop_event,
            )
        finally:
            if watcher is not None:
                watcher.cancel()

    print(f"ARVEN paper runtime starting: polling every {args.poll_seconds}s. Heartbeat: {heartbeat_path}  "
          f"Log: {log_path}  Ctrl+C to stop" + (f", or create {stop_file}." if stop_file else "."))
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("stopped (Ctrl+C).")
    return 0


def cmd_paper_heartbeat(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.core.time import from_ms, to_ms, utc_now
    from arven.paper.runtime import is_stale, read_heartbeat

    path = cfg.data.data_dir / "paper" / "heartbeat.json"
    hb = read_heartbeat(path)
    if hb is None:
        print(f"no heartbeat file at {path} - the runtime has never ticked, or was never started")
        return 1
    now_ms = to_ms(utc_now())
    age_s = (now_ms - hb["checked_at_ms"]) / 1000
    stale = is_stale(hb, now_ms, max_age_ms=120_000)  # 2x the default --poll-seconds, a reasonable default
    print(f"status={hb['status']}  checked {age_s:.0f}s ago  last_tick={from_ms(hb['last_tick_ms']).isoformat() if hb['last_tick_ms'] else 'never'}")
    if hb["detail"]:
        print(f"  detail: {hb['detail']}")
    if stale:
        print("STALE: the runtime has not checked in recently - it may have crashed or been stopped.")
    return 1 if stale or hb["status"] == "error" else 0


def cmd_paper_show(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.paper.runs import paper_dir

    manifest = json.loads((paper_dir(cfg) / args.run / "run.json").read_text(encoding="utf-8"))
    _print_metrics(manifest["metrics"])
    print(f"  result_hash {manifest['result_hash']}   window [{manifest['window_start_ms']}, {manifest['window_end_ms']})")
    return 0


def cmd_paper_status(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.core.time import from_ms
    from arven.paper.runs import latest_forward_window_end_ms, paper_dir

    with open_readonly(cfg.data.database_path) as con:
        last_1m = con.execute("SELECT max(open_time_ms) FROM ohlcv_1m WHERE symbol = ?", [cfg.market.symbol]).fetchone()[0]
        last_funding = con.execute("SELECT max(funding_time_ms) FROM funding_rates WHERE symbol = ?", [cfg.market.symbol]).fetchone()[0]
    print(f"forward_start {cfg.splits.forward_start.isoformat()}")
    print(f"latest usable decision time (now): {from_ms(latest_forward_window_end_ms(cfg) - 3_600_000).isoformat()}")
    print(f"latest stored 1m bar: {from_ms(last_1m).isoformat() if last_1m is not None else 'none'}")
    print(f"latest stored funding: {from_ms(last_funding).isoformat() if last_funding is not None else 'none'}")
    index = paper_dir(cfg) / "runs.jsonl"
    if not index.exists():
        print("no paper runs yet; run `arven paper run`")
        return 0
    last_line = index.read_text(encoding="utf-8").strip().splitlines()[-1]
    entry = json.loads(last_line)
    print(f"latest paper run: {entry['run_id']} ({entry['created_at']})  result_hash={entry['result_hash']}")
    return 0


def cmd_news_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.core.news_config import load_news_config
    from arven.news.runs import run_news_tick

    news_cfg = load_news_config(args.config_dir)
    with connect(cfg.data.database_path) as con:
        summary = run_news_tick(cfg, news_cfg, con)
    print(f"news tick: fetched={summary.items_fetched} new={summary.items_new} "
          f"structured={summary.items_structured} parse_failed={summary.items_parse_failed} "
          f"tokens(in/out)={summary.input_tokens}/{summary.output_tokens}")
    for err in summary.errors:
        print(f"  ERROR {err}")
    print("Structuring only, per CLAUDE.md rule 9 - not wired into any trading decision (see docs/current_state.md's \"Stage 9b\" section).")
    return 0 if summary.ok else 1


def cmd_news_show(cfg: AppConfig, args: argparse.Namespace) -> int:
    with open_readonly(cfg.data.database_path) as con:
        rows = con.execute(
            """
            SELECT n.published_at_ms, n.source, n.title, e.event_type, e.asset_relevance, e.direction_bias,
                   e.severity, e.confidence, e.summary, e.parse_error
            FROM news_items n LEFT JOIN news_events e ON e.news_id = n.news_id
            ORDER BY n.published_at_ms DESC LIMIT ?
            """,
            [args.limit],
        ).fetchall()
    for published_ms, source, title, event_type, relevance, bias, severity, confidence, summary, parse_error in rows:
        from arven.core.time import from_ms

        print(f"[{from_ms(published_ms).isoformat()}] ({source}) {title}")
        if parse_error:
            print(f"    UNSTRUCTURED: {parse_error}")
        elif event_type is not None:
            print(f"    {event_type} / {relevance} / {bias}  severity={severity:.2f} confidence={confidence:.2f}")
            print(f"    {summary}")
        else:
            print("    (not yet structured)")
    return 0


def cmd_telegram_send(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.core.telegram_config import load_telegram_config
    from arven.telegram.outbox import charts_dir
    from arven.telegram.runs import run_telegram_send_tick

    tcfg = load_telegram_config(args.config_dir)
    with connect(cfg.data.database_path) as con:
        summary = run_telegram_send_tick(con, tcfg, charts_root=charts_dir(cfg.data.data_dir))
    print(f"sent={summary.sent} (as pictures {summary.photos})  skipped_paused={summary.skipped_paused}  failed={summary.failed}  dry_run={summary.dry_run}")
    for note in summary.photo_fallbacks:
        print(f"  picture not sent, text instead: {note}")
    for err in summary.errors:
        print(f"  ERROR {err}")
    if tcfg.dry_run:
        print("dry_run=true (config/telegram.yaml) - nothing was actually sent to Telegram.")
    return 0 if summary.ok else 1


def cmd_telegram_commands(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.core.telegram_config import allowed_chat_ids, load_telegram_config
    from arven.telegram.runs import read_update_cursor, run_telegram_commands_tick, write_update_cursor

    tcfg = load_telegram_config(args.config_dir)
    allowed = allowed_chat_ids()
    if not allowed:
        print("TELEGRAM_CHAT_IDS is not set (environment/.env) - no chat is allow-listed; every incoming "
              "message will get the 'not authorized' reply.")
    root = cfg.data.data_dir / "telegram"
    cursor_path = root / "commands_cursor.json"
    last_id = read_update_cursor(cursor_path)
    with connect(cfg.data.database_path) as con:
        summary, new_id = run_telegram_commands_tick(
            con, tcfg, cfg.data.data_dir / "signals", cfg.data.data_dir / "paper" / "heartbeat.json",
            last_update_id=last_id, allowed_chats=allowed,
        )
    write_update_cursor(cursor_path, new_id)
    print(f"updates_seen={summary.updates_seen}  replied={summary.replied}  unauthorized={summary.unauthorized}")
    for err in summary.errors:
        print(f"  ERROR {err}")
    return 0 if summary.ok else 1


def cmd_telegram_test(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Sends one real message to every allow-listed chat - the "owner supplies token for a live test"
    step of the Phase 6 gate. Ignores config/telegram.yaml's dry_run (a deliberate smoke test, not a tick)."""
    from arven.core.telegram_config import allowed_chat_ids
    from arven.telegram.client import TelegramConfigError, TelegramRequestError, send_message

    allowed = allowed_chat_ids()
    if not allowed:
        print("TELEGRAM_CHAT_IDS is not set (environment/.env) - nothing to send a test message to.")
        return 1
    ok = True
    for chat_id in allowed:
        try:
            sent = send_message(chat_id, "ARVEN test message - if you see this, TELEGRAM_BOT_TOKEN and this chat id both work.")
            print(f"sent to {chat_id}: message_id={sent.message_id}")
        except TelegramConfigError as exc:
            print(f"not configured: {exc}")
            return 1
        except TelegramRequestError as exc:
            print(f"send to {chat_id} failed: {exc}")
            ok = False
    return 0 if ok else 1


def cmd_explain(cfg: AppConfig, args: argparse.Namespace) -> int:
    import json

    from arven.core.explain_config import load_explain_config
    from arven.llm.explain import explain_decision

    ecfg = load_explain_config(args.config_dir)
    run_dir = cfg.data.data_dir / "paper" / args.run
    decisions_path = run_dir / "decisions.jsonl"
    if not decisions_path.exists():
        print(f"no decisions.jsonl for run {args.run} (run `arven paper show {args.run}` to check the run exists)")
        return 1
    lines = decisions_path.read_text(encoding="utf-8").strip().splitlines()
    index = args.index if args.index is not None else len(lines) - 1
    if not (0 <= index < len(lines)):
        print(f"index {index} out of range (0..{len(lines) - 1})")
        return 1
    summary = json.loads(lines[index])
    print(f"Decision at t={summary['t_ms']} (index {index} of {len(lines)}):")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print()
    print("Explanation:")
    print(explain_decision(summary, model=ecfg.llm_model, max_tokens=ecfg.max_tokens_explain))
    return 0


def cmd_ask(cfg: AppConfig, args: argparse.Namespace) -> int:
    from arven.core.explain_config import load_explain_config
    from arven.llm.context import build_context
    from arven.llm.qa import answer_question

    ecfg = load_explain_config(args.config_dir)
    context = build_context(cfg, n_decisions=ecfg.n_decisions_context, n_news=ecfg.n_news_context)
    answer = answer_question(args.question, context, model=ecfg.llm_model, max_tokens=ecfg.max_tokens_qa)
    print(answer)
    print()
    print("Research tool only - not financial advice (CLAUDE.md rule 6/9).")
    return 0


def cmd_dashboard(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Launch the Stage 10 Streamlit dashboard as a subprocess (there is no application code to run here
    directly - ``streamlit run`` is its own process model, same relationship as e.g. ``pytest``)."""
    import subprocess
    from pathlib import Path

    app_path = Path(__file__).resolve().parent / "dashboard" / "app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.headless", "true" if args.headless else "false"]
    return subprocess.run(cmd, check=False).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arven", description="ARVEN data pipeline (research only, no execution)")
    parser.add_argument("--config-dir", default=None, help="configuration directory (default: <project>/config)")
    parser.add_argument("--instrument", default=None,
                        help="instrument overlay from config/instruments (e.g. XAUUSD, XAUUSDT); default: BTCUSDT")
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

    p = sub.add_parser("duka", help="Dukascopy 1m history for a spot instrument (needs --instrument, e.g. XAUUSD)")
    dsub = p.add_subparsers(dest="duka_command", required=True)
    with_range(dsub.add_parser("download", help="fetch BID+ASK .bi5 files into data/raw (no database access)")).set_defaults(func=cmd_duka_download)
    q = with_range(dsub.add_parser("ingest", help="decode downloaded days into ohlcv_1m (mid price, session minutes only)"))
    q.add_argument("--refresh", action="store_true", help="re-ingest days even if unchanged")
    q.set_defaults(func=cmd_duka_ingest)
    q = with_range(dsub.add_parser("closures", help="list zero-volume runs inside regular session hours (holiday evidence)"))
    q.add_argument("--min-minutes", type=int, default=30)
    q.set_defaults(func=cmd_duka_closures)
    sub.add_parser("export", help="export DuckDB tables to Parquet").set_defaults(func=cmd_export)
    sub.add_parser("status", help="show stored data summary").set_defaults(func=cmd_status)

    p = sub.add_parser("features", help="build and inspect the causal feature cache (Stage 3)")
    fsub = p.add_subparsers(dest="features_command", required=True)
    fsub.add_parser("build", help="compute features on the 1h grid, write the Parquet cache").set_defaults(func=cmd_features_build)
    fsub.add_parser("check", help="verify the cache and print development-period stats").set_defaults(func=cmd_features_check)
    fsub.add_parser("status", help="show the cache manifest").set_defaults(func=cmd_features_status)

    p = sub.add_parser("backtest", help="deterministic 1m backtester and baselines (Stage 4)")
    bsub = p.add_subparsers(dest="backtest_command", required=True)

    def with_window(q: argparse.ArgumentParser) -> argparse.ArgumentParser:
        q.add_argument("--period", choices=["development", "validation", "test"], default="development")
        q.add_argument("--start", help="UTC start date inside the period (default: period start)")
        q.add_argument("--end", help="UTC end date inside the period (default: period end)")
        q.add_argument("--stress", action="store_true", help="multiply slippage by costs.slippage.stress_multiplier")
        q.add_argument("--allow-sealed", action="store_true", help="acknowledge access to the SEALED test period (logged)")
        q.add_argument("--reason", help="required with --allow-sealed; recorded permanently in the sealed-access log")
        return q

    q = with_window(bsub.add_parser("run", help="run one baseline provider on a period"))
    q.add_argument("--provider", choices=["no_trade", "buy_and_hold", "random_entry", "pipeline"], required=True)
    q.add_argument("--seed-index", type=int, default=0, help="random_entry spawn index")
    q.add_argument("--ml-model", help="Stage 6 model id (data/models/<id>): if given, --provider pipeline runs with this MetaFilter enabled")
    q.add_argument("--random-filter-rate", type=float, help="control (D20): --provider pipeline vetoes this fraction of candidates uniformly at random instead of using a model")
    q.set_defaults(func=cmd_backtest_run)
    q = with_window(bsub.add_parser("baselines", help="no-trade, buy-and-hold and the random-entry distribution, side by side"))
    q.add_argument("--seeds", type=int, default=None, help="override baselines.random_entry.n_seeds")
    q.set_defaults(func=cmd_backtest_baselines)
    q = bsub.add_parser("verify", help="recompute a run's hashes from its files")
    q.add_argument("run")
    q.set_defaults(func=cmd_backtest_verify)
    q = bsub.add_parser("show", help="print a stored run's metrics")
    q.add_argument("run")
    q.set_defaults(func=cmd_backtest_show)

    p = sub.add_parser("ml", help="Stage 6 ML meta-filter: train, verify and inspect models")
    msub = p.add_subparsers(dest="ml_command", required=True)
    q = msub.add_parser("train", help="build the development+validation dataset, walk-forward select hyperparameters, fit and calibrate the final model")
    q.add_argument("--model-family", choices=["logistic", "lightgbm"], required=True)
    q.add_argument("--shuffle-labels-seed", type=int, help="shuffled-label control (D20): permute labels with this seed before training")
    q.set_defaults(func=cmd_ml_train)
    q = msub.add_parser("verify", help="recompute a model artifact's hash from its file")
    q.add_argument("model")
    q.set_defaults(func=cmd_ml_verify)
    q = msub.add_parser("show", help="print a stored model's manifest")
    q.add_argument("model")
    q.set_defaults(func=cmd_ml_show)

    p = sub.add_parser("wfo", help="Stage 7: walk-forward robustness evaluation over development+validation only")
    wsub = p.add_subparsers(dest="wfo_command", required=True)
    q = wsub.add_parser("run", help="run the full walk-forward schedule (both model families, baseline + ml + shuffled + random controls per window)")
    q.set_defaults(func=cmd_wfo_run)
    q = wsub.add_parser("show", help="print a stored walk-forward report")
    q.add_argument("run")
    q.set_defaults(func=cmd_wfo_show)

    q = sub.add_parser("backup", help="zip the signal record, runtime state and config into data/backups (keeps the newest N)")
    q.add_argument("--with-db", action="store_true", help="also copy the DuckDB database (consistent: taken under a read lock)")
    q.add_argument("--keep", type=int, default=10, help="how many backups to keep (default 10)")
    q.set_defaults(func=cmd_backup)

    q = sub.add_parser("web", help="Phase 8: local read-only HTTP API + web app")
    q.add_argument("--host", default="127.0.0.1")
    q.add_argument("--port", type=int, default=8000)
    q.add_argument("--allow-remote", action="store_true", help="allow binding to a non-local address (not recommended)")
    q.add_argument("--log-file", help="append all output to this file, without access lines (for a windowless pythonw run)")
    q.set_defaults(func=cmd_web)
    p = sub.add_parser("paper", help="Stage 8: the paper-signal loop (forward-only, simulated fills on live data)")
    psub = p.add_subparsers(dest="paper_command", required=True)
    q = psub.add_parser("run", help="REST-update market data, then decide+paper-trade every new forward decision time since the last run")
    q.add_argument("--ml-model", help="Stage 6 model id (data/models/<id>): run the pipeline with this MetaFilter enabled")
    q.add_argument("--random-filter-rate", type=float, help="control (D20): veto this fraction of candidates uniformly at random instead of using a model")
    q.set_defaults(func=cmd_paper_run)
    q = psub.add_parser("show", help="print a stored paper run's metrics")
    q.add_argument("run")
    q.set_defaults(func=cmd_paper_show)
    psub.add_parser("status", help="latest ingested data and latest paper run").set_defaults(func=cmd_paper_status)
    q = psub.add_parser("strategies", help="same as `arven live tick` (kept for the existing scheduled task)")
    q.add_argument("--no-telegram", action="store_true", help="do not queue Telegram alerts for new signals")
    q.set_defaults(func=cmd_paper_strategies)
    q = psub.add_parser("runtime", help="Phase 5: one long-running process polling for new decision times, instead of an externally-scheduled `paper run`")
    q.add_argument("--poll-seconds", type=float, default=15.0, help="how often to check for a new decision time (default 15s)")
    q.add_argument("--stop-file", help="create this file to request a graceful stop (checked once a second); Ctrl+C also works")
    q.add_argument("--ml-model", help="Stage 6 model id (data/models/<id>): run the pipeline with this MetaFilter enabled")
    q.add_argument("--random-filter-rate", type=float, help="control (D20): veto this fraction of candidates uniformly at random instead of using a model")
    q.set_defaults(func=cmd_paper_runtime)
    psub.add_parser("heartbeat", help="print the always-on runtime's last heartbeat (status/age); non-zero exit if stale or missing").set_defaults(func=cmd_paper_heartbeat)

    p = sub.add_parser("live", help="live signals: every enabled strategy (config/live.yaml) on fresh Binance data, Telegram alerts")
    lsub = p.add_subparsers(dest="live_command", required=True)
    q = lsub.add_parser("run", help="the always-on process: new 15m closes -> strategies -> signal store -> Telegram; heartbeat")
    q.add_argument("--poll-seconds", type=float, default=None, help="override poll_seconds from config/live.yaml")
    q.add_argument("--stop-file", help="create this file to stop the process gracefully (checked once a second)")
    q.add_argument("--no-telegram", action="store_true", help="do not queue Telegram alerts")
    q.add_argument("--log-file", help="append all output to this file (for a windowless pythonw run)")
    q.set_defaults(func=cmd_live_run)
    q = lsub.add_parser("tick", help="one pass: update data, scan every enabled strategy, track stored signals, queue alerts")
    q.add_argument("--no-telegram", action="store_true", help="do not queue Telegram alerts")
    q.set_defaults(func=cmd_live_tick)
    lsub.add_parser("status", help="enabled strategies, the last summary and the heartbeat").set_defaults(func=cmd_live_status)
    lsub.add_parser("heartbeat", help="the live process's heartbeat; non-zero exit if stale, missing or in error").set_defaults(func=cmd_live_heartbeat)

    p = sub.add_parser("news", help="Stage 9b: RSS ingestion + LLM structuring into a fixed schema (never a trading decision)")
    nsub = p.add_subparsers(dest="news_command", required=True)
    nsub.add_parser("run", help="fetch new RSS items, structure up to max_items_per_tick of them via the LLM").set_defaults(func=cmd_news_run)
    q = nsub.add_parser("show", help="print recent news items and their structured events, if any")
    q.add_argument("--limit", type=int, default=20)
    q.set_defaults(func=cmd_news_show)

    p = sub.add_parser("telegram", help="Phase 6: Telegram alerts and bot commands (never a real order)")
    tsub = p.add_subparsers(dest="telegram_command", required=True)
    tsub.add_parser("send", help="drain the outbox - send (or, in dry_run, just mark as sent) every pending alert").set_defaults(func=cmd_telegram_send)
    tsub.add_parser("commands", help="poll getUpdates once, reply to recognised commands from allow-listed chats").set_defaults(func=cmd_telegram_commands)
    tsub.add_parser("test", help="send one real test message to every allow-listed chat (ignores dry_run)").set_defaults(func=cmd_telegram_test)

    q = sub.add_parser("explain", help="Stage 10: plain-language explanation of one decision from a paper run (never a new decision)")
    q.add_argument("run", help="a paper run id (see `arven paper status`)")
    q.add_argument("--index", type=int, default=None, help="which decision in the run (default: the last one)")
    q.set_defaults(func=cmd_explain)

    q = sub.add_parser("ask", help="Stage 10: ask a question about stored decisions/results/news (answers only from stored data, never new trading advice)")
    q.add_argument("question")
    q.set_defaults(func=cmd_ask)

    q = sub.add_parser("dashboard", help="Stage 10: launch the read-only Streamlit dashboard (reports, signals, news, Q&A)")
    q.add_argument("--headless", action="store_true", help="do not try to open a browser window automatically")
    q.set_defaults(func=cmd_dashboard)
    return parser


# Commands that already work per instrument (`--instrument`). Every other command still assumes the default
# BTCUSDT configuration (shared output directories such as the feature cache), so it refuses an overlay instead of
# silently mixing markets.
_INSTRUMENT_COMMANDS = frozenset({"ingest", "resample", "crosscheck", "quality", "status", "duka", "features", "backtest", "live"})


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.instrument is not None and args.command not in _INSTRUMENT_COMMANDS:
        raise SystemExit(f"`{args.command}` does not support --instrument yet (supported: {sorted(_INSTRUMENT_COMMANDS)})")
    cfg = load_config(args.config_dir, instrument=args.instrument)
    if args.command == "duka" and cfg.market.exchange != "dukascopy":
        raise SystemExit("`duka` needs a Dukascopy instrument, e.g. --instrument XAUUSD")
    if args.command == "live" and args.instrument is not None and args.live_command != "tick":
        raise SystemExit("`live run/status/heartbeat` cover every market of config/live.yaml; only `live tick` takes --instrument")
    if args.command in ("ingest", "crosscheck") and cfg.market.exchange != "binance":
        raise SystemExit(f"`{args.command}` reads Binance bulk files; use `duka download/ingest` for {cfg.market.symbol}")
    return args.func(cfg, args)


if __name__ == "__main__":
    sys.exit(main())

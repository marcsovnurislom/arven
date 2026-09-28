"""Composition root for backtest runs: load data through an ``AllowedWindow``, run, write artifacts.

All I/O of Stage 4 lives here (and in ``arven.cli``); the ``arven.backtest`` package stays pure.

Artifacts of a run (``<data_dir>/backtests/<run_id>/``): ``run.json`` (manifest, metrics, hashes), ``meta.json``,
``orders.csv``, ``fills.csv``, ``funding.csv``, ``trades.csv``, ``equity.csv``. ``runs.jsonl`` (append-only) indexes
every run; ``sealed_test_log.jsonl`` records every access to the sealed test period.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from arven.backtest.baselines import BuyAndHold, NoTrade, RandomEntry
from arven.backtest.engine import Backtester, BacktestResult, decision_grid
from arven.backtest.errors import ConfigurationError, DataError
from arven.backtest.marketdata import MarketData, align_funding
from arven.backtest.metrics import compute_metrics, summarize_distribution
from arven.backtest.provider import FeatureData, SignalProvider
from arven.backtest.report import TABLE_ORDER, combine_hashes, fmt_value, result_tables, table_hashes
from arven.backtest.types import Trade
from arven.core.backtest_config import BacktestConfig
from arven.core.config import AppConfig
from arven.core.features_config import FeaturesConfig
from arven.core.splitguard import AllowedWindow, SplitGuard
from arven.core.time import utc_now
from arven.data.reader import load_1m_bars, load_funding_window, open_readonly
from arven.data.storage import feature_store
from arven.features.registry import build_registry, definition_hash

HOUR_MS = 3_600_000
FILE_NAMES = {"meta": "meta.json", "orders": "orders.csv", "fills": "fills.csv", "funding": "funding.csv", "trades": "trades.csv", "equity": "equity.csv"}


def backtests_dir(app: AppConfig) -> Path:
    return app.data.data_dir / "backtests"


def sealed_log_path(app: AppConfig) -> Path:
    return backtests_dir(app) / "sealed_test_log.jsonl"


def make_guard(app: AppConfig) -> SplitGuard:
    return SplitGuard(app.splits, sealed_log_path(app))


def git_state() -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, None
    if commit.returncode != 0:
        return None, None
    return commit.stdout.strip() or None, bool(status.stdout.strip())


@dataclass(frozen=True, eq=False)
class LoadedInputs:
    market: MarketData
    features: FeatureData
    feature_manifest: dict[str, Any]
    data_ranges: list[dict[str, Any]]


def load_inputs(
    app: AppConfig, fcfg: FeaturesConfig, window: AllowedWindow, con: duckdb.DuckDBPyConnection | None = None
) -> LoadedInputs:
    """Read 1m bars, funding and Stage 3 feature rows for ``window`` only, and record what was read."""
    ranges: list[dict[str, Any]] = []
    own = con is None
    if con is None:
        con = open_readonly(app.data.database_path)
    try:
        bars = load_1m_bars(con, app.market.symbol, window, ranges)
        f_t, f_r = load_funding_window(con, app.market.symbol, window, ranges)
    finally:
        if own:
            con.close()
    interval_ms = app.costs.funding.default_interval_hours * HOUR_MS
    ft, fr = align_funding(f_t, f_r, window.start_ms, window.end_ms, interval_ms)
    market = MarketData(bars["time_ms"], bars["open"], bars["high"], bars["low"], bars["close"], window.start_ms, window.end_ms, ft, fr, interval_ms)

    directory = feature_store.cache_dir(app.data.data_dir, fcfg.version)
    manifest = feature_store.read_manifest(directory)
    if manifest["definition_hash"] != definition_hash(fcfg):
        raise ConfigurationError("feature cache is stale: definition hash differs from config/features.yaml (run `arven features build`)")
    specs = build_registry(fcfg)
    table = feature_store.read_window_parquet(directory / feature_store.PARQUET_NAME, manifest["feature_version"], specs, window.start_ms, window.end_ms)
    ranges.append({"dataset": "features", "start_ms": window.start_ms, "end_ms": window.end_ms})
    if list(table.columns) != [c["name"] for c in manifest["columns"]]:
        raise ConfigurationError("feature cache columns do not match its manifest")
    grid = decision_grid(window)
    if len(table.t_ms) != len(grid) or np.any(table.t_ms != grid):
        raise DataError("feature cache rows do not cover the window's decision grid")
    names = tuple(table.columns)
    values = np.column_stack([table.columns[n] for n in names]) if len(grid) else np.empty((0, len(names)))
    features = FeatureData(table.t_ms, names, values, manifest["first_ready_ms"])
    return LoadedInputs(market, features, manifest, ranges)


@dataclass(frozen=True, eq=False)
class RunOutcome:
    run_id: str
    run_dir: Path | None
    manifest: dict[str, Any]
    metrics: dict[str, Any]
    result: BacktestResult
    result_hash: str


def _new_run_id(root: Path, config_hash: str, dir_prefix: str = "") -> str:
    """A run id unique under ``root / f"{dir_prefix}{run_id}"`` (``dir_prefix`` lets callers that nest the run
    id inside a longer directory name, e.g. ``baselines-<id>``, check for collisions on the actual path)."""
    base = f"{utc_now():%Y%m%dT%H%M%SZ}-{config_hash[:8]}"
    run_id, k = base, 1
    while (root / f"{dir_prefix}{run_id}").exists():
        k += 1
        run_id = f"{base}-{k}"
    return run_id


def _manifest(
    app: AppConfig,
    cfg: BacktestConfig,
    fcfg: FeaturesConfig,
    window: AllowedWindow,
    provider: SignalProvider,
    inputs: LoadedInputs,
    result: BacktestResult,
    metrics: dict[str, Any],
    hashes: dict[str, str],
    rhash: str,
    run_id: str,
    stress: bool,
    extra: dict[str, Any] | None,
) -> dict[str, Any]:
    commit, dirty = git_state()
    fm = inputs.feature_manifest
    peak = None
    try:
        from arven.cli import _peak_working_set_mb

        peak = _peak_working_set_mb()
    except Exception:  # noqa: BLE001 - diagnostics only
        pass
    describe = provider.describe()
    for attr in ("placed", "skipped_not_ready"):
        if hasattr(provider, attr):
            describe[attr] = getattr(provider, attr)
    manifest = {
        "run_id": run_id,
        "created_at": utc_now().isoformat(),
        "git_commit": commit,
        "git_dirty": dirty,
        "feature_version": fm["feature_version"],
        "feature_definition_hash": fm["definition_hash"],
        "feature_content_hash": fm["data_sha256"],
        "feature_cache_source_fingerprint": fm["source_fingerprint"],
        "feature_cache_git_commit": fm.get("git_commit"),
        "market_data_fingerprint": inputs.market.fingerprint(),
        "app_config_hash": app.config_hash(),
        "features_config_hash": fcfg.config_hash(),
        "backtest_config_hash": cfg.config_hash(),
        "stress": stress,
        "period": window.period.value,
        "window_start_ms": window.start_ms,
        "window_end_ms": window.end_ms,
        "touched_test_set": window.sealed,
        "sealed_reason": window.sealed_reason,
        "data_ranges_read": inputs.data_ranges,
        "provider": describe,
        "provider_hash": hashlib.sha256(json.dumps(describe, sort_keys=True).encode()).hexdigest(),
        "random_seed": {k: describe[k] for k in ("base_seed", "spawn_index", "algorithm") if k in describe} or None,
        "table_hashes": hashes,
        "result_hash": rhash,
        "metrics": metrics,
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "duckdb": duckdb.__version__},
        "peak_working_set_mb": peak,
    }
    if extra:
        manifest.update(extra)
    return manifest


def write_run_files(run_dir: Path, tables: dict[str, str], manifest: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=False)
    for name in TABLE_ORDER:
        (run_dir / FILE_NAMES[name]).write_text(tables[name], encoding="utf-8", newline="")
    (run_dir / "run.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_run_index(app: AppConfig, manifest: dict[str, Any], run_dir: Path | None) -> None:
    path = backtests_dir(app) / "runs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "run_id": manifest["run_id"],
        "dir": None if run_dir is None else str(run_dir.relative_to(backtests_dir(app))),
        "provider": manifest["provider"].get("name"),
        "period": manifest["period"],
        "window_start_ms": manifest["window_start_ms"],
        "window_end_ms": manifest["window_end_ms"],
        "result_hash": manifest["result_hash"],
        "touched_test_set": manifest["touched_test_set"],
        "git_commit": manifest["git_commit"],
        "git_dirty": manifest["git_dirty"],
        "created_at": manifest["created_at"],
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def execute_run(
    app: AppConfig,
    cfg: BacktestConfig,
    fcfg: FeaturesConfig,
    window: AllowedWindow,
    provider: SignalProvider,
    inputs: LoadedInputs,
    *,
    stress: bool = False,
    out_dir: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> RunOutcome:
    """Run one backtest and (if ``out_dir`` is given, a directory root) write its artifacts and index entry."""
    result = Backtester(app, cfg, window, inputs.market, inputs.features, stress=stress).run(provider)
    metrics = compute_metrics(result, cfg)
    tables = result_tables(result)
    hashes = table_hashes(tables)
    rhash = combine_hashes(hashes)
    root = out_dir if out_dir is not None else backtests_dir(app)
    run_id = _new_run_id(root, cfg.config_hash())
    manifest = _manifest(app, cfg, fcfg, window, provider, inputs, result, metrics, hashes, rhash, run_id, stress, extra)
    run_dir = None
    if out_dir is not None:
        run_dir = out_dir / run_id
        write_run_files(run_dir, tables, manifest)
        if out_dir == backtests_dir(app):
            append_run_index(app, manifest, run_dir)
    return RunOutcome(run_id, run_dir, manifest, metrics, result, rhash)


def verify_run(run_dir: Path) -> dict[str, Any]:
    """Recompute every table hash from the files and check the contamination audit."""
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    hashes = {}
    for name in TABLE_ORDER:
        text = (run_dir / FILE_NAMES[name]).read_bytes()
        hashes[name] = hashlib.sha256(text).hexdigest()
        if hashes[name] != manifest["table_hashes"][name]:
            problems.append(f"{FILE_NAMES[name]}: hash mismatch")
    if combine_hashes(hashes) != manifest["result_hash"]:
        problems.append("result_hash mismatch")
    start, end = manifest["window_start_ms"], manifest["window_end_ms"]
    for r in manifest["data_ranges_read"]:
        if r["start_ms"] < start or r["end_ms"] > end:
            problems.append(f"data range read outside the window: {r}")
    return {"ok": not problems, "problems": problems, "result_hash": manifest["result_hash"], "touched_test_set": manifest["touched_test_set"]}


# --------------------------------------------------------------------------- baselines

COMPARISON_KEYS = (
    "total_return", "net_pnl_usdt", "max_drawdown", "max_intrabar_drawdown", "n_trades", "win_rate", "profit_factor",
    "avg_trade_usdt", "fees_total", "slippage_total", "funding_total", "turnover", "exposure_time", "volatility", "sharpe", "sortino",
)


def _fmt_num(x: Any) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.6g}"
    return str(x)


def run_baselines(
    app: AppConfig,
    cfg: BacktestConfig,
    fcfg: FeaturesConfig,
    window: AllowedWindow,
    inputs: LoadedInputs,
    *,
    stress: bool = False,
    n_seeds: int | None = None,
) -> dict[str, Any]:
    """No-trade, buy-and-hold and the random-entry distribution on one window, side by side (no ranking)."""
    root = backtests_dir(app)
    root.mkdir(parents=True, exist_ok=True)
    parent_id = _new_run_id(root, cfg.config_hash(), dir_prefix="baselines-")
    parent = root / f"baselines-{parent_id}"
    parent.mkdir(parents=True)
    bh_cfg, re_cfg = cfg.baselines.buy_and_hold, cfg.baselines.random_entry
    seeds = re_cfg.n_seeds if n_seeds is None else n_seeds

    outcomes = {
        "no_trade": execute_run(app, cfg, fcfg, window, NoTrade(), inputs, stress=stress, out_dir=parent / "no_trade"),
        "buy_and_hold": execute_run(app, cfg, fcfg, window, BuyAndHold(bh_cfg.notional_fraction), inputs, stress=stress, out_dir=parent / "buy_and_hold"),
    }

    per_seed: list[dict[str, Any]] = []
    all_trades: list[str] = []
    header: list[str] | None = None
    from dataclasses import fields as dc_fields

    trade_fields = [f.name for f in dc_fields(Trade)]
    for i in range(seeds):
        prov = RandomEntry(
            base_seed=app.project.random_seed, spawn_index=i, n_trades=re_cfg.n_trades, holding_minutes=re_cfg.holding_minutes,
            notional_fraction=re_cfg.notional_fraction, direction_mode=re_cfg.direction_mode,
        )
        result = Backtester(app, cfg, window, inputs.market, inputs.features, stress=stress).run(prov)
        metrics = compute_metrics(result, cfg)
        rhash = combine_hashes(table_hashes(result_tables(result)))
        per_seed.append({"seed_index": i, "result_hash": rhash, "placed": prov.placed, **{k: metrics[k] for k in COMPARISON_KEYS}})
        if header is None:
            header = ["seed_index", *trade_fields]
        for t in result.trades:
            all_trades.append(",".join([str(i)] + [fmt_value(getattr(t, f)) for f in trade_fields]))

    # Reproducibility self-check: re-run seed 0 from scratch and compare the full result hash.
    check = RandomEntry(base_seed=app.project.random_seed, spawn_index=0, n_trades=re_cfg.n_trades, holding_minutes=re_cfg.holding_minutes,
                        notional_fraction=re_cfg.notional_fraction, direction_mode=re_cfg.direction_mode)
    again = Backtester(app, cfg, window, inputs.market, inputs.features, stress=stress).run(check)
    repro_ok = combine_hashes(table_hashes(result_tables(again))) == per_seed[0]["result_hash"] if per_seed else True

    re_dir = parent / "random_entry"
    re_dir.mkdir()
    (re_dir / "trades.csv").write_text("\n".join([",".join(header or [])] + all_trades) + "\n", encoding="utf-8", newline="")
    seeds_cols = list(per_seed[0].keys()) if per_seed else []
    (re_dir / "seeds.csv").write_text(
        "\n".join([",".join(seeds_cols)] + [",".join(fmt_value(row[c]) for c in seeds_cols) for row in per_seed]) + "\n", encoding="utf-8", newline=""
    )
    distribution = {k: summarize_distribution([float(r[k]) for r in per_seed if r[k] is not None]) for k in COMPARISON_KEYS}
    agg_hash = hashlib.sha256("\n".join(r["result_hash"] for r in per_seed).encode()).hexdigest()

    commit, dirty = git_state()
    fm = inputs.feature_manifest
    summary = {
        "baselines_id": parent_id,
        "created_at": utc_now().isoformat(),
        "git_commit": commit,
        "git_dirty": dirty,
        "period": window.period.value,
        "window_start_ms": window.start_ms,
        "window_end_ms": window.end_ms,
        "touched_test_set": window.sealed,
        "stress": stress,
        "feature_version": fm["feature_version"],
        "feature_definition_hash": fm["definition_hash"],
        "feature_content_hash": fm["data_sha256"],
        "feature_cache_source_fingerprint": fm["source_fingerprint"],
        "market_data_fingerprint": inputs.market.fingerprint(),
        "app_config_hash": app.config_hash(),
        "backtest_config_hash": cfg.config_hash(),
        "data_ranges_read": inputs.data_ranges,
        "no_trade": {"run_id": outcomes["no_trade"].run_id, "result_hash": outcomes["no_trade"].result_hash, "metrics": outcomes["no_trade"].metrics},
        "buy_and_hold": {"run_id": outcomes["buy_and_hold"].run_id, "result_hash": outcomes["buy_and_hold"].result_hash, "metrics": outcomes["buy_and_hold"].metrics},
        "random_entry": {
            "n_seeds": seeds,
            "base_seed": app.project.random_seed,
            "algorithm": RandomEntry.ALGORITHM,
            "seed_derivation": "SeedSequence(base_seed, spawn_key=(spawn_index,))",
            "parameters": {"n_trades": re_cfg.n_trades, "holding_minutes": re_cfg.holding_minutes, "notional_fraction": re_cfg.notional_fraction, "direction_mode": re_cfg.direction_mode},
            "seed_result_hashes": [r["result_hash"] for r in per_seed],
            "aggregate_hash": agg_hash,
            "placed_min": min((r["placed"] for r in per_seed), default=None),
            "distribution": distribution,
            "reproducibility_check_seed0": repro_ok,
        },
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "duckdb": duckdb.__version__},
    }
    (parent / "baselines.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (re_dir / "run.json").write_text(json.dumps(summary["random_entry"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (parent / "comparison.txt").write_text(comparison_text(summary), encoding="utf-8")
    index = backtests_dir(app) / "runs.jsonl"
    with index.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"run_id": f"baselines-{parent_id}", "dir": parent.name, "provider": "baselines", "period": window.period.value,
                             "window_start_ms": window.start_ms, "window_end_ms": window.end_ms, "result_hash": agg_hash,
                             "touched_test_set": window.sealed, "git_commit": commit, "git_dirty": dirty, "created_at": summary["created_at"]}, sort_keys=True) + "\n")
    summary["dir"] = str(parent)
    return summary


def comparison_text(summary: dict[str, Any]) -> str:
    """Side-by-side table. Deliberately unsorted and unscored: it shows numbers, it does not pick a winner."""
    nt, bh = summary["no_trade"]["metrics"], summary["buy_and_hold"]["metrics"]
    dist = summary["random_entry"]["distribution"]
    lines = [
        f"Baselines on the {summary['period']} period  [{summary['window_start_ms']} .. {summary['window_end_ms']})"
        f"{'  (STRESS slippage)' if summary['stress'] else ''}",
        f"git {summary['git_commit']}{' (DIRTY working tree)' if summary['git_dirty'] else ''}   touched_test_set={summary['touched_test_set']}",
        "",
        f"{'metric':<24}{'no_trade':>14}{'buy_and_hold':>16}{'random p5':>14}{'random mean':>14}{'random p95':>14}",
    ]
    for k in COMPARISON_KEYS:
        d = dist[k]
        lines.append(f"{k:<24}{_fmt_num(nt.get(k)):>14}{_fmt_num(bh.get(k)):>16}{_fmt_num(d['p5']):>14}{_fmt_num(d['mean']):>14}{_fmt_num(d['p95']):>14}")
    lines += ["", f"random_entry: {summary['random_entry']['n_seeds']} seeds, parameters {summary['random_entry']['parameters']}",
              f"reproducibility check (seed 0 re-run): {summary['random_entry']['reproducibility_check_seed0']}", ""]
    for name in ("no_trade", "buy_and_hold"):
        for w in summary[name]["metrics"]["warnings"]:
            lines.append(f"[{name}] WARNING: {w}")
    lines.append("Results include fees, slippage and funding. They are measurements of the simulator, not evidence of profitability.")
    return "\n".join(lines) + "\n"


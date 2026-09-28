"""End-to-end: synthetic DuckDB + a real Stage 3 feature cache -> run -> artifacts -> verify.

Uses an isolated tmp data directory; the real database and caches are never touched.
"""

import json

import numpy as np
import pytest
import synthetic_market as sm
from bt_helpers import HOUR, T0, bulk_insert_1m, bulk_insert_funding

from arven.backtest.baselines import BuyAndHold, NoTrade
from arven.backtest.errors import ConfigurationError
from arven.core.backtest_config import load_backtest_config
from arven.core.features_config import load_features_config
from arven.core.splitguard import BacktestPeriod, SealedAccessError
from arven.core.time import from_ms
from arven.data.storage import feature_store
from arven.data.storage.db import connect
from arven.features.builder import FeatureTable, build_features, decision_grid
from arven.features.registry import build_registry, definition_hash
from arven.runs import (
    backtests_dir,
    comparison_text,
    execute_run,
    load_inputs,
    make_guard,
    run_baselines,
    sealed_log_path,
    verify_run,
)

HOURS = 72
assert sm.START_MS == T0


@pytest.fixture
def env(make_config):
    app = make_config()
    fcfg = load_features_config()
    bt = load_backtest_config()

    # Stage 3 features on a synthetic market, with feat_ready forced to 1 so that trades can happen.
    market = sm.make_market(n_days=10, seed=1)
    grid = decision_grid(T0, T0 + HOURS * HOUR)
    table = build_features(market, grid, fcfg)
    cols = dict(table.columns)
    cols["feat_ready"] = np.ones(len(grid))
    table = FeatureTable(table.version, table.t_ms, cols, table.specs)
    manifest = feature_store.build_manifest(
        table, definition_hash=definition_hash(fcfg), features_config_hash=fcfg.config_hash(), app_config_hash=app.config_hash(),
        source_fingerprint="synthetic", input_summary={}, git_commit="deadbeef", history_start=from_ms(T0), history_end=from_ms(T0 + HOURS * HOUR),
        peak_working_set_mb=None,
    )
    feature_store.write_cache(feature_store.cache_dir(app.data.data_dir, fcfg.version), table, manifest)

    # 1m rows: the window plus a few rows outside it (which must never be loaded)
    rng = np.random.default_rng(4)
    con = connect(":memory:")
    px = 30_000.0
    rows = []
    for k in range(-5, HOURS * 60 + 5):
        t = T0 + k * 60_000
        o = float(px)
        px *= 1 + rng.normal(0, 3e-4)
        rows.append(("BTCUSDT", t, t + 60_000, o, max(o, float(px)), min(o, float(px)), float(px), 1.0, 1.0, 1, 0.5, 0.5, "x", 0))
    bulk_insert_1m(con, rows)
    fund_rows = [("BTCUSDT", T0 + k * 8 * HOUR, T0 + k * 8 * HOUR, 0.0001, 8, T0 + k * 8 * HOUR, "x", 0) for k in range(0, HOURS // 8 + 2)]
    bulk_insert_funding(con, fund_rows)
    window = make_guard(app).resolve(BacktestPeriod.DEVELOPMENT, T0, T0 + HOURS * HOUR)
    return app, fcfg, bt, con, window


def test_load_inputs_reads_only_the_window(env):
    app, fcfg, bt, con, window = env
    inputs = load_inputs(app, fcfg, window, con)
    m = inputs.market
    assert len(m) == HOURS * 60 and int(m.time_ms[0]) == T0 and int(m.time_ms[-1]) == T0 + HOURS * HOUR - 60_000
    assert len(inputs.features.t_ms) == HOURS and inputs.features.names[-1] == "feat_ready"
    assert {r["dataset"] for r in inputs.data_ranges} == {"ohlcv_1m", "funding_rates", "features"}
    assert all(r["start_ms"] == window.start_ms and r["end_ms"] == window.end_ms for r in inputs.data_ranges)
    assert [float(x) for x in m.funding_rate[:2]] == [0.0001, 0.0001]


def test_a_stale_feature_cache_is_refused(env):
    app, fcfg, bt, con, window = env
    path = feature_store.cache_dir(app.data.data_dir, fcfg.version) / feature_store.MANIFEST_NAME
    manifest = json.loads(path.read_text())
    manifest["definition_hash"] = "0" * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ConfigurationError, match="stale"):
        load_inputs(app, fcfg, window, con)


def test_run_writes_artifacts_with_complete_metadata_and_verifies(env):
    app, fcfg, bt, con, window = env
    inputs = load_inputs(app, fcfg, window, con)
    out = execute_run(app, bt, fcfg, window, BuyAndHold(1.0), inputs, out_dir=backtests_dir(app))
    d = out.run_dir
    assert sorted(p.name for p in d.iterdir()) == ["equity.csv", "fills.csv", "funding.csv", "meta.json", "orders.csv", "run.json", "trades.csv"]
    m = json.loads((d / "run.json").read_text())
    for key in ("git_commit", "git_dirty", "feature_version", "feature_definition_hash", "feature_content_hash", "feature_cache_source_fingerprint",
                "market_data_fingerprint", "app_config_hash", "backtest_config_hash", "features_config_hash", "period", "window_start_ms",
                "window_end_ms", "random_seed", "result_hash", "table_hashes", "touched_test_set", "provider", "provider_hash", "metrics", "data_ranges_read"):
        assert key in m, key
    assert m["feature_version"] == "v1" and m["feature_content_hash"] and m["period"] == "development" and m["touched_test_set"] is False
    assert m["backtest_config_hash"] == bt.config_hash() and m["app_config_hash"] == app.config_hash()
    assert m["result_hash"] == out.result_hash
    assert verify_run(d) == {"ok": True, "problems": [], "result_hash": out.result_hash, "touched_test_set": False}
    index = [json.loads(x) for x in (backtests_dir(app) / "runs.jsonl").read_text().splitlines()]
    assert index[-1]["run_id"] == out.run_id and index[-1]["result_hash"] == out.result_hash

    (d / "trades.csv").write_text((d / "trades.csv").read_text().replace("END_OF_PERIOD", "STOP"), newline="")
    bad = verify_run(d)
    assert not bad["ok"] and any("trades.csv" in p for p in bad["problems"])


def test_verify_flags_data_read_outside_the_window(env):
    app, fcfg, bt, con, window = env
    out = execute_run(app, bt, fcfg, window, NoTrade(), load_inputs(app, fcfg, window, con), out_dir=backtests_dir(app))
    path = out.run_dir / "run.json"
    m = json.loads(path.read_text())
    m["data_ranges_read"].append({"dataset": "ohlcv_1m", "start_ms": window.start_ms, "end_ms": window.end_ms + HOUR})
    path.write_text(json.dumps(m))
    res = verify_run(out.run_dir)
    assert not res["ok"] and any("outside the window" in p for p in res["problems"])


def test_reproducibility_same_inputs_same_result_hash(env):
    app, fcfg, bt, con, window = env
    inputs = load_inputs(app, fcfg, window, con)
    a = execute_run(app, bt, fcfg, window, BuyAndHold(1.0), inputs, out_dir=backtests_dir(app))
    b = execute_run(app, bt, fcfg, window, BuyAndHold(1.0), inputs, out_dir=backtests_dir(app))
    assert a.result_hash == b.result_hash and a.run_id != b.run_id
    assert a.manifest["table_hashes"] == b.manifest["table_hashes"]
    fresh = load_inputs(app, fcfg, window, con)  # reloaded from the database and cache
    assert execute_run(app, bt, fcfg, window, BuyAndHold(1.0), fresh).result_hash == a.result_hash
    assert a.manifest["market_data_fingerprint"] == fresh.market.fingerprint()


def test_baselines_run_side_by_side_without_ranking_and_reproduce(env):
    app, fcfg, bt, con, window = env
    inputs = load_inputs(app, fcfg, window, con)
    cfg = bt.model_copy(update={"baselines": bt.baselines.model_copy(update={"random_entry": bt.baselines.random_entry.model_copy(update={"n_trades": 5, "holding_minutes": 120})})})
    s1 = run_baselines(app, cfg, fcfg, window, inputs, n_seeds=4)
    s2 = run_baselines(app, cfg, fcfg, window, inputs, n_seeds=4)
    assert s1["random_entry"]["aggregate_hash"] == s2["random_entry"]["aggregate_hash"]
    assert s1["random_entry"]["reproducibility_check_seed0"] and s1["no_trade"]["result_hash"] == s2["no_trade"]["result_hash"]
    assert s1["buy_and_hold"]["result_hash"] == s2["buy_and_hold"]["result_hash"]
    assert len(s1["random_entry"]["seed_result_hashes"]) == 4 and len(set(s1["random_entry"]["seed_result_hashes"])) == 4
    assert s1["random_entry"]["seed_derivation"] == "SeedSequence(base_seed, spawn_key=(spawn_index,))" and s1["random_entry"]["base_seed"] == 42
    text = comparison_text(s1).lower()
    assert "no_trade" in text and "buy_and_hold" in text and "random" in text
    for word in ("best", "rank", "winner", "score", "recommend"):
        assert word not in text
    assert "not evidence of profitability" in text
    from pathlib import Path

    parent = Path(s1["dir"])
    assert (parent / "baselines.json").exists() and (parent / "random_entry" / "trades.csv").exists() and (parent / "random_entry" / "seeds.csv").exists()
    assert verify_run(next((parent / "buy_and_hold").iterdir()))["ok"]


def test_sealed_period_requires_acknowledgement_and_is_logged_in_the_run_data_dir(env):
    app, *_ = env
    guard = make_guard(app)
    with pytest.raises(SealedAccessError):
        guard.resolve(BacktestPeriod.TEST)
    assert not sealed_log_path(app).exists()
    w = guard.resolve(BacktestPeriod.TEST, allow_sealed=True, reason="integration test", context={"command": "test"})
    assert w.sealed and sealed_log_path(app).exists()
    assert json.loads(sealed_log_path(app).read_text().splitlines()[0])["reason"] == "integration test"


def test_cli_refuses_the_sealed_period_without_acknowledgement():
    from arven.cli import build_parser, cmd_backtest_run
    from arven.core.config import load_config

    cfg = load_config()
    args = build_parser().parse_args(["backtest", "run", "--provider", "no_trade", "--period", "test"])
    before = sealed_log_path(cfg).exists()
    with pytest.raises(SealedAccessError):
        cmd_backtest_run(cfg, args)
    assert sealed_log_path(cfg).exists() == before  # nothing was logged or read
    args = build_parser().parse_args(["backtest", "baselines", "--period", "test", "--allow-sealed"])
    from arven.cli import cmd_backtest_baselines

    with pytest.raises(SealedAccessError):  # acknowledged but no reason
        cmd_backtest_baselines(cfg, args)
    assert sealed_log_path(cfg).exists() == before

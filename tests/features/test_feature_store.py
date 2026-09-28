"""Parquet cache + manifest round trip (no pandas / pyarrow)."""

import json

import numpy as np
import pytest
from synthetic_market import HOUR, START_MS, make_market

from arven.core.features_config import load_features_config
from arven.core.time import from_ms
from arven.data.storage import feature_store
from arven.features.builder import build_features, decision_grid
from arven.features.registry import build_registry, definition_hash

CFG = load_features_config()


@pytest.fixture(scope="module")
def table():
    market = make_market(n_days=60, seed=2)
    return build_features(market, decision_grid(START_MS, START_MS + 60 * 24 * HOUR - 4 * HOUR), CFG), market


def test_parquet_round_trip_is_exact_and_maps_nan_to_null(table, tmp_path):
    tbl, _ = table
    assert any(np.isnan(c).any() for c in tbl.columns.values())  # warm-up NaNs exist
    path = tmp_path / "f.parquet"
    feature_store.write_table_parquet(tbl, path)
    back = feature_store.read_table_parquet(path, tbl.version, tbl.specs)
    np.testing.assert_array_equal(back.t_ms, tbl.t_ms)
    assert list(back.columns) == list(tbl.columns)
    for name, col in tbl.columns.items():
        np.testing.assert_array_equal(back.columns[name], col, err_msg=name)  # bitwise equal, NaN == NaN
    assert back.content_sha256() == tbl.content_sha256()
    assert not list(tmp_path.glob("*.part")) and not list(tmp_path.glob("*.csv"))


def test_cache_write_read_and_manifest(table, tmp_path):
    tbl, market = table
    manifest = feature_store.build_manifest(
        tbl,
        definition_hash=definition_hash(CFG),
        features_config_hash=CFG.config_hash(),
        app_config_hash="abc",
        source_fingerprint=market.fingerprint(),
        input_summary={"bars_1h": len(market.bars[next(iter(market.bars))])},
        git_commit="deadbeef",
        history_start=from_ms(START_MS),
        history_end=from_ms(START_MS + 60 * 24 * HOUR),
        peak_working_set_mb=123.0,
    )
    directory = feature_store.cache_dir(tmp_path, CFG.version)
    feature_store.write_cache(directory, tbl, manifest)
    assert directory == tmp_path / "features" / "v1"
    assert sorted(p.name for p in directory.iterdir()) == ["features_1h.parquet", "manifest.json"]

    back, m = feature_store.read_cache(directory, build_registry(CFG))
    assert back.content_sha256() == m["data_sha256"] == tbl.content_sha256()
    assert m["rows"] == len(tbl) and m["feature_version"] == "v1"
    assert m["definition_hash"] == definition_hash(CFG) and m["git_commit"] == "deadbeef"
    assert [c["name"] for c in m["columns"]] == list(tbl.columns)
    assert m["first_ready_ms"] is None or m["first_ready_ms"] >= START_MS
    json.dumps(m)  # serialisable


def test_rewriting_the_cache_replaces_it_atomically(table, tmp_path):
    tbl, _ = table
    path = tmp_path / "f.parquet"
    feature_store.write_table_parquet(tbl, path)
    first = path.read_bytes()
    feature_store.write_table_parquet(tbl.select_rows(np.arange(len(tbl)) < 10), path)
    assert path.read_bytes() != first
    assert feature_store.read_table_parquet(path, "v1", tbl.specs).t_ms.shape == (10,)


def test_content_hash_detects_any_change(table):
    tbl, _ = table
    changed = {k: v.copy() for k, v in tbl.columns.items()}
    idx = int(np.flatnonzero(np.isfinite(changed["h1_ret_1"]))[5])
    changed["h1_ret_1"][idx] += 1e-12
    other = type(tbl)(tbl.version, tbl.t_ms, changed, tbl.specs)
    assert other.content_sha256() != tbl.content_sha256()


def test_input_fingerprint_is_stable_and_sensitive(table):
    _, market = table
    assert market.fingerprint() == market.fingerprint()
    other = make_market(n_days=60, seed=3)
    assert other.fingerprint() != market.fingerprint()

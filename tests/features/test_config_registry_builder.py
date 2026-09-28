"""Feature config, registry and builder contracts."""

import copy

import numpy as np
import pytest
import yaml
from pydantic import ValidationError
from synthetic_market import HOUR, START_MS, make_market

from arven.core.config import DEFAULT_CONFIG_DIR
from arven.core.features_config import FEATURES_FILE, FeaturesConfig, load_features_config
from arven.features.builder import build_features, check_decision_times, decision_grid
from arven.features.registry import READY_COLUMN, build_registry, definition_hash

CFG = load_features_config()


def raw() -> dict:
    return yaml.safe_load((DEFAULT_CONFIG_DIR / FEATURES_FILE).read_text(encoding="utf-8"))


# --- config -------------------------------------------------------------------------------------


def test_repo_features_config_loads_and_hash_is_stable():
    assert CFG.version == "v1" and CFG.warmup_factor == 5
    assert CFG.config_hash() == load_features_config().config_hash()
    assert CFG.warmup(14) == 70 and CFG.warmup(200) == 1000


def test_config_hash_changes_with_any_parameter():
    doc = raw()
    doc["momentum"]["rsi_period"] = 21
    assert FeaturesConfig.model_validate(doc).config_hash() != CFG.config_hash()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["trend"].update(slope_ema_period=33),  # not one of ema_periods
        lambda d: d["volatility"].update(cc_vol_short_bars=200),  # short >= long
        lambda d: d["momentum"].update(macd_fast=30),  # fast >= slow
        lambda d: d.update(warmup_factor=0.5),
        lambda d: d["returns"].update(h1_horizons=[1, 1]),
        lambda d: d["returns"].update(h1_horizons=[0]),
        lambda d: d.update(unknown_key=1),
        lambda d: d["open_interest"].update(z_min_valid_fraction=0),
        lambda d: d.update(version="bad version"),
    ],
)
def test_invalid_feature_config_is_rejected(mutate):
    doc = copy.deepcopy(raw())
    mutate(doc)
    with pytest.raises(ValidationError):
        FeaturesConfig.model_validate(doc)


# --- registry -----------------------------------------------------------------------------------


def test_registry_names_are_unique_sql_identifiers_and_ready_is_last():
    specs = build_registry(CFG)
    names = [s.name for s in specs]
    assert len(names) == len(set(names)) and all(n.isidentifier() for n in names)
    assert names[-1] == READY_COLUMN
    assert 50 <= len(names) <= 75


def test_registry_covers_the_planned_groups_and_sources():
    specs = build_registry(CFG)
    assert {s.group for s in specs} == {"returns", "volatility", "trend", "momentum", "volume", "candle", "funding", "open_interest", "time", "quality"}
    assert {s.source for s in specs} == {"1h", "4h", "15m", "5m", "funding", "oi", "time", "derived"}
    assert all(not s.required for s in specs if s.group == "open_interest")  # OI history starts in 2020-09
    assert all(s.warmup_bars >= 1 and s.description for s in specs)


def test_definition_hash_tracks_config_and_specs():
    other = FeaturesConfig.model_validate({**raw(), "warmup_factor": 4})
    assert definition_hash(CFG) == definition_hash(load_features_config())
    assert definition_hash(other) != definition_hash(CFG)


# --- builder ------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def market():
    return make_market(n_days=240, seed=1)


def test_builder_output_matches_registry_and_is_finite_or_nan(market):
    t = decision_grid(START_MS, START_MS + 30 * 24 * HOUR)
    table = build_features(market, t, CFG)
    assert list(table.columns) == [s.name for s in build_registry(CFG)]
    assert all(len(c) == len(t) and c.dtype == np.float64 for c in table.columns.values())
    assert not any(np.isinf(c).any() for c in table.columns.values())
    assert table.version == "v1"


def test_feat_ready_requires_all_required_features_and_ignores_oi(market):
    t = decision_grid(START_MS + 200 * 24 * HOUR, START_MS + 230 * 24 * HOUR)
    table = build_features(market, t, CFG)
    required = [s.name for s in table.specs if s.required]
    all_finite = np.all([np.isfinite(table.columns[n]) for n in required], axis=0)
    np.testing.assert_array_equal(table.columns["feat_ready"], all_finite.astype(float))
    assert table.columns["feat_ready"].sum() > 0
    # Early rows are not ready (warm-up), whatever OI says.
    early = build_features(market, decision_grid(START_MS + 24 * HOUR, START_MS + 48 * HOUR), CFG)
    assert early.columns["feat_ready"].sum() == 0


def test_builder_is_deterministic(market):
    t = decision_grid(START_MS, START_MS + 60 * 24 * HOUR)
    assert build_features(market, t, CFG).content_sha256() == build_features(market, t, CFG).content_sha256()


def test_decision_time_validation():
    with pytest.raises(ValueError):
        check_decision_times(np.array([START_MS + 1]))
    with pytest.raises(ValueError):
        check_decision_times(np.array([START_MS + HOUR, START_MS]))
    with pytest.raises(ValueError):
        check_decision_times(np.array([START_MS, START_MS]))
    assert len(check_decision_times(np.array([], dtype=np.int64))) == 0


def test_decision_grid_is_half_open_hour_closes():
    g = decision_grid(START_MS + 1, START_MS + 3 * HOUR)
    np.testing.assert_array_equal(g, [START_MS + HOUR, START_MS + 2 * HOUR])
    g = decision_grid(START_MS, START_MS + 2 * HOUR)
    np.testing.assert_array_equal(g, [START_MS, START_MS + HOUR])


def test_select_rows_keeps_columns_aligned(market):
    t = decision_grid(START_MS, START_MS + 10 * HOUR)
    table = build_features(market, t, CFG)
    sub = table.select_rows(table.t_ms >= START_MS + 5 * HOUR)
    assert len(sub) == 5 and all(len(c) == 5 for c in sub.columns.values())

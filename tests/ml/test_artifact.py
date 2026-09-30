"""Model artifacts: save/load round trip, manifest completeness, hash verification and determinism."""

import numpy as np
import pytest

from arven.ml.artifact import (
    ModelArtifact,
    artifact_bytes,
    build_manifest,
    dataset_fingerprint,
    load_artifact,
    save_artifact,
    verify_artifact,
)
from arven.ml.calibration import fit_isotonic
from arven.ml.model import fit_lightgbm, fit_logistic_regression

REQUIRED_MANIFEST_FIELDS = (
    "model_id", "model_family", "git_commit", "git_dirty", "feature_version", "feature_definition_hash",
    "feature_content_hash", "ml_config_hash", "app_config_hash", "backtest_config_hash", "regime_config_hash",
    "strategies_config_hash", "risk_config_hash", "training_period_start_ms", "training_period_end_ms",
    "validation_period_start_ms", "validation_period_end_ms", "random_seed", "hyperparameters", "fold_summary",
    "training_dataset_fingerprint", "model_artifact_hash", "threshold", "feature_names", "n_features",
    "n_candidates_total", "n_ineligible_risk", "n_ineligible_label", "n_train_rows", "n_calibration_rows",
    "metrics", "warnings", "environment", "touched_test_set", "threshold_selection",
)


def _logistic_artifact():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(200, 2))
    y = (rng.random(200) < 0.4).astype(float)
    model = fit_logistic_regression(x, y, ("a", "b"), l2=1.0)
    cal = fit_isotonic(model.predict_proba(x), y)
    return ModelArtifact("logistic", model, cal, ("a", "b"), 0.55, x.mean(axis=0), x.std(axis=0))


def _lightgbm_artifact():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(200, 2))
    y = (rng.random(200) < 0.4).astype(float)
    hp = {"num_leaves": 7, "max_depth": 3, "learning_rate": 0.1, "min_data_in_leaf": 10, "feature_fraction": 0.8, "bagging_fraction": 0.8, "lambda_l1": 0.0, "lambda_l2": 1.0}
    model = fit_lightgbm(x[:150], y[:150], x[150:], y[150:], ("a", "b"), hp, 30, 5, seed=1)
    cal = fit_isotonic(model.predict_proba(x[150:]), y[150:])
    return ModelArtifact("lightgbm", model, cal, ("a", "b"), 0.55, None, None)


def _manifest_for(artifact):
    return build_manifest(
        model_id="test-model", artifact=artifact, feature_version="v1", feature_definition_hash="a" * 64,
        feature_content_hash="b" * 64, ml_config_hash="c" * 64, app_config_hash="d" * 64,
        backtest_config_hash="e" * 64, regime_config_hash="f" * 64, strategies_config_hash="0" * 64,
        risk_config_hash="1" * 64, training_period=(0, 1000), validation_period=(1000, 2000), random_seed=42,
        hyperparameters={"l2": 1.0}, fold_summary=[], train_dataset_fingerprint="2" * 64,
        metrics={"raw": {"log_loss": 0.6}}, n_candidates_total=200, n_ineligible_risk=0, n_ineligible_label=0,
        n_train_rows=150, n_calibration_rows=50, warnings=[],
        threshold_selection={"candidates": [0.5, 0.55], "selected": 0.55, "used_fallback": False},
    )


@pytest.mark.parametrize("make", [_logistic_artifact, _lightgbm_artifact])
def test_save_load_round_trip_preserves_predictions(tmp_path, make):
    artifact = make()
    manifest = _manifest_for(artifact)
    d = tmp_path / "m"
    save_artifact(d, artifact, manifest)
    loaded, loaded_manifest = load_artifact(d)
    assert loaded_manifest == manifest
    x = np.random.default_rng(9).normal(size=(10, 2))
    assert np.array_equal(loaded.predict_calibrated(x), artifact.predict_calibrated(x))


@pytest.mark.parametrize("make", [_logistic_artifact, _lightgbm_artifact])
def test_manifest_has_every_required_field(make):
    manifest = _manifest_for(make())
    for field in REQUIRED_MANIFEST_FIELDS:
        assert field in manifest, field
    assert manifest["touched_test_set"] is False


@pytest.mark.parametrize("make", [_logistic_artifact, _lightgbm_artifact])
def test_verify_passes_on_an_untouched_saved_artifact(tmp_path, make):
    artifact = make()
    manifest = _manifest_for(artifact)
    d = tmp_path / "m"
    save_artifact(d, artifact, manifest)
    res = verify_artifact(d)
    assert res["ok"] and not res["problems"]


@pytest.mark.parametrize("make", [_logistic_artifact, _lightgbm_artifact])
def test_verify_fails_on_a_tampered_manifest(tmp_path, make):
    import json

    artifact = make()
    manifest = _manifest_for(artifact)
    d = tmp_path / "m"
    save_artifact(d, artifact, manifest)
    m = json.loads((d / "manifest.json").read_text())
    m["model_artifact_hash"] = "0" * 64
    (d / "manifest.json").write_text(json.dumps(m))
    res = verify_artifact(d)
    assert not res["ok"] and "model_artifact_hash mismatch" in res["problems"]


@pytest.mark.parametrize("make", [_logistic_artifact, _lightgbm_artifact])
def test_artifact_bytes_are_deterministic_for_a_fixed_object(make):
    artifact = make()
    assert artifact_bytes(artifact) == artifact_bytes(artifact)


def test_dataset_fingerprint_is_deterministic_and_sensitive():
    t = np.array([1, 2, 3], dtype=np.int64)
    x = np.array([[1.0, 2.0], [3.0, np.nan], [5.0, 6.0]])
    label = np.array([1, 0, 1])
    f1 = dataset_fingerprint(t, x, label)
    f2 = dataset_fingerprint(t, x, label)
    assert f1 == f2
    f3 = dataset_fingerprint(t, x, np.array([1, 1, 1]))
    assert f1 != f3


def test_two_independently_trained_lightgbm_artifacts_with_the_same_seed_have_the_same_hash():
    """Determinism at the artifact level, not just the model level: the whole pickled bundle (including the
    LightGBM model_str fix) must be byte-identical across two independent fits."""
    a1 = _lightgbm_artifact()
    a2 = _lightgbm_artifact()
    assert artifact_bytes(a1) == artifact_bytes(a2)


def test_two_independently_trained_logistic_artifacts_with_the_same_data_have_the_same_hash():
    a1 = _logistic_artifact()
    a2 = _logistic_artifact()
    assert artifact_bytes(a1) == artifact_bytes(a2)

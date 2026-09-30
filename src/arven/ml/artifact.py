"""Model artifacts: a frozen, versioned bundle a :class:`~arven.ml.filter.MetaFilter` loads at backtest
time, plus the full-provenance manifest every trained model must record (mirrors Stage 3's
``manifest.json`` and Stage 4/5's ``run.json`` conventions exactly - same field families, same
content-hash-over-canonical-bytes technique as ``MarketData.fingerprint()``/``FeatureTable.content_sha256()``).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pickle
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import lightgbm
import numpy as np

from arven.ml.calibration import IsotonicCalibrator
from arven.ml.model import LightGBMModel, LogisticRegressionModel

MANIFEST_NAME = "manifest.json"
MODEL_NAME = "model.pkl"

ModelFamily = Literal["logistic", "lightgbm"]


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
class ModelArtifact:
    model_family: ModelFamily
    model: LogisticRegressionModel | LightGBMModel
    calibrator: IsotonicCalibrator
    feature_names: tuple[str, ...]
    threshold: float
    scaler_mean: np.ndarray | None  # logistic only; None for lightgbm
    scaler_std: np.ndarray | None

    def raw_score(self, x: np.ndarray) -> np.ndarray:
        if self.model_family == "logistic":
            assert self.scaler_mean is not None and self.scaler_std is not None
            xs = (x - self.scaler_mean) / self.scaler_std
            return self.model.predict_proba(xs)
        return self.model.predict_proba(x)

    def predict_calibrated(self, x: np.ndarray) -> np.ndarray:
        return self.calibrator.predict(self.raw_score(x))


def _canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def dataset_fingerprint(t_ms: np.ndarray, x: np.ndarray, label: np.ndarray) -> str:
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(t_ms, dtype=np.int64).tobytes())
    xa = np.ascontiguousarray(x, dtype=np.float64)
    h.update(np.where(np.isnan(xa), np.nan, xa).tobytes())
    h.update(np.ascontiguousarray(label, dtype=np.int64).tobytes())
    return h.hexdigest()


def artifact_bytes(artifact: ModelArtifact) -> bytes:
    buf = io.BytesIO()
    pickle.dump(artifact, buf, protocol=4)
    return buf.getvalue()


def build_manifest(
    *,
    model_id: str,
    artifact: ModelArtifact,
    feature_version: str,
    feature_definition_hash: str,
    feature_content_hash: str,
    ml_config_hash: str,
    app_config_hash: str,
    backtest_config_hash: str,
    regime_config_hash: str,
    strategies_config_hash: str,
    risk_config_hash: str,
    training_period: tuple[int, int],
    validation_period: tuple[int, int],
    random_seed: int,
    hyperparameters: dict,
    fold_summary: list[dict],
    train_dataset_fingerprint: str,
    metrics: dict,
    n_candidates_total: int,
    n_ineligible_risk: int,
    n_ineligible_label: int,
    n_train_rows: int,
    n_calibration_rows: int,
    warnings: list[str],
    threshold_selection: dict[str, Any],
) -> dict[str, Any]:
    commit, dirty = git_state()
    artifact_hash = hashlib.sha256(artifact_bytes(artifact)).hexdigest()
    return {
        "model_id": model_id,
        "model_family": artifact.model_family,
        "git_commit": commit,
        "git_dirty": dirty,
        "feature_version": feature_version,
        "feature_definition_hash": feature_definition_hash,
        "feature_content_hash": feature_content_hash,
        "ml_config_hash": ml_config_hash,
        "app_config_hash": app_config_hash,
        "backtest_config_hash": backtest_config_hash,
        "regime_config_hash": regime_config_hash,
        "strategies_config_hash": strategies_config_hash,
        "risk_config_hash": risk_config_hash,
        "training_period_start_ms": training_period[0],
        "training_period_end_ms": training_period[1],
        "validation_period_start_ms": validation_period[0],
        "validation_period_end_ms": validation_period[1],
        "random_seed": random_seed,
        "hyperparameters": hyperparameters,
        "fold_summary": fold_summary,
        "training_dataset_fingerprint": train_dataset_fingerprint,
        "model_artifact_hash": artifact_hash,
        "threshold": artifact.threshold,
        "feature_names": list(artifact.feature_names),
        "n_features": len(artifact.feature_names),
        "n_candidates_total": n_candidates_total,
        "n_ineligible_risk": n_ineligible_risk,
        "n_ineligible_label": n_ineligible_label,
        "n_train_rows": n_train_rows,
        "n_calibration_rows": n_calibration_rows,
        "metrics": metrics,
        "warnings": warnings,
        # BLOCKER 2 (Stage 6 pre-commit audit): complete provenance for the threshold selection - candidates,
        # the selected value, the exact objective and tie-break rule, and whether the fallback path fired
        # (never a silent, unexplained choice).
        "threshold_selection": threshold_selection,
        "environment": {
            "python": platform.python_version(), "numpy": np.__version__, "lightgbm": lightgbm.__version__,
        },
        "touched_test_set": False,
    }


def save_artifact(directory: Path, artifact: ModelArtifact, manifest: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tmp_model = directory / (MODEL_NAME + ".part")
    tmp_model.write_bytes(artifact_bytes(artifact))
    os.replace(tmp_model, directory / MODEL_NAME)
    tmp_manifest = directory / (MANIFEST_NAME + ".part")
    tmp_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_manifest, directory / MANIFEST_NAME)


def load_artifact(directory: Path) -> tuple[ModelArtifact, dict[str, Any]]:
    manifest = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    artifact = pickle.loads((directory / MODEL_NAME).read_bytes())
    return artifact, manifest


def verify_artifact(directory: Path) -> dict[str, Any]:
    artifact, manifest = load_artifact(directory)
    problems: list[str] = []
    actual_hash = hashlib.sha256(artifact_bytes(artifact)).hexdigest()
    if actual_hash != manifest["model_artifact_hash"]:
        problems.append("model_artifact_hash mismatch")
    if list(artifact.feature_names) != manifest["feature_names"]:
        problems.append("feature_names mismatch")
    if artifact.threshold != manifest["threshold"]:
        problems.append("threshold mismatch")
    return {"ok": not problems, "problems": problems, "model_artifact_hash": manifest["model_artifact_hash"]}

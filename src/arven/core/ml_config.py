"""ML meta-filter configuration (``config/ml.yaml``). Own hash, like the other Stage 3+ configs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import Field, model_validator

from arven.core.config import DEFAULT_CONFIG_DIR, _read_yaml, _StrictModel

ML_FILE = "ml.yaml"


class LabelsConfig(_StrictModel):
    min_net_return_for_positive_label: float


class DatasetConfig(_StrictModel):
    apply_portfolio_state_risk_rules: bool

    @model_validator(mode="after")
    def _d3(self) -> DatasetConfig:
        if self.apply_portfolio_state_risk_rules:
            raise ValueError("apply_portfolio_state_risk_rules must be false (approved decision D3)")
        return self


class WalkForwardConfig(_StrictModel):
    retrain_interval_months: int = Field(ge=1)
    embargo_hours: int = Field(ge=1)
    min_train_months: int = Field(ge=1)


class LogisticHyperparams(_StrictModel):
    l2: float = Field(gt=0)


class LightGBMHyperparams(_StrictModel):
    num_leaves: int = Field(ge=2)
    max_depth: int = Field(ge=1)
    learning_rate: float = Field(gt=0, le=1)
    min_data_in_leaf: int = Field(ge=1)
    feature_fraction: float = Field(gt=0, le=1)
    bagging_fraction: float = Field(gt=0, le=1)
    lambda_l1: float = Field(ge=0)
    lambda_l2: float = Field(ge=0)


class HyperparametersConfig(_StrictModel):
    logistic: tuple[LogisticHyperparams, ...] = Field(min_length=1, max_length=4)
    lightgbm: tuple[LightGBMHyperparams, ...] = Field(min_length=1, max_length=4)
    n_estimators_max: int = Field(ge=1)
    early_stopping_rounds: int = Field(ge=1)
    selection_metric: str = Field(pattern=r"^(log_loss|brier)$")


class CalibrationConfig(_StrictModel):
    method: str = Field(pattern=r"^isotonic$")


class ThresholdConfig(_StrictModel):
    candidates: tuple[float, ...] = Field(min_length=1)
    default: float

    @model_validator(mode="after")
    def _bounds(self) -> ThresholdConfig:
        if not all(0.0 < c < 1.0 for c in self.candidates):
            raise ValueError("threshold candidates must be in (0, 1)")
        if self.default not in self.candidates:
            raise ValueError("threshold.default must be one of threshold.candidates")
        return self


class DeterminismConfig(_StrictModel):
    lightgbm_deterministic: bool

    @model_validator(mode="after")
    def _must_be_true(self) -> DeterminismConfig:
        if not self.lightgbm_deterministic:
            raise ValueError("lightgbm_deterministic must be true (Stage 6 requires deterministic training)")
        return self


class MLConfig(_StrictModel):
    version: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    labels: LabelsConfig
    dataset: DatasetConfig
    walk_forward: WalkForwardConfig
    hyperparameters: HyperparametersConfig
    calibration: CalibrationConfig
    threshold: ThresholdConfig
    determinism: DeterminismConfig

    def config_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_ml_config(config_dir: Path | str | None = None) -> MLConfig:
    config_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    return MLConfig.model_validate(_read_yaml(config_dir / ML_FILE))

import copy

import pytest
import yaml
from pydantic import ValidationError

from arven.core.config import DEFAULT_CONFIG_DIR
from arven.core.ml_config import ML_FILE, MLConfig, load_ml_config


def raw():
    return yaml.safe_load((DEFAULT_CONFIG_DIR / ML_FILE).read_text(encoding="utf-8"))


def test_repo_config_loads_and_hash_is_stable():
    cfg = load_ml_config()
    assert cfg.version == "v1"
    assert len(cfg.hyperparameters.logistic) <= 4 and len(cfg.hyperparameters.lightgbm) <= 4  # D5
    assert cfg.walk_forward.retrain_interval_months == 3 and cfg.walk_forward.embargo_hours == 96 and cfg.walk_forward.min_train_months == 12  # D4
    assert cfg.calibration.method == "isotonic"  # D6
    assert cfg.config_hash() == load_ml_config().config_hash()


def test_config_hash_changes_with_a_value():
    doc = raw()
    doc["threshold"]["default"] = 0.5
    assert MLConfig.model_validate(doc).config_hash() != load_ml_config().config_hash()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["dataset"].update(apply_portfolio_state_risk_rules=True),  # D3
        lambda d: d.update(hyperparameters={**d["hyperparameters"], "logistic": [d["hyperparameters"]["logistic"][0]] * 5}),  # >4 (D5)
        lambda d: d["threshold"].update(default=0.99),  # not in candidates
        lambda d: d["threshold"].update(candidates=[1.5]),
        lambda d: d["determinism"].update(lightgbm_deterministic=False),
        lambda d: d["calibration"].update(method="platt"),
        lambda d: d.update(unknown=1),
    ],
)
def test_invalid_config_rejected(mutate):
    doc = copy.deepcopy(raw())
    mutate(doc)
    with pytest.raises(ValidationError):
        MLConfig.model_validate(doc)

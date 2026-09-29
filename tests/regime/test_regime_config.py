import copy

import pytest
import yaml
from pydantic import ValidationError

from arven.core.config import DEFAULT_CONFIG_DIR
from arven.core.regime_config import REGIME_FILE, RegimeConfig, load_regime_config


def raw():
    return yaml.safe_load((DEFAULT_CONFIG_DIR / REGIME_FILE).read_text(encoding="utf-8"))


def test_repo_config_loads_and_hash_is_stable():
    cfg = load_regime_config()
    assert cfg.version == "v1"
    assert cfg.config_hash() == load_regime_config().config_hash()


def test_config_hash_changes_with_a_value():
    doc = raw()
    doc["trend"]["adx_4h_threshold"] = 99.0
    assert RegimeConfig.model_validate(doc).config_hash() != load_regime_config().config_hash()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["volatility"].update(low_percentile=70.0, high_percentile=60.0),
        lambda d: d["volatility"].update(min_history_bars=d["volatility"]["window_hours"] + 1),
        lambda d: d.update(min_dwell_bars=0),
        lambda d: d["trend"].update(adx_4h_threshold=-1.0),
        lambda d: d.update(unknown=1),
    ],
)
def test_invalid_config_rejected(mutate):
    doc = copy.deepcopy(raw())
    mutate(doc)
    with pytest.raises(ValidationError):
        RegimeConfig.model_validate(doc)

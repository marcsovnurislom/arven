import copy

import pytest
import yaml
from pydantic import ValidationError

from arven.core.config import DEFAULT_CONFIG_DIR
from arven.core.strategies_config import STRATEGIES_FILE, StrategiesConfig, load_strategies_config


def raw():
    return yaml.safe_load((DEFAULT_CONFIG_DIR / STRATEGIES_FILE).read_text(encoding="utf-8"))


def test_repo_config_loads_and_hash_is_stable():
    cfg = load_strategies_config()
    assert cfg.version == "v1"
    assert set(cfg.decision.weights) == {"trend_momentum", "breakout", "mean_reversion"}
    assert cfg.config_hash() == load_strategies_config().config_hash()


def test_config_hash_changes_with_a_value():
    doc = raw()
    doc["mean_reversion"]["bb_z_threshold"] = 3.5
    assert StrategiesConfig.model_validate(doc).config_hash() != load_strategies_config().config_hash()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["trend_momentum"].update(ema_fast=30),  # not one of 20/50/200
        lambda d: d["trend_momentum"].update(ema_fast=50, ema_slow=20),  # fast >= slow
        lambda d: d["breakout"].update(compression_lookback_bars=d["breakout"]["bb_width_window_bars"]),
        lambda d: d["breakout"].update(breakout_upper=0.4),
        lambda d: d["mean_reversion"].update(rsi_oversold_confirm=60.0),
        lambda d: d["decision"]["weights"].pop("breakout"),
        lambda d: d["decision"].update(decision_threshold=-0.1),
        lambda d: d["trend_momentum"].update(allowed_trends=["SIDEWAYS"]),  # not a real label
        lambda d: d.update(unknown=1),
    ],
)
def test_invalid_config_rejected(mutate):
    doc = copy.deepcopy(raw())
    mutate(doc)
    with pytest.raises(ValidationError):
        StrategiesConfig.model_validate(doc)

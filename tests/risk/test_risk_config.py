import copy

import pytest
import yaml
from pydantic import ValidationError

from arven.core.config import DEFAULT_CONFIG_DIR
from arven.core.risk_config import RISK_FILE, RiskConfig, load_risk_config


def raw():
    return yaml.safe_load((DEFAULT_CONFIG_DIR / RISK_FILE).read_text(encoding="utf-8"))


def test_repo_config_loads_and_hash_is_stable():
    cfg = load_risk_config()
    assert cfg.risk_fraction_per_trade == 0.0075
    assert cfg.config_hash() == load_risk_config().config_hash()


def test_config_hash_changes_with_a_value():
    doc = raw()
    doc["risk_fraction_per_trade"] = 0.01
    assert RiskConfig.model_validate(doc).config_hash() != load_risk_config().config_hash()


def test_leverage_and_maintenance_margin_rate_are_not_duplicated_here():
    assert "leverage" not in raw() and "maintenance_margin_rate" not in raw()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(min_stop_pct=0.1, max_stop_pct=0.05),
        lambda d: d.update(funding_guard_reduce_z=5.0, funding_guard_veto_z=2.0),
        lambda d: d.update(drawdown_resume_pct=0.3, max_drawdown_halt_pct=0.2),
        lambda d: d.update(liquidation_min_multiple=0.5),
        lambda d: d.update(risk_fraction_per_trade=1.5),
        lambda d: d.update(cooldown_after_losses=0),
        lambda d: d.update(unknown=1),
    ],
)
def test_invalid_config_rejected(mutate):
    doc = copy.deepcopy(raw())
    mutate(doc)
    with pytest.raises(ValidationError):
        RiskConfig.model_validate(doc)

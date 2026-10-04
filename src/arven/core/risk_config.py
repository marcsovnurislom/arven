"""Risk-engine configuration (``config/risk.yaml``). Own hash.

Leverage and ``maintenance_margin_rate`` are deliberately not here: the risk engine reads them from
``config/backtest.yaml`` (:class:`~arven.core.backtest_config.BacktestConfig`) so the exchange-level
parameters have a single source of truth shared with the backtester.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import Field, model_validator

from arven.core.config import DEFAULT_CONFIG_DIR, _read_yaml, _StrictModel

RISK_FILE = "risk.yaml"


class RiskConfig(_StrictModel):
    macro_blackout_window_hours: float = Field(gt=0)

    high_vol_size_multiplier: float = Field(gt=0, le=1.0)
    veto_on_stress: bool

    funding_guard_reduce_z: float = Field(gt=0)
    funding_guard_veto_z: float = Field(gt=0)
    funding_guard_reduce_multiplier: float = Field(gt=0, le=1.0)

    min_stop_pct: float = Field(gt=0)
    max_stop_pct: float = Field(gt=0)
    min_reward_risk_ratio: float = Field(gt=0)

    risk_fraction_per_trade: float = Field(gt=0, lt=1.0)
    max_notional_fraction: float = Field(gt=0)

    max_daily_loss_pct: float = Field(gt=0, lt=1.0)
    max_drawdown_halt_pct: float = Field(gt=0, lt=1.0)
    drawdown_resume_pct: float = Field(gt=0, lt=1.0)
    cooldown_after_losses: int = Field(ge=1)
    cooldown_bars: int = Field(ge=1)

    liquidation_min_multiple: float = Field(gt=1.0)

    @model_validator(mode="after")
    def _cross_checks(self) -> RiskConfig:
        if self.min_stop_pct >= self.max_stop_pct:
            raise ValueError("min_stop_pct must be smaller than max_stop_pct")
        if self.funding_guard_reduce_z >= self.funding_guard_veto_z:
            raise ValueError("funding_guard_reduce_z must be smaller than funding_guard_veto_z")
        if self.drawdown_resume_pct >= self.max_drawdown_halt_pct:
            raise ValueError("drawdown_resume_pct must be smaller than max_drawdown_halt_pct")
        return self

    def config_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_risk_config(config_dir: Path | str | None = None) -> RiskConfig:
    config_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    return RiskConfig.model_validate(_read_yaml(config_dir / RISK_FILE))

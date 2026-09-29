"""Regime-detection configuration (``config/regime.yaml``). Own hash, like the other Stage 3+ configs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import Field, model_validator

from arven.core.config import DEFAULT_CONFIG_DIR, _read_yaml, _StrictModel

REGIME_FILE = "regime.yaml"


class TrendRegimeConfig(_StrictModel):
    adx_4h_threshold: float = Field(gt=0)
    adx_1h_confirm_threshold: float = Field(gt=0)


class VolatilityRegimeConfig(_StrictModel):
    window_hours: int = Field(ge=1)
    min_history_bars: int = Field(ge=1)
    low_percentile: float = Field(ge=0, le=100)
    high_percentile: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _order(self) -> VolatilityRegimeConfig:
        if self.low_percentile >= self.high_percentile:
            raise ValueError("low_percentile must be smaller than high_percentile")
        if self.min_history_bars > self.window_hours:
            raise ValueError("min_history_bars must not exceed window_hours")
        return self


class StressRegimeConfig(_StrictModel):
    funding_z_threshold: float = Field(gt=0)
    oi_change_1h_threshold: float = Field(gt=0)


class RegimeConfig(_StrictModel):
    version: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    trend: TrendRegimeConfig
    volatility: VolatilityRegimeConfig
    stress: StressRegimeConfig
    min_dwell_bars: int = Field(ge=1)

    def config_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_regime_config(config_dir: Path | str | None = None) -> RegimeConfig:
    config_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    return RegimeConfig.model_validate(_read_yaml(config_dir / REGIME_FILE))

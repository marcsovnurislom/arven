"""Strategy and decision-layer configuration (``config/strategies.yaml``). Own hash.

Trend/vol labels are validated here as plain string literals (matching ``arven.regime.detector.TrendState`` /
``VolState`` by value) rather than by importing that module, to keep ``core`` free of dependents' dependencies.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from arven.core.config import DEFAULT_CONFIG_DIR, _read_yaml, _StrictModel

STRATEGIES_FILE = "strategies.yaml"

TrendLabel = Literal["TREND_UP", "TREND_DOWN", "NO_TREND"]
VolLabel = Literal["LOW", "NORMAL", "HIGH"]
_EMA_PERIODS = (20, 50, 200)


class DecisionConfig(_StrictModel):
    weights: dict[str, float]
    decision_threshold: float = Field(gt=0)
    conflict_threshold: float = Field(gt=0)

    @model_validator(mode="after")
    def _weights_positive(self) -> DecisionConfig:
        if not self.weights or any(w < 0 for w in self.weights.values()):
            raise ValueError("weights must be non-empty and non-negative")
        return self


class TrendMomentumConfig(_StrictModel):
    ema_fast: int
    ema_slow: int
    adx_4h_threshold: float = Field(gt=0)
    adx_strength_scale: float = Field(gt=0)
    rsi_overbought_block: float = Field(gt=50, le=100)
    rsi_oversold_block: float = Field(ge=0, lt=50)
    require_macd_confirm: bool
    stop_atr_mult: float = Field(gt=0)
    take_profit_atr_mult: float = Field(gt=0)
    max_holding_minutes: int = Field(ge=1)
    allowed_trends: tuple[TrendLabel, ...] | None
    allowed_vols: tuple[VolLabel, ...] | None
    require_not_stress: bool

    @model_validator(mode="after")
    def _emas_known_and_ordered(self) -> TrendMomentumConfig:
        if self.ema_fast not in _EMA_PERIODS or self.ema_slow not in _EMA_PERIODS:
            raise ValueError(f"ema_fast/ema_slow must be one of {_EMA_PERIODS} (the Stage 3 EMA periods)")
        if self.ema_fast >= self.ema_slow:
            raise ValueError("ema_fast must be smaller than ema_slow")
        return self


class BreakoutConfig(_StrictModel):
    bb_width_window_bars: int = Field(ge=2)
    compression_lookback_bars: int = Field(ge=1)
    compression_percentile: float = Field(ge=0, le=100)
    donchian_feature: str
    breakout_upper: float = Field(gt=0.5, le=1.0)
    breakout_lower: float = Field(ge=0.0, lt=0.5)
    stop_atr_mult: float = Field(gt=0)
    take_profit_atr_mult: float = Field(gt=0)
    max_holding_minutes: int = Field(ge=1)
    allowed_trends: tuple[TrendLabel, ...] | None
    allowed_vols: tuple[VolLabel, ...] | None
    require_not_stress: bool

    @model_validator(mode="after")
    def _lookback_within_window(self) -> BreakoutConfig:
        if self.compression_lookback_bars >= self.bb_width_window_bars:
            raise ValueError("compression_lookback_bars must be smaller than bb_width_window_bars")
        return self


class MeanReversionConfig(_StrictModel):
    bb_z_threshold: float = Field(gt=0)
    bb_z_strength_scale: float = Field(gt=0)
    rsi_oversold_confirm: float = Field(ge=0, lt=50)
    rsi_overbought_confirm: float = Field(gt=50, le=100)
    stop_atr_mult: float = Field(gt=0)
    take_profit_atr_mult: float = Field(gt=0)
    max_holding_minutes: int = Field(ge=1)
    allowed_trends: tuple[TrendLabel, ...] | None
    allowed_vols: tuple[VolLabel, ...] | None
    require_not_stress: bool


class StrategiesConfig(_StrictModel):
    version: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    decision: DecisionConfig
    trend_momentum: TrendMomentumConfig
    breakout: BreakoutConfig
    mean_reversion: MeanReversionConfig

    @model_validator(mode="after")
    def _weights_cover_every_strategy(self) -> StrategiesConfig:
        names = {"trend_momentum", "breakout", "mean_reversion"}
        if set(self.decision.weights) != names:
            raise ValueError(f"decision.weights must have exactly one entry per strategy: {sorted(names)}")
        return self

    def config_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_strategies_config(config_dir: Path | str | None = None) -> StrategiesConfig:
    config_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    return StrategiesConfig.model_validate(_read_yaml(config_dir / STRATEGIES_FILE))

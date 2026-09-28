"""Feature configuration (``config/features.yaml``).

Kept separate from :class:`arven.core.config.AppConfig` on purpose: it has its own hash
(:meth:`FeaturesConfig.config_hash`), so ``AppConfig.config_hash()`` and everything recorded with it in
Stage 2 stay unchanged.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from arven.core.config import DEFAULT_CONFIG_DIR, _read_yaml, _StrictModel

FEATURES_FILE = "features.yaml"


def _positive_unique(values: tuple[int, ...]) -> tuple[int, ...]:
    if not values or any(v < 1 for v in values) or len(set(values)) != len(values):
        raise ValueError("expected a non-empty list of unique positive integers")
    return values


class ReturnsConfig(_StrictModel):
    h1_horizons: tuple[int, ...]
    h4_horizons: tuple[int, ...]
    m15_horizons: tuple[int, ...]

    _check = field_validator("h1_horizons", "h4_horizons", "m15_horizons")(_positive_unique)


class VolatilityConfig(_StrictModel):
    atr_period: int = Field(ge=2)
    rv5m_short_hours: int = Field(ge=1)
    rv5m_long_hours: int = Field(ge=1)
    cc_vol_short_bars: int = Field(ge=2)
    cc_vol_long_bars: int = Field(ge=2)
    parkinson_window: int = Field(ge=1)

    @model_validator(mode="after")
    def _order(self) -> VolatilityConfig:
        if self.rv5m_short_hours >= self.rv5m_long_hours:
            raise ValueError("rv5m_short_hours must be smaller than rv5m_long_hours")
        if self.cc_vol_short_bars >= self.cc_vol_long_bars:
            raise ValueError("cc_vol_short_bars must be smaller than cc_vol_long_bars")
        return self


class TrendConfig(_StrictModel):
    ema_periods: tuple[int, ...]
    slope_ema_period: int
    slope_bars: int = Field(ge=1)
    adx_period: int = Field(ge=2)
    donchian_windows: tuple[int, ...]

    _check = field_validator("ema_periods", "donchian_windows")(_positive_unique)

    @model_validator(mode="after")
    def _slope_period_known(self) -> TrendConfig:
        if self.slope_ema_period not in self.ema_periods:
            raise ValueError("slope_ema_period must be one of ema_periods")
        return self


class MomentumConfig(_StrictModel):
    rsi_period: int = Field(ge=2)
    macd_fast: int = Field(ge=2)
    macd_slow: int = Field(ge=2)
    macd_signal: int = Field(ge=2)
    bollinger_window: int = Field(ge=2)
    bollinger_k: float = Field(gt=0)

    @model_validator(mode="after")
    def _order(self) -> MomentumConfig:
        if self.macd_fast >= self.macd_slow:
            raise ValueError("macd_fast must be smaller than macd_slow")
        return self


class VolumeConfig(_StrictModel):
    relative_window: int = Field(ge=1)


class FundingFeatureConfig(_StrictModel):
    z_window: int = Field(ge=3)
    sum_periods: int = Field(ge=1)
    max_age_intervals: float = Field(gt=0)


class OpenInterestFeatureConfig(_StrictModel):
    max_staleness_seconds: int = Field(ge=1)
    change_hours: tuple[int, ...]
    z_window_hours: int = Field(ge=2)
    z_min_valid_fraction: float = Field(gt=0, le=1)

    _check = field_validator("change_hours")(_positive_unique)


class FeaturesConfig(_StrictModel):
    version: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    warmup_factor: float = Field(ge=1)
    returns: ReturnsConfig
    volatility: VolatilityConfig
    trend: TrendConfig
    momentum: MomentumConfig
    volume: VolumeConfig
    funding: FundingFeatureConfig
    open_interest: OpenInterestFeatureConfig

    def warmup(self, period: int) -> int:
        """Number of valid inputs a recursive indicator of ``period`` needs before it emits values."""
        return max(period, math.ceil(self.warmup_factor * period))

    def config_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_features_config(config_dir: Path | str | None = None) -> FeaturesConfig:
    config_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    return FeaturesConfig.model_validate(_read_yaml(config_dir / FEATURES_FILE))

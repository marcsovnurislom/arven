"""Configuration models and loader.

Configuration lives in YAML files under ``config/``. Models are strict (unknown keys are rejected)
and frozen (immutable after loading). ``AppConfig.config_hash()`` gives a reproducible fingerprint
of everything that can influence results, recorded with every backtest / model run.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from arven.core.time import to_utc_datetime
from arven.core.timeframes import Timeframe

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_FILES = ("default.yaml", "costs.yaml", "splits.yaml")


class _StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- default.yaml -------------------------------------------------------------------------------


class ProjectConfig(_StrictModel):
    name: str
    random_seed: int


class MarketConfig(_StrictModel):
    exchange: Literal["binance"]
    market_type: Literal["usdm_perpetual"]
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    base_timeframe: Literal[Timeframe.M1]
    feature_timeframes: tuple[Timeframe, ...] = Field(min_length=1)
    decision_timeframe: Timeframe
    context_timeframe: Timeframe

    @model_validator(mode="after")
    def _check_timeframes(self) -> MarketConfig:
        if len(set(self.feature_timeframes)) != len(self.feature_timeframes):
            raise ValueError("feature_timeframes contains duplicates")
        for name in ("decision_timeframe", "context_timeframe"):
            if getattr(self, name) not in self.feature_timeframes:
                raise ValueError(f"{name} must be one of feature_timeframes")
        if self.context_timeframe.duration <= self.decision_timeframe.duration:
            raise ValueError("context_timeframe must be longer than decision_timeframe")
        return self


class DataConfig(_StrictModel):
    data_dir: Path
    history_start: datetime
    history_end: datetime
    bar_availability_delay_seconds: int = Field(ge=0)
    # Binance OI snapshots are stamped with the snapshot time but published with an unknown lag;
    # the value stamped T is treated as usable only from T + this delay.
    open_interest_availability_delay_seconds: int = Field(ge=0)

    @field_validator("history_start", "history_end", mode="before")
    @classmethod
    def _coerce_utc(cls, value: Any) -> datetime:
        return to_utc_datetime(value)

    @model_validator(mode="after")
    def _check_range(self) -> DataConfig:
        if self.history_start >= self.history_end:
            raise ValueError("data.history_start must be before data.history_end")
        return self

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def parquet_dir(self) -> Path:
        return self.data_dir / "parquet"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "arven.duckdb"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def bar_availability_delay(self) -> timedelta:
        return timedelta(seconds=self.bar_availability_delay_seconds)


class DownloadConfig(_StrictModel):
    base_url: str = Field(pattern=r"^https?://")
    rest_base_url: str = Field(pattern=r"^https?://")  # Stage 8: live REST tail updates (klines, funding)
    timeout_seconds: float = Field(gt=0, le=600)
    max_attempts: int = Field(ge=1, le=20)
    backoff_initial_seconds: float = Field(ge=0)
    backoff_multiplier: float = Field(ge=1)
    backoff_max_seconds: float = Field(ge=0)
    crosscheck_timeframes: tuple[Timeframe, ...]


# --- costs.yaml ---------------------------------------------------------------------------------

OrderType = Literal["maker", "taker"]


class FeeConfig(_StrictModel):
    # Bounds are sanity checks against unit mistakes (e.g. 0.05 meaning percent vs bps).
    maker_fee_bps: float = Field(ge=-10.0, le=100.0)
    taker_fee_bps: float = Field(ge=0.0, le=100.0)
    entry_order_type: OrderType
    exit_order_type: OrderType
    stop_order_type: Literal["taker"]

    def fee_bps(self, order_type: OrderType) -> float:
        return self.maker_fee_bps if order_type == "maker" else self.taker_fee_bps


class SlippageConfig(_StrictModel):
    model: Literal["fixed_plus_volatility"]
    fixed_bps: float = Field(ge=0.0, le=100.0)
    volatility_multiplier: float = Field(ge=0.0, le=10.0)
    stress_multiplier: float = Field(ge=1.0, le=20.0)


class FundingConfig(_StrictModel):
    source: Literal["historical"]
    missing_policy: Literal["error", "assume_rate"]
    assumed_rate_bps: float = Field(ge=-100.0, le=100.0)
    default_interval_hours: int = Field(gt=0, le=24)


class CostsConfig(_StrictModel):
    fees: FeeConfig
    slippage: SlippageConfig
    funding: FundingConfig


# --- splits.yaml --------------------------------------------------------------------------------


class Period(_StrictModel):
    """Half-open UTC interval ``[start, end)``."""

    start: datetime
    end: datetime

    @field_validator("start", "end", mode="before")
    @classmethod
    def _coerce_utc(cls, value: Any) -> datetime:
        return to_utc_datetime(value)

    @model_validator(mode="after")
    def _check_order(self) -> Period:
        if self.start >= self.end:
            raise ValueError(f"period start {self.start} must be before end {self.end}")
        return self

    def contains(self, t: datetime) -> bool:
        return self.start <= t < self.end


class HoldoutPeriod(Period):
    """The final test period. ``sealed`` marks it as reserved for final evaluation only."""

    sealed: bool


class SplitsConfig(_StrictModel):
    development: Period
    validation: Period
    test: HoldoutPeriod
    forward_start: datetime

    @field_validator("forward_start", mode="before")
    @classmethod
    def _coerce_utc(cls, value: Any) -> datetime:
        return to_utc_datetime(value)

    @model_validator(mode="after")
    def _check_chronology(self) -> SplitsConfig:
        if self.development.end > self.validation.start:
            raise ValueError("development must end before or when validation starts")
        if self.validation.end > self.test.start:
            raise ValueError("validation must end before or when test starts")
        if self.test.end > self.forward_start:
            raise ValueError("test must end before or when forward period starts")
        return self


# --- application config -------------------------------------------------------------------------


class AppConfig(_StrictModel):
    project: ProjectConfig
    market: MarketConfig
    data: DataConfig
    download: DownloadConfig
    costs: CostsConfig
    splits: SplitsConfig

    @model_validator(mode="after")
    def _check_history_covers_splits(self) -> AppConfig:
        if self.splits.development.start < self.data.history_start:
            raise ValueError("development period starts before data.history_start")
        if self.splits.test.end > self.data.history_end:
            raise ValueError("test period ends after data.history_end")
        return self

    def config_hash(self) -> str:
        """SHA-256 of all result-relevant settings (machine-specific paths and transport settings excluded)."""
        payload = self.model_dump(mode="json", exclude={"data": {"data_dir"}, "download": True})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        content = yaml.safe_load(fh)
    if not isinstance(content, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return content


def load_config(config_dir: Path | str | None = None) -> AppConfig:
    """Load and validate ``default.yaml``, ``costs.yaml`` and ``splits.yaml`` from ``config_dir``.

    A relative ``data.data_dir`` is resolved against the parent of ``config_dir`` (the project root).
    """
    config_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    default = _read_yaml(config_dir / "default.yaml")
    costs = _read_yaml(config_dir / "costs.yaml")
    splits = _read_yaml(config_dir / "splits.yaml")

    data_section = dict(default.get("data") or {})
    if "data_dir" in data_section:
        data_dir = Path(data_section["data_dir"])
        if not data_dir.is_absolute():
            data_dir = (config_dir.resolve().parent / data_dir).resolve()
        data_section["data_dir"] = data_dir
    default["data"] = data_section

    return AppConfig.model_validate({**default, "costs": costs, "splits": splits})

"""Backtest configuration (``config/backtest.yaml``).

Kept separate from :class:`arven.core.config.AppConfig` (like the feature configuration) so that
``AppConfig.config_hash()`` and everything recorded with it in earlier stages stay unchanged.
Fee, slippage and funding parameters stay in ``costs.yaml``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from arven.core.config import DEFAULT_CONFIG_DIR, _read_yaml, _StrictModel

BACKTEST_FILE = "backtest.yaml"


class BuyAndHoldConfig(_StrictModel):
    notional_fraction: float = Field(gt=0)


class RandomEntryConfig(_StrictModel):
    n_seeds: int = Field(ge=1)
    n_trades: int = Field(ge=1)
    holding_minutes: int = Field(ge=1)
    direction_mode: Literal["random_50_50"]
    notional_fraction: float = Field(gt=0)


class BaselinesConfig(_StrictModel):
    buy_and_hold: BuyAndHoldConfig
    random_entry: RandomEntryConfig


class BacktestConfig(_StrictModel):
    initial_equity_usdt: float = Field(gt=0)
    leverage: float = Field(ge=1)
    margin_mode: Literal["isolated"]
    maintenance_margin_rate: float = Field(ge=0, lt=1)
    liquidation_includes_funding: bool
    qty_step_btc: float = Field(gt=0)
    min_notional_usdt: float = Field(ge=0)
    latency_minutes: int = Field(ge=0, lt=60)
    end_of_period: Literal["close_last_bar"]
    data_gap_policy: Literal["exit_at_next_open"]
    annualization_days: int = Field(gt=0)
    risk_free_rate: float
    min_days_for_ratios: int = Field(ge=2)
    min_trades_warning: int = Field(ge=0)
    baselines: BaselinesConfig

    @model_validator(mode="after")
    def _liquidation_beyond_entry(self) -> BacktestConfig:
        if self.maintenance_margin_rate >= 1.0 / self.leverage:
            raise ValueError("maintenance_margin_rate must be smaller than 1 / leverage")
        return self

    @property
    def latency_ms(self) -> int:
        return self.latency_minutes * 60_000

    def config_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_backtest_config(config_dir: Path | str | None = None) -> BacktestConfig:
    config_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    return BacktestConfig.model_validate(_read_yaml(config_dir / BACKTEST_FILE))

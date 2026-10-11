"""Live signal loop configuration (``config/live.yaml``): which strategies run, with which parameters, and how the
always-on process behaves. Secrets (Telegram token / chat ids) stay in the environment, never here."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from arven.core.config import DEFAULT_CONFIG_DIR, _read_yaml, _StrictModel

LIVE_FILE = "live.yaml"


class LiveStrategyConfig(_StrictModel):
    id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")  # signal-store folder name; never reuse an id for different rules
    kind: str  # registry key in arven.live.registry (what code runs)
    enabled: bool = True
    version: str = Field(default="v1", min_length=1)  # bump it whenever the rules or params change
    title: str = ""
    params: dict[str, Any] = Field(default_factory=dict)

    def params_hash(self) -> str:
        canonical = json.dumps({"kind": self.kind, "version": self.version, "params": self.params}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LiveTelegramConfig(_StrictModel):
    enabled: bool = True  # queue alerts (sending itself follows config/telegram.yaml dry_run and the .env secrets)
    send_updates: bool = True  # also TP hit / stop moved / filled / cancelled / closed
    commands: bool = True  # answer bot commands from the allow-listed chats
    daily_summary_hour_utc: int | None = Field(default=0, ge=0, le=23)


class LiveConfig(_StrictModel):
    poll_seconds: float = Field(default=20.0, ge=1.0, le=600.0)
    event_delay_seconds: int = Field(default=5, ge=0, le=600)  # wait this long after a 15m close before evaluating it
    max_data_age_seconds: int = Field(default=180, ge=60)  # newest 1m bar older than this => stale => no new signals
    alert_recency_hours: float = Field(default=6.0, gt=0)  # catch-up signals older than this are stored, never alerted
    cost_profile: str = "costs_cfd_justmarkets.yaml"  # file in config/ used to resolve signals in R
    include_open_interest: bool = True  # REST-tail open interest (needed by Crowded Shorts' oi_z)
    run_legacy_paper: bool = True  # also run the Stage 8 hourly `paper run` in this process (one DuckDB writer)
    telegram: LiveTelegramConfig = Field(default_factory=LiveTelegramConfig)
    strategies: tuple[LiveStrategyConfig, ...] = ()

    @model_validator(mode="after")
    def _unique_ids(self) -> LiveConfig:
        ids = [s.id for s in self.strategies]
        if len(ids) != len(set(ids)):
            raise ValueError(f"strategy ids must be unique, got {ids}")
        return self

    def enabled(self) -> tuple[LiveStrategyConfig, ...]:
        return tuple(s for s in self.strategies if s.enabled)


def load_live_config(config_dir: Path | str | None = None) -> LiveConfig:
    config_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    return LiveConfig.model_validate(_read_yaml(config_dir / LIVE_FILE))


__all__ = ["LiveConfig", "LiveStrategyConfig", "LiveTelegramConfig", "load_live_config"]

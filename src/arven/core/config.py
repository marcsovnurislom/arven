"""Configuration models and loader.

Configuration lives in YAML files under ``config/``. Models are strict (unknown keys are rejected)
and frozen (immutable after loading). ``AppConfig.config_hash()`` gives a reproducible fingerprint
of everything that can influence results, recorded with every backtest / model run.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from arven.core.sessions import SessionCalendar, SessionKind
from arven.core.time import to_ms, to_utc_datetime
from arven.core.timeframes import Timeframe

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_FILES = ("default.yaml", "costs.yaml", "splits.yaml")
INSTRUMENTS_DIR = "instruments"  # config/instruments/<NAME>.yaml: per-instrument overlay (see load_config)
SESSIONS_DIR = "sessions"  # config/sessions/<session>_closures.csv: holiday / early-close windows


class _StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- default.yaml -------------------------------------------------------------------------------


class ProjectConfig(_StrictModel):
    name: str
    random_seed: int


class SessionClosure(_StrictModel):
    """A holiday or early-close window ``[start, end)`` on top of the session's regular rule (UTC, whole minutes)."""

    start: datetime
    end: datetime
    reason: str

    @field_validator("start", "end", mode="before")
    @classmethod
    def _coerce_utc(cls, value: Any) -> datetime:
        return to_utc_datetime(value)

    @model_validator(mode="after")
    def _check(self) -> SessionClosure:
        if self.start >= self.end:
            raise ValueError(f"closure start {self.start} must be before end {self.end}")
        if self.start.second or self.start.microsecond or self.end.second or self.end.microsecond:
            raise ValueError("closure bounds must be whole minutes")
        return self


class MarketConfig(_StrictModel):
    exchange: Literal["binance", "dukascopy"]
    market_type: Literal["usdm_perpetual", "spot_otc"]
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    base_timeframe: Literal[Timeframe.M1]
    feature_timeframes: tuple[Timeframe, ...] = Field(min_length=1)
    decision_timeframe: Timeframe
    context_timeframe: Timeframe
    # Trading hours (arven.core.sessions). "24x7" (BTC) is the default and is left out of config_hash, so configs
    # written before calendars existed keep their hash.
    session: SessionKind = "24x7"
    session_closures: tuple[SessionClosure, ...] = ()  # loaded from config/sessions/<session>_closures.csv
    # False for a market whose funding is absent or meaningless (gold): funding features then do not gate
    # feat_ready (arven.features.registry.build_registry). Left out of config_hash while True.
    has_funding: bool = True
    # False for a feed without trade counts / taker-buy volume (Dukascopy): those features then do not gate feat_ready.
    has_trade_flow: bool = True

    @model_validator(mode="after")
    def _check_timeframes(self) -> MarketConfig:
        if len(set(self.feature_timeframes)) != len(self.feature_timeframes):
            raise ValueError("feature_timeframes contains duplicates")
        for name in ("decision_timeframe", "context_timeframe"):
            if getattr(self, name) not in self.feature_timeframes:
                raise ValueError(f"{name} must be one of feature_timeframes")
        if self.context_timeframe.duration <= self.decision_timeframe.duration:
            raise ValueError("context_timeframe must be longer than decision_timeframe")
        if self.session == "24x7" and self.session_closures:
            raise ValueError("a 24x7 market cannot have session closures")
        if (self.exchange == "dukascopy") != (self.market_type == "spot_otc"):
            raise ValueError("market_type spot_otc goes with exchange dukascopy, usdm_perpetual with binance")
        return self

    def session_calendar(self) -> SessionCalendar:
        return _calendar(self.session, tuple((to_ms(c.start), to_ms(c.end)) for c in self.session_closures))


@lru_cache(maxsize=16)
def _calendar(kind: SessionKind, closures: tuple[tuple[int, int], ...]) -> SessionCalendar:
    return SessionCalendar(kind, closures)


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


class DukascopyConfig(_StrictModel):
    """Dukascopy public datafeed (``<base_url>/<instrument>/<YYYY>/<MM-1>/<DD>/<BID|ASK>_candles_min_1.bi5``)."""

    base_url: str = Field(pattern=r"^https?://")
    instrument: str = Field(pattern=r"^[A-Z0-9]+$")
    point: int = Field(gt=0)  # stored integer prices / point = price (XAUUSD: 1000)
    request_interval_seconds: float = Field(ge=0.0, le=60.0)  # politeness pause before each request, per worker
    workers: int = Field(ge=1, le=8)  # parallel downloads
    timeout_seconds: float = Field(gt=0, le=600)
    max_attempts: int = Field(ge=1, le=30)
    backoff_max_seconds: float = Field(ge=0)


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
    source: Literal["historical", "none"]  # none: no funding events (a CFD; see backtest.marketdata.funding_schedule)
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
    instrument: str | None = None  # name of the config/instruments overlay; None = the default (BTCUSDT) config
    dukascopy: DukascopyConfig | None = None  # required when market.exchange is dukascopy

    @model_validator(mode="after")
    def _check_history_covers_splits(self) -> AppConfig:
        if self.splits.development.start < self.data.history_start:
            raise ValueError("development period starts before data.history_start")
        if self.splits.test.end > self.data.history_end:
            raise ValueError("test period ends after data.history_end")
        if (self.market.exchange == "dukascopy") != (self.dukascopy is not None):
            raise ValueError("a dukascopy section is required exactly when market.exchange is dukascopy")
        return self

    def config_hash(self) -> str:
        """SHA-256 of all result-relevant settings (machine-specific paths and transport settings excluded).

        Settings added for multi-instrument support are left out while they hold their defaults, so the default
        (BTCUSDT) configuration keeps the hash it had before (pinned in ``tests/unit/test_config.py``)."""
        payload = self.model_dump(mode="json", exclude={"data": {"data_dir"}, "download": True})
        if payload["market"]["session"] == "24x7":
            del payload["market"]["session"]
        if not payload["market"]["session_closures"]:
            del payload["market"]["session_closures"]
        for flag in ("has_funding", "has_trade_flow"):
            if payload["market"][flag]:
                del payload["market"][flag]
        for name in ("instrument", "dukascopy"):
            if payload[name] is None:
                del payload[name]
        if "dukascopy" in payload:  # only what changes the stored prices; the rest is transport
            payload["dukascopy"] = {k: payload["dukascopy"][k] for k in ("instrument", "point")}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def session_calendar(self) -> SessionCalendar:
        return self.market.session_calendar()


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        content = yaml.safe_load(fh)
    if not isinstance(content, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return content


_OVERLAY_KEYS = frozenset({"market", "dukascopy", "costs_file"})


def _read_closures(path: Path) -> list[dict[str, str]]:
    """``start_utc,end_utc,reason,source`` rows (the ``source`` column documents provenance and is not loaded)."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(line for line in fh if not line.startswith("#")))
    return [{"start": r["start_utc"], "end": r["end_utc"], "reason": r["reason"]} for r in rows]


def instrument_names(config_dir: Path | str | None = None) -> list[str]:
    """Names of the instrument overlays in ``config/instruments``."""
    d = (Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR) / INSTRUMENTS_DIR
    return sorted(p.stem for p in d.glob("*.yaml")) if d.is_dir() else []


def load_config(config_dir: Path | str | None = None, instrument: str | None = None) -> AppConfig:
    """Load and validate ``default.yaml``, ``costs.yaml`` and ``splits.yaml`` from ``config_dir``.

    A relative ``data.data_dir`` is resolved against the parent of ``config_dir`` (the project root).

    ``instrument`` names an overlay ``config/instruments/<instrument>.yaml`` for a second market (e.g. gold): its
    ``market`` keys replace those of ``default.yaml`` (symbol, exchange, session...), an optional ``dukascopy``
    section configures that data source, and an optional ``costs_file`` replaces ``costs.yaml``. Everything else
    (data directory, database, splits, transport) is shared. A non-24x7 session also loads its holiday and
    early-close windows from ``config/sessions/<session>_closures.csv``.
    """
    config_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    default = _read_yaml(config_dir / "default.yaml")
    costs_name = "costs.yaml"
    if instrument is not None:
        overlay = _read_yaml(config_dir / INSTRUMENTS_DIR / f"{instrument}.yaml")
        unknown = set(overlay) - _OVERLAY_KEYS
        if unknown:
            raise ValueError(f"instrument {instrument}: unknown overlay keys {sorted(unknown)}")
        default["market"] = {**dict(default.get("market") or {}), **dict(overlay.get("market") or {})}
        if "dukascopy" in overlay:
            default["dukascopy"] = overlay["dukascopy"]
        costs_name = overlay.get("costs_file", costs_name)
        default["instrument"] = instrument
    session = (default.get("market") or {}).get("session", "24x7")
    if session != "24x7":
        default["market"]["session_closures"] = _read_closures(config_dir / SESSIONS_DIR / f"{session}_closures.csv")
    costs = _read_yaml(config_dir / costs_name)
    splits = _read_yaml(config_dir / "splits.yaml")

    data_section = dict(default.get("data") or {})
    if "data_dir" in data_section:
        data_dir = Path(data_section["data_dir"])
        if not data_dir.is_absolute():
            data_dir = (config_dir.resolve().parent / data_dir).resolve()
        data_section["data_dir"] = data_dir
    default["data"] = data_section

    return AppConfig.model_validate({**default, "costs": costs, "splits": splits})

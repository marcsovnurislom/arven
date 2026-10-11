"""The live strategy contract: what every strategy plugged into the live loop implements, and the data it gets.

A strategy is a small object with two methods - ``scan`` (which signals did the decision times in ``(after, through]``
produce?) and ``resolve`` (where is a stored signal now: filled, TP hit, cancelled, closed?). Everything a strategy
reads comes from :class:`LiveContext`, built once per tick from the database: bars of every timeframe since the
start of history (so recursive indicators are seeded exactly as in research), the forward-period 1m market for
resolution, and - computed only if a strategy asks - the Stage 3 feature table. Nothing here touches the network,
the wall clock or any order endpoint; the composition root (``arven.live.service``) does the I/O.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from arven.backtest.marketdata import MarketData
from arven.core.config import AppConfig, CostsConfig
from arven.core.features_config import FeaturesConfig
from arven.core.series import BarSeries
from arven.core.splitguard import AllowedWindow
from arven.core.timeframes import Timeframe
from arven.engine.signal import EngineSignal
from arven.engine.signal_events import SignalUpdate


@dataclass(frozen=True, slots=True)
class LiveOutcome:
    """Where one stored signal stands after replaying the data available now."""

    signal: EngineSignal
    updates: tuple[SignalUpdate, ...]  # every update so far, oldest first (the caller appends the new ones)
    state: str  # "pending" (resting limit) | "open" | "closed" | "cancelled"
    net_r: float | None = None  # net R once closed (None while open, and for a cancelled signal)


@dataclass(eq=False)
class LiveContext:
    """The data of one tick. ``bars``: every timeframe from the start of history to the last closed bar;
    ``market``: 1m bars of the forward window (signals are resolved on these); ``through_ms``: the last 15m close
    whose 1m data is complete - nothing later is ever evaluated."""

    app: AppConfig
    fcfg: FeaturesConfig
    costs: CostsConfig
    window: AllowedWindow
    bars: dict[Timeframe, BarSeries]
    market: MarketData
    through_ms: int
    feature_version: str
    config_hash: str
    git_commit: str | None
    features_loader: Callable[[], Any] | None = None  # -> arven.backtest.types.FeatureData of the forward window
    cache: dict[str, Any] = field(default_factory=dict)  # per-tick memo shared by scan/resolve (e.g. detected setups)

    def features(self) -> Any:
        if "features" not in self.cache:
            if self.features_loader is None:
                raise RuntimeError("no feature loader configured for this tick")
            self.cache["features"] = self.features_loader()
        return self.cache["features"]


class LiveStrategy(Protocol):
    strategy_id: str
    title: str

    def scan(self, ctx: LiveContext, after_ms: int, through_ms: int, stored: list[EngineSignal]) -> list[EngineSignal]:
        """Signals whose decision time is in ``(after_ms, through_ms]``, oldest first. ``stored``: this strategy's
        signals already in the store (for cooldowns); a signal already stored may be returned again, the caller
        de-duplicates by ``signal_id``."""
        ...

    def resolve(self, ctx: LiveContext, signal: EngineSignal) -> LiveOutcome | None:
        """The signal's state on the data in ``ctx`` (``None``: nothing can be said yet, e.g. its entry minute is
        not stored yet)."""
        ...


__all__ = ["LiveContext", "LiveOutcome", "LiveStrategy"]

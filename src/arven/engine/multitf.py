"""``MultiTFView``: what a strategy may see at one decision instant, across its timeframes.

For a decision time ``t`` and each timeframe a :class:`~arven.engine.spec.StrategySpec` declares
(``trigger_tf``, ``setup_tf``, ``context_tfs``), the view returns that timeframe's **last closed-and-available
row**: the last row of its :class:`~arven.engine.features.TFFeatureTable` with ``available_at_ms <= t``,
found by the project's single backward as-of primitive (:func:`arven.features.asof.asof_index`). For the
trigger timeframe, at its own bar-close event, that row *is* the bar that just closed.

Three outcomes per requested timeframe - deliberately kept distinct:

1. **No row at all** (``available_at <= t`` holds for no row: ``t`` is before the first stored bar of that
   timeframe has closed, or its table is empty) -> :class:`~arven.engine.errors.LookAheadError`. The only
   row that could fill this slot would be one from the future, so the view refuses rather than return
   something that looks like a reading. The caller (the Phase 3 engine) treats this as ``NO_TRADE``.
2. **A row exists but is stale** (``t - available_at >= tf.ms``: a newer bar of that timeframe should
   already be available but is not in the data, e.g. the feed stopped) -> the row is returned with
   ``stale=True`` and **all values NaN** - never carried forward. This mirrors the Stage 3 builder exactly
   (``asof_join(..., max_age_ms=tf.ms - 1)``).
3. **A fresh row** -> returned as is. Individual values may still be NaN (indicator warm-up, a missing or
   incomplete bar, a zero division): that is a *defined* reading under the Stage 3 convention ("NaN in,
   NaN out", never raise), already leakage-tested, and strategies must treat NaN as "no signal".

Warm-up in the ``StrategySpec.warmup_bars`` sense is not enforced here; every row reports ``bars_seen`` (its
1-based position in the regularized grid) so the engine can apply that gate.

Same-instant closes: a coarser bar closing exactly at ``t`` (e.g. a 4h bar closing at 08:00 seen from the
08:00 1h trigger) has ``available_at == t`` (zero delay) and is therefore **visible** (``<=``, not ``<``) -
consistent with the coarsest-first tie rule of :class:`~arven.engine.clock.SimulatedEventClock`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from arven.core.series import BarSeries
from arven.core.timeframes import Timeframe
from arven.engine.errors import LookAheadError
from arven.engine.events import BarCloseEvent
from arven.engine.features import DEFAULT_PARAMS, TFFeatureParams, TFFeatureTable, compute_tf_features
from arven.engine.spec import StrategySpec
from arven.features.asof import asof_index


@dataclass(frozen=True, slots=True)
class TFRow:
    """One timeframe's row as seen at ``as_of_ms``."""

    timeframe: Timeframe
    as_of_ms: int
    open_ms: int
    close_ms: int
    available_at_ms: int
    bars_seen: int  # 1-based position of this row in the timeframe's regularized grid
    complete: bool  # False: the bar was missing or built from incomplete data (values NaN)
    stale: bool  # True: a newer bar should be available but is not; values are all NaN
    values: Mapping[str, float]

    def __getitem__(self, name: str) -> float:
        return self.values[name]


@dataclass(frozen=True, slots=True)
class MultiTFSnapshot:
    """The rows a strategy may read at ``t_ms``: its trigger row, its setup row and its context rows."""

    t_ms: int
    trigger: TFRow
    setup: TFRow
    context: tuple[TFRow, ...]  # same order as StrategySpec.context_tfs

    def row(self, tf: Timeframe) -> TFRow:
        for r in (self.trigger, self.setup, *self.context):
            if r.timeframe == tf:
                return r
        raise KeyError(f"timeframe {tf} is not part of this snapshot")


class MultiTFView:
    """Read-only, point-in-time access to per-timeframe feature tables."""

    def __init__(self, tables: Mapping[Timeframe, TFFeatureTable]) -> None:
        for tf, table in tables.items():
            if table.timeframe != tf:
                raise ValueError(f"table stored under {tf} has timeframe {table.timeframe}")
        self._tables: dict[Timeframe, TFFeatureTable] = dict(tables)

    @classmethod
    def from_bars(
        cls,
        bars: Mapping[Timeframe, BarSeries],
        timeframes: Iterable[Timeframe],
        params: TFFeatureParams = DEFAULT_PARAMS,
    ) -> MultiTFView:
        """Compute the feature table of each requested timeframe from its own bar series."""
        return cls({tf: compute_tf_features(bars[tf], params) for tf in dict.fromkeys(timeframes)})

    @property
    def timeframes(self) -> tuple[Timeframe, ...]:
        return tuple(self._tables)

    def table(self, tf: Timeframe) -> TFFeatureTable:
        return self._tables[tf]

    def row_at(self, tf: Timeframe, t_ms: int) -> TFRow:
        """The last row of ``tf`` with ``available_at <= t_ms`` (see the module docstring for the three cases)."""
        if tf not in self._tables:
            raise KeyError(f"no feature table for timeframe {tf}")
        table = self._tables[tf]
        t = int(t_ms)
        i = int(asof_index(table.available_at_ms, np.array([t], dtype=np.int64))[0])
        if i < 0:
            raise LookAheadError(f"no closed {tf} bar is available at t={t}")
        available_at = int(table.available_at_ms[i])
        if available_at > t:  # cannot happen via asof_index; kept as an explicit invariant
            raise LookAheadError(f"{tf} row available at {available_at} requested at t={t}")
        stale = t - available_at >= tf.ms
        if stale:
            values = dict.fromkeys(table.names, float("nan"))
        else:
            values = {name: float(v) for name, v in zip(table.names, table.values[i], strict=True)}
        return TFRow(
            timeframe=tf,
            as_of_ms=t,
            open_ms=int(table.open_ms[i]),
            close_ms=int(table.close_ms[i]),
            available_at_ms=available_at,
            bars_seen=i + 1,
            complete=bool(table.complete[i]),
            stale=stale,
            values=MappingProxyType(values),
        )

    def at(self, t_ms: int, spec: StrategySpec) -> MultiTFSnapshot:
        """Every row ``spec`` may read at ``t_ms``. Raises :class:`LookAheadError` if any is missing."""
        cache: dict[Timeframe, TFRow] = {}

        def get(tf: Timeframe) -> TFRow:
            if tf not in cache:
                cache[tf] = self.row_at(tf, t_ms)
            return cache[tf]

        return MultiTFSnapshot(
            t_ms=int(t_ms),
            trigger=get(spec.trigger_tf),
            setup=get(spec.setup_tf),
            context=tuple(get(tf) for tf in spec.context_tfs),
        )

    def for_event(self, event: BarCloseEvent, spec: StrategySpec) -> MultiTFSnapshot:
        """The snapshot for ``spec`` at its own trigger event, as of the moment the event's bar became
        available (``event.available_at_ms``). If the trigger bar itself is absent from the data the trigger
        row is the previous bar and therefore ``stale`` (all NaN)."""
        if event.timeframe != spec.trigger_tf:
            raise ValueError(
                f"event timeframe {event.timeframe} is not the trigger_tf {spec.trigger_tf} of {spec.strategy_id}"
            )
        return self.at(event.available_at_ms, spec)

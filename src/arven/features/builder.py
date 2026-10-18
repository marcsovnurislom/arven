"""Batch feature builder: ``MarketInputs`` + decision times -> ``FeatureTable``.

Row ``t`` (a 1h bar close) contains only information with ``available_at <= t``. The same function
serves the backtest (all decision times at once) and the live loop (one decision time, on inputs
truncated with :meth:`MarketInputs.available_until`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from arven.core.features_config import FeaturesConfig
from arven.core.series import MarketInputs
from arven.core.sessions import SessionCalendar, session_decision_mask
from arven.core.timeframes import Timeframe
from arven.features.asof import asof_join
from arven.features.bars import compute_bar_features
from arven.features.futures import HOUR_MS, compute_funding, compute_oi, compute_time
from arven.features.registry import BAR_TIMEFRAMES, READY_COLUMN, build_registry
from arven.features.spec import FeatureSpec


@dataclass(frozen=True, eq=False)
class FeatureTable:
    version: str
    t_ms: np.ndarray  # decision times (1h bar closes), int64
    columns: dict[str, np.ndarray]  # one float64 array per registered feature, in registry order
    specs: tuple[FeatureSpec, ...]

    def __len__(self) -> int:
        return len(self.t_ms)

    def content_sha256(self) -> str:
        """Hash of decision times and all columns (NaN canonicalised), independent of the file format."""
        h = hashlib.sha256()
        h.update(np.ascontiguousarray(self.t_ms, dtype=np.int64).tobytes())
        for name, col in self.columns.items():
            a = np.ascontiguousarray(col, dtype=np.float64)
            h.update(name.encode())
            h.update(np.where(np.isnan(a), np.nan, a).tobytes())
        return h.hexdigest()

    def select_rows(self, mask: np.ndarray) -> FeatureTable:
        return FeatureTable(
            self.version, self.t_ms[mask], {k: v[mask] for k, v in self.columns.items()}, self.specs
        )


def decision_grid(start_ms: int, end_ms: int, calendar: SessionCalendar | None = None) -> np.ndarray:
    """1h bar closes ``t`` with ``start <= t < end`` (the decision clock); for a session market only the times
    :func:`session_decision_mask` allows."""
    first = -(-int(start_ms) // HOUR_MS) * HOUR_MS
    grid = np.arange(first, int(end_ms), HOUR_MS, dtype=np.int64)
    return grid if calendar is None or calendar.always_open else grid[session_decision_mask(calendar, grid)]


def check_decision_times(t_ms: np.ndarray) -> np.ndarray:
    t = np.ascontiguousarray(t_ms, dtype=np.int64)
    if t.ndim != 1:
        raise ValueError("decision times must be one-dimensional")
    if len(t) and (np.any(t % HOUR_MS != 0) or np.any(np.diff(t) <= 0)):
        raise ValueError("decision times must be strictly increasing whole hours (1h bar closes)")
    return t


def market_open_at_decision(inputs: MarketInputs, t: np.ndarray) -> np.ndarray:
    """:func:`session_decision_mask` for the market the inputs come from (a second guard: a session market's
    decision grid already contains only these times)."""
    return session_decision_mask(inputs.bars[Timeframe.H1].calendar, t)


def build_features(
    inputs: MarketInputs, t_ms: np.ndarray, cfg: FeaturesConfig, *, funding_required: bool = True,
    trade_flow_required: bool = True,
) -> FeatureTable:
    """``funding_required`` / ``trade_flow_required``: see :func:`arven.features.registry.build_registry` (both
    follow ``AppConfig.market.has_funding`` / ``has_trade_flow``). For a session market the bar
    features age by the session grid (the bar before a closure is not stale while the market is shut) and
    ``feat_ready`` is 0 whenever the market is closed at the decision time (NO_TRADE)."""
    t = check_decision_times(t_ms)
    specs = build_registry(cfg, funding_required, trade_flow_required)
    columns: dict[str, np.ndarray] = {}

    for tf in BAR_TIMEFRAMES:
        regular = inputs.bars[tf].regularized()
        if regular.session:
            max_age: int | np.ndarray = regular.next_open_ms(regular.open_time_ms) - regular.open_time_ms - 1
        else:
            max_age = tf.ms - 1
        for name, values in compute_bar_features(tf, regular, cfg).items():
            columns[name] = asof_join(regular.available_at_ms, values, t, max_age_ms=max_age)

    columns |= compute_funding(inputs.funding, t, cfg)
    columns |= compute_oi(inputs.open_interest, t, cfg)
    columns |= compute_time(t)

    required = [s.name for s in specs if s.required]
    ready = market_open_at_decision(inputs, t)
    for name in required:
        ready &= np.isfinite(columns[name])
    columns[READY_COLUMN] = ready.astype(np.float64)

    expected = [s.name for s in specs]
    if set(columns) != set(expected):
        raise RuntimeError(
            f"feature groups and registry disagree: extra={sorted(set(columns) - set(expected))} "
            f"missing={sorted(set(expected) - set(columns))}"
        )
    return FeatureTable(cfg.version, t, {name: columns[name] for name in expected}, specs)

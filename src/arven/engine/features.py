"""Per-timeframe causal feature tables (``features_<tf>``) for the event-driven engine.

One generic function, :func:`compute_tf_features`, computes the same small, fixed indicator set for **any**
timeframe: it is parametrised by the ``BarSeries`` it is given, never by a per-timeframe table (unlike the
frozen Stage 3 set in ``arven.features.bars``, which this module neither imports nor changes).

Pipeline per timeframe, exactly the Stage 3 convention:

1. ``BarSeries.regularized()`` - a gap-free grid from the first to the last stored bar; missing or incomplete
   bars become NaN rows (``complete=False``), so ``shift(k)`` always means "k bars earlier";
2. the causal numpy primitives of ``arven.features.indicators`` (``output[i]`` depends only on
   ``input[:i+1]``; NaN in, NaN out; recursive indicators are seeded at the first stored bar and emit only
   after their warm-up);
3. non-finite results become NaN.

Each row describes one bar of that timeframe and carries the bar's ``open_ms``, ``close_ms`` and
``available_at_ms`` (``= close_ms + delay_ms``, straight from ``BarSeries.available_at_ms``). Joining a row
onto a decision time is the job of :mod:`arven.engine.multitf`, never of this module.

**Column naming.** Inside a table, names are unqualified and carry their parameters (``adx_14``,
``ema_dist_20``...). Wherever columns of several timeframes meet, :func:`qualified_name` gives
``"<tf>.<name>"`` (e.g. ``"4h.adx_14"``). A dot never appears in a Stage 3 column name (``h4_adx``...), so
the two feature sets can never collide even if one day used side by side.

**Columns** (``p = TFFeatureParams``, every one a pure function of the bar's own history):

- ``close``                  - the bar's close (price level for stops/targets in later phases);
- ``atr_<atr_period>``       - Wilder ATR (absolute, price units; for ATR-buffered stops);
- ``atr_pct_<atr_period>``   - ATR / close (volatility, comparable across time);
- ``ema_dist_<ema_fast>``    - log(close / EMA_fast);
- ``ema_dist_<ema_slow>``    - log(close / EMA_slow);
- ``ema_slope_<ema_slow>``   - log(EMA_slow / EMA_slow ``slope_bars`` bars earlier);
- ``adx_<adx_period>``       - Wilder ADX (trend strength).

These are the indicator families the existing regime detector actually reads (ADX, EMA distance/slope) plus
ATR for volatility-normalised stops - deliberately minimal; later phases add columns with a new
``FEATURE_SET_VERSION``.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np

from arven.core.series import BarSeries
from arven.core.timeframes import Timeframe
from arven.features import indicators as ind

FEATURE_SET_VERSION = "tf-v1"


@dataclass(frozen=True, slots=True)
class TFFeatureParams:
    """Indicator parameters. Defaults mirror the Stage 3 conventions (``config/features.yaml``: ATR/ADX 14,
    EMA 20/50, ``warmup_factor`` 5)."""

    ema_fast: int = 20
    ema_slow: int = 50
    slope_bars: int = 5
    adx_period: int = 14
    atr_period: int = 14
    warmup_factor: float = 5.0

    def __post_init__(self) -> None:
        if self.ema_fast < 1 or self.ema_slow < 1:
            raise ValueError("EMA periods must be >= 1")
        if self.ema_fast >= self.ema_slow:
            raise ValueError("ema_fast must be smaller than ema_slow")
        if self.slope_bars < 1:
            raise ValueError("slope_bars must be >= 1")
        if self.adx_period < 2 or self.atr_period < 2:
            raise ValueError("ADX/ATR periods must be >= 2")
        if self.warmup_factor < 1:
            raise ValueError("warmup_factor must be >= 1")

    def warmup(self, period: int) -> int:
        """Valid inputs a recursive indicator of ``period`` needs before emitting (same rule as Stage 3)."""
        return max(period, math.ceil(self.warmup_factor * period))


DEFAULT_PARAMS = TFFeatureParams()


def feature_names(params: TFFeatureParams = DEFAULT_PARAMS) -> tuple[str, ...]:
    p = params
    return (
        "close",
        f"atr_{p.atr_period}",
        f"atr_pct_{p.atr_period}",
        f"ema_dist_{p.ema_fast}",
        f"ema_dist_{p.ema_slow}",
        f"ema_slope_{p.ema_slow}",
        f"adx_{p.adx_period}",
    )


def qualified_name(tf: Timeframe, name: str) -> str:
    """``"<tf>.<name>"``, e.g. ``"4h.adx_14"`` - the cross-timeframe column name."""
    return f"{tf.value}.{name}"


@dataclass(frozen=True, eq=False)
class TFFeatureTable:
    """One timeframe's features, one row per bar of the regularized grid (``values[i, j]`` = column
    ``names[j]`` for the bar ``open_ms[i]``)."""

    timeframe: Timeframe
    version: str
    open_ms: np.ndarray
    close_ms: np.ndarray
    available_at_ms: np.ndarray
    complete: np.ndarray
    names: tuple[str, ...]
    values: np.ndarray
    # When each row is superseded: the time its successor on the market's bar grid becomes available. None =
    # around the clock (``available_at + tf``). A session market's last bar before a weekend stays current until the
    # first bar after the weekend could have closed, so it is not "stale" while the market is shut.
    superseded_at_ms: np.ndarray | None = None

    def __post_init__(self) -> None:
        n = len(self.open_ms)
        for what in ("close_ms", "available_at_ms", "complete"):
            if len(getattr(self, what)) != n:
                raise ValueError(f"{what} has length {len(getattr(self, what))}, expected {n}")
        if self.values.shape != (n, len(self.names)):
            raise ValueError(f"values has shape {self.values.shape}, expected {(n, len(self.names))}")
        if len(set(self.names)) != len(self.names):
            raise ValueError("column names must be unique")
        if n > 1 and np.any(np.diff(self.available_at_ms) <= 0):
            raise ValueError("available_at_ms must be strictly increasing")
        if n and np.any(self.close_ms != self.open_ms + self.timeframe.ms):
            raise ValueError("close_ms must equal open_ms + timeframe duration")
        if n and np.any(self.available_at_ms < self.close_ms):
            raise ValueError("available_at_ms must not be earlier than close_ms")
        if self.superseded_at_ms is not None and (
            len(self.superseded_at_ms) != n or (n and np.any(self.superseded_at_ms < self.available_at_ms + self.timeframe.ms))
        ):
            raise ValueError("superseded_at_ms must have one entry per row, each >= available_at + timeframe")

    def superseded_at(self, i: int) -> int:
        """When row ``i`` stops being the current bar of this timeframe."""
        if self.superseded_at_ms is None:
            return int(self.available_at_ms[i]) + self.timeframe.ms
        return int(self.superseded_at_ms[i])

    def __len__(self) -> int:
        return len(self.open_ms)

    def column(self, name: str) -> np.ndarray:
        return self.values[:, self.names.index(name)]

    def content_sha256(self) -> str:
        """Hash of row times and every column (NaN canonicalised)."""
        h = hashlib.sha256()
        h.update(f"{self.timeframe.value}:{self.version}:{','.join(self.names)}".encode())
        for a in (self.open_ms, self.available_at_ms):
            h.update(np.ascontiguousarray(a, dtype=np.int64).tobytes())
        h.update(np.ascontiguousarray(self.complete, dtype=bool).tobytes())
        v = np.ascontiguousarray(self.values, dtype=np.float64)
        h.update(np.where(np.isnan(v), np.nan, v).tobytes())
        if self.superseded_at_ms is not None:  # session markets only; around the clock the hash is unchanged
            h.update(np.ascontiguousarray(self.superseded_at_ms, dtype=np.int64).tobytes())
        return h.hexdigest()


def compute_tf_features(bars: BarSeries, params: TFFeatureParams = DEFAULT_PARAMS) -> TFFeatureTable:
    """The per-timeframe feature table of ``bars`` (any timeframe; the same code for all)."""
    p = params
    r = bars.regularized()
    h, lo, c = r.high, r.low, r.close
    atr = ind.atr(h, lo, c, p.atr_period, p.warmup(p.atr_period))
    ema_fast = ind.ema(c, p.ema_fast, p.warmup(p.ema_fast))
    ema_slow = ind.ema(c, p.ema_slow, p.warmup(p.ema_slow))
    cols = (
        c,
        atr,
        ind.safe_divide(atr, c),
        ind.log_ratio(c, ema_fast),
        ind.log_ratio(c, ema_slow),
        ind.log_ratio(ema_slow, ind.shift(ema_slow, p.slope_bars)),
        ind.adx(h, lo, c, p.adx_period, p.warmup(p.adx_period)),
    )
    names = feature_names(p)
    values = np.empty((len(r), len(names)), dtype=np.float64)
    for j, col in enumerate(cols):
        values[:, j] = ind.finite_or_nan(np.asarray(col, dtype=np.float64))
    return TFFeatureTable(
        timeframe=r.timeframe,
        version=FEATURE_SET_VERSION,
        open_ms=r.open_time_ms.copy(),
        close_ms=r.close_time_ms,
        available_at_ms=r.available_at_ms,
        complete=r.complete.copy(),
        names=names,
        values=values,
        superseded_at_ms=(r.next_open_ms(r.open_time_ms) + (r.timeframe.ms + r.delay_ms)) if r.session else None,
    )

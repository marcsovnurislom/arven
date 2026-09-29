"""Stateful, causal regime classifier.

``RegimeDetector.step(view, t_ms)`` must be called once per decision time, in strictly increasing order (the
same order the backtest clock advances) — it is how hysteresis/dwell state is carried forward without ever
looking at the future. Every input comes from :class:`~arven.backtest.provider.FeatureView`, which already
refuses rows after ``t_ms``; ``step`` never reads anything else.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from arven.backtest.provider import FeatureView
from arven.core.regime_config import RegimeConfig


class TrendState(StrEnum):
    UP = "TREND_UP"
    DOWN = "TREND_DOWN"
    NONE = "NO_TREND"  # also read as "RANGE" by strategies that gate on the absence of a trend


class VolState(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class Regime:
    trend: TrendState
    vol: VolState
    stress: bool
    vol_confident: bool  # False while the trailing volatility window has fewer than min_history_bars values

    @property
    def label(self) -> str:
        base = f"{self.trend.value}/{self.vol.value}"
        return f"{base}+STRESS" if self.stress else base


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def raw_trend(row: dict[str, float], cfg: RegimeConfig) -> TrendState:
    """The trend classification implied by this bar alone (no dwell/hysteresis)."""
    adx4, adx1 = row["h4_adx"], row["h1_adx"]
    slope, dist200 = row["h4_ema_slope"], row["h4_ema_dist_200"]
    if not (adx4 >= cfg.trend.adx_4h_threshold and adx1 >= cfg.trend.adx_1h_confirm_threshold):
        return TrendState.NONE
    s = _sign(slope)
    if s != 0 and s == _sign(dist200):
        return TrendState.UP if s > 0 else TrendState.DOWN
    return TrendState.NONE  # ADX is high but slope and price-vs-EMA200 disagree: no clean trend


def volatility_percentile(history: np.ndarray) -> tuple[float, int]:
    """Percentile rank (0-100) of the last value of ``history`` among its finite entries, and the valid count."""
    finite = history[np.isfinite(history)]
    n = len(finite)
    if n == 0 or not math.isfinite(history[-1]):
        return 50.0, 0
    rank = float((finite < finite[-1]).sum()) / n * 100.0
    return rank, n


def raw_vol(view: FeatureView, t_ms: int, cfg: RegimeConfig) -> tuple[VolState, bool]:
    history = view.history("h1_atr_pct", cfg.volatility.window_hours, t_ms)
    pct, n = volatility_percentile(history)
    confident = n >= cfg.volatility.min_history_bars
    if pct <= cfg.volatility.low_percentile:
        return VolState.LOW, confident
    if pct >= cfg.volatility.high_percentile:
        return VolState.HIGH, confident
    return VolState.NORMAL, confident


def raw_stress(row: dict[str, float], cfg: RegimeConfig) -> bool:
    fund_z, oi_chg = row["fund_z"], row["oi_chg_1h"]
    stressed = False
    if math.isfinite(fund_z) and abs(fund_z) >= cfg.stress.funding_z_threshold:
        stressed = True
    if math.isfinite(oi_chg) and abs(oi_chg) >= cfg.stress.oi_change_1h_threshold:
        stressed = True
    return stressed


class RegimeDetector:
    """Sequential classifier with dwell-based hysteresis. Construct once per backtest run; call
    :meth:`reset` (done automatically by the Stage 5 pipeline's ``prepare``) before reusing it for another run."""

    def __init__(self, cfg: RegimeConfig) -> None:
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self._current_trend = TrendState.NONE
        self._candidate_trend: TrendState | None = None
        self._candidate_count = 0
        self._last_t_ms: int | None = None

    def step(self, view: FeatureView, t_ms: int) -> Regime:
        if self._last_t_ms is not None and t_ms <= self._last_t_ms:
            raise ValueError("RegimeDetector.step must be called in strictly increasing time order")
        self._last_t_ms = t_ms
        row = view.row(t_ms)

        candidate = raw_trend(row, self.cfg)
        if candidate == self._current_trend:
            self._candidate_trend, self._candidate_count = None, 0
        elif candidate == self._candidate_trend:
            self._candidate_count += 1
        else:
            self._candidate_trend, self._candidate_count = candidate, 1
        if self._candidate_trend is not None and self._candidate_count >= self.cfg.min_dwell_bars:
            self._current_trend = self._candidate_trend
            self._candidate_trend, self._candidate_count = None, 0

        vol, confident = raw_vol(view, t_ms, self.cfg)
        stress = raw_stress(row, self.cfg)
        return Regime(self._current_trend, vol, stress, confident)


def classify_series(view: FeatureView, t_grid: np.ndarray, cfg: RegimeConfig) -> list[Regime]:
    """Batch helper for offline per-regime analysis: run a fresh detector over ``t_grid`` in order.

    This is exactly what happens inside a live backtest (one ``step`` per decision time, sequentially), just
    without a running strategy pipeline attached — safe to use for reporting after a run.
    """
    detector = RegimeDetector(cfg)
    return [detector.step(view, int(t)) for t in t_grid]

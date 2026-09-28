"""Generic point-in-time leakage checks.

``compute(inputs, t_ms) -> {column: array over t_ms}`` is any feature computation. Two independent checks:

- ``truncation_leaks``: the value at ``t`` computed from the full data must equal the value computed from
  only the data that was available at ``t``.
- ``perturbation_leaks``: replacing every record that became available after ``t`` with garbage must not
  change the value at ``t``.

Both compare exactly (NaN equals NaN); a column that differs at any sampled ``t`` is reported.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace

import numpy as np

from arven.core.series import BarSeries, FundingSeries, MarketInputs, OpenInterestSeries

Compute = Callable[[MarketInputs, np.ndarray], Mapping[str, np.ndarray]]


def _same(a: float, b: float) -> bool:
    return (np.isnan(a) and np.isnan(b)) or a == b


def sample_times(t_grid: np.ndarray, count: int, seed: int = 7, tail: int = 0) -> np.ndarray:
    """Seeded random subset of the decision grid (sorted), optionally always including the last ``tail`` rows."""
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(t_grid), size=min(count, len(t_grid)), replace=False)
    if tail:
        pick = np.union1d(pick, np.arange(max(len(t_grid) - tail, 0), len(t_grid)))
    return t_grid[np.sort(pick)]


def truncation_leaks(compute: Compute, inputs: MarketInputs, t_grid: np.ndarray, samples: np.ndarray) -> dict[str, list[int]]:
    full = compute(inputs, t_grid)
    index = {int(t): i for i, t in enumerate(t_grid)}
    leaks: dict[str, list[int]] = {}
    for t in samples:
        part = compute(inputs.available_until(int(t)), np.array([t], dtype=np.int64))
        for name, col in full.items():
            if not _same(float(part[name][0]), float(col[index[int(t)]])):
                leaks.setdefault(name, []).append(int(t))
    return leaks


def _garbage_bars(s: BarSeries, t_ms: int, rng: np.random.Generator) -> BarSeries:
    future = s.available_at_ms > t_ms
    cols = {}
    for name in ("open", "high", "low", "close", "volume", "trade_count", "taker_buy_volume"):
        col = getattr(s, name).copy()
        col[future] = rng.uniform(1.0, 1e6, int(future.sum()))
        cols[name] = col
    complete = s.complete.copy()
    complete[future] = rng.random(int(future.sum())) > 0.3
    return replace(s, complete=complete, **cols)


def garbage_after(inputs: MarketInputs, t_ms: int, seed: int = 11) -> MarketInputs:
    """Same record times as ``inputs``, but every value that became available after ``t_ms`` is random."""
    rng = np.random.default_rng(seed)
    bars = {tf: _garbage_bars(s, t_ms, rng) for tf, s in inputs.bars.items()}
    f = inputs.funding
    ff = f.available_at_ms > t_ms
    rate = f.funding_rate.copy()
    rate[ff] = rng.normal(0.5, 1.0, int(ff.sum()))
    funding = FundingSeries(f.funding_time_ms, f.available_at_ms, rate, f.interval_hours)
    o = inputs.open_interest
    of = o.available_at_ms > t_ms

    def scramble(col: np.ndarray) -> np.ndarray:
        col = col.copy()
        col[of] = rng.uniform(0.1, 1e6, int(of.sum()))
        return col

    oi = OpenInterestSeries(
        o.ts_ms, o.available_at_ms, scramble(o.sum_open_interest), scramble(o.top_trader_ls_ratio), scramble(o.taker_ls_vol_ratio)
    )
    return MarketInputs(bars=bars, funding=funding, open_interest=oi)


def perturbation_leaks(compute: Compute, inputs: MarketInputs, t_grid: np.ndarray, samples: np.ndarray) -> dict[str, list[int]]:
    full = compute(inputs, t_grid)
    index = {int(t): i for i, t in enumerate(t_grid)}
    leaks: dict[str, list[int]] = {}
    for t in samples:
        part = compute(garbage_after(inputs, int(t)), np.array([t], dtype=np.int64))
        for name, col in full.items():
            if not _same(float(part[name][0]), float(col[index[int(t)]])):
                leaks.setdefault(name, []).append(int(t))
    return leaks

"""Strategy "Crowded Shorts" - the rules pre-registered in `docs/strategy_crowded_shorts.md` section 2.

Pure functions of the Stage 3 feature columns on the 1h decision grid; no prices, fills or costs (those belong to
``arven.backtest.crowded_shorts_sim``). Identical, rule for rule, to the research script that produced the
pre-registered and sealed-test numbers (``scripts/research/cs_sealed_test.py``: ``trades_from_signals`` with
``edge_lab.hold``), so the live signals are the same strategy that was evaluated (CLAUDE.md rule 8).

- **Signal** at a 1h close ``t``: ``fund_z <= fund_z_max`` and ``oi_z >= oi_z_min``; a missing value is no signal.
- **Hold**: long from the signal for ``hold_hours`` decision times; a new signal while long restarts the count.
- A *block* is one continuous hold: entry at its first decision time (market, at the next 1m open), planned exit at the
  first decision time after it with no position; the stop (``stop_fraction`` below the fill) is the price module's job.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class CrowdedShortsParams:
    fund_z_max: float = -1.5
    oi_z_min: float = 1.0
    hold_hours: int = 24
    stop_fraction: float = 0.03

    def __post_init__(self) -> None:
        if self.hold_hours < 1:
            raise ValueError("hold_hours must be >= 1")
        if not 0 < self.stop_fraction < 1:
            raise ValueError("stop_fraction must be in (0, 1)")


@dataclass(frozen=True, slots=True)
class CrowdedShortsBlock:
    start_ms: int  # the first signal's decision time = the entry time
    end_ms: int | None  # the planned exit time (first decision time without a position); None = still holding
    last_signal_ms: int  # the most recent qualifying signal inside the block (the hold counts from here)
    start_index: int  # row of ``start_ms`` in the decision grid


def signal_mask(fund_z: np.ndarray, oi_z: np.ndarray, p: CrowdedShortsParams) -> np.ndarray:
    """Qualifying decision times; NaN (missing funding or OI) never qualifies."""
    z = np.nan_to_num(np.asarray(fund_z, dtype=float), nan=0.0)
    oz = np.nan_to_num(np.asarray(oi_z, dtype=float), nan=-np.inf)
    return (z <= p.fund_z_max) & (oz >= p.oi_z_min) & np.isfinite(np.asarray(fund_z, dtype=float)) & np.isfinite(np.asarray(oi_z, dtype=float))


def holding(mask: np.ndarray, hours: int) -> np.ndarray:
    """1 where long: the most recent signal is within the last ``hours`` decision times (a signal at ``t`` acts from ``t``)."""
    pos = np.zeros(len(mask))
    left = 0
    for i, e in enumerate(mask):
        if e:
            left = hours
        if left > 0:
            pos[i] = 1.0
            left -= 1
    return pos


def blocks(t_ms: np.ndarray, mask: np.ndarray, p: CrowdedShortsParams) -> list[CrowdedShortsBlock]:
    """Every hold block on the decision grid ``t_ms`` (consecutive hours, oldest first)."""
    pos = holding(mask, p.hold_hours)
    prev = np.concatenate([[0.0], pos[:-1]])
    out = []
    for s in np.flatnonzero((pos != 0) & (prev == 0)):
        e = int(s)
        last = int(s)
        while e < len(pos) and pos[e] != 0:
            if mask[e]:
                last = e
            e += 1
        out.append(CrowdedShortsBlock(int(t_ms[s]), int(t_ms[e]) if e < len(t_ms) else None, int(t_ms[last]), int(s)))
    return out


__all__ = ["CrowdedShortsBlock", "CrowdedShortsParams", "blocks", "holding", "signal_mask"]

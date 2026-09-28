"""Deterministic simulation clock.

The clock is the only source of "now" inside a backtest: an immutable, pre-computed grid of decision times
(1h bar closes) that only the engine advances. No wall-clock is ever read. A live loop implements the same
protocol with real time, so backtest and live share one code path.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

HOUR_MS = 3_600_000


class Clock(Protocol):
    @property
    def now_ms(self) -> int: ...

    def advance(self) -> int | None:
        """Move to the next decision time and return it, or ``None`` when the grid is exhausted."""
        ...


class SimulationClock:
    def __init__(self, grid_ms: np.ndarray) -> None:
        grid = np.ascontiguousarray(grid_ms, dtype=np.int64)
        if len(grid) and (np.any(grid % HOUR_MS != 0) or np.any(np.diff(grid) <= 0)):
            raise ValueError("clock grid must be strictly increasing whole hours")
        self._grid = grid
        self._i = -1

    @property
    def grid_ms(self) -> np.ndarray:
        return self._grid

    @property
    def now_ms(self) -> int:
        if self._i < 0:
            raise RuntimeError("clock has not started")
        return int(self._grid[self._i])

    @property
    def started(self) -> bool:
        return self._i >= 0

    def advance(self) -> int | None:
        if self._i + 1 >= len(self._grid):
            return None
        self._i += 1
        return int(self._grid[self._i])

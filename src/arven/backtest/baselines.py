"""Baseline signal providers: no-trade, buy-and-hold, seeded random entry.

They exist to make the measuring instrument checkable and to give every later result something to be
compared with (CLAUDE.md rule 6). They contain no trading logic and take no decisions from prices: they see only
the clock, readiness flags and their own seeded random numbers.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from arven.backtest.clock import HOUR_MS
from arven.backtest.provider import DecisionContext, PrepareInfo
from arven.core.signal import Signal
from arven.core.types import Action

MINUTE_MS = 60_000


class NoTrade:
    """Never trades: equity must stay exactly at its initial value."""

    def describe(self) -> dict[str, Any]:
        return {"name": "no_trade"}

    def prepare(self, info: PrepareInfo) -> None:
        return None

    def decide(self, ctx: DecisionContext) -> Signal | None:
        return None


class BuyAndHold:
    """One LONG at the first decision whose features are ready; held until the forced close at the window end."""

    def __init__(self, notional_fraction: float) -> None:
        self._fraction = notional_fraction
        self._done = False

    def describe(self) -> dict[str, Any]:
        return {"name": "buy_and_hold", "notional_fraction": self._fraction}

    def prepare(self, info: PrepareInfo) -> None:
        self._done = False

    def decide(self, ctx: DecisionContext) -> Signal | None:
        if self._done or ctx.portfolio.side != 0 or ctx.portfolio.order_pending:
            return None
        if ctx.features.value("feat_ready") != 1.0:
            return None
        self._done = True
        return Signal(ctx.now_ms, Action.LONG, notional_fraction=self._fraction, tag="buy_and_hold")


class RandomEntry:
    """Random entries with a fixed holding time, reproducible from ``(base_seed, spawn_index)``.

    The schedule (which decision times enter, in which direction) is drawn once in ``prepare`` from a
    ``numpy`` PCG64 generator seeded with ``SeedSequence(base_seed, spawn_key=(spawn_index,))`` (identical to
    ``SeedSequence(base_seed).spawn(n)[spawn_index]``). It depends only on decision times, the warm-up date and
    the seed - never on prices. Entries never overlap: a trade occupies ``[t, t + holding + 1h)``.
    Each trade exits by a time stop after ``holding_minutes``; no stop or target.
    """

    ALGORITHM = "PCG64/SeedSequence"

    def __init__(
        self,
        *,
        base_seed: int,
        spawn_index: int,
        n_trades: int,
        holding_minutes: int,
        notional_fraction: float,
        direction_mode: str = "random_50_50",
    ) -> None:
        if direction_mode != "random_50_50":
            raise ValueError("only random_50_50 is implemented")
        self._base_seed, self._index = base_seed, spawn_index
        self._n, self._holding, self._fraction = n_trades, holding_minutes, notional_fraction
        self._mode = direction_mode
        self._schedule: dict[int, Action] = {}
        self.placed = 0
        self.skipped_not_ready = 0

    def describe(self) -> dict[str, Any]:
        return {
            "name": "random_entry",
            "base_seed": self._base_seed,
            "spawn_index": self._index,
            "algorithm": self.ALGORITHM,
            "numpy_version": np.__version__,
            "n_trades_requested": self._n,
            "holding_minutes": self._holding,
            "notional_fraction": self._fraction,
            "direction_mode": self._mode,
        }

    @property
    def schedule(self) -> dict[int, Action]:
        return dict(self._schedule)

    def prepare(self, info: PrepareInfo) -> None:
        rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence(self._base_seed, spawn_key=(self._index,))))
        hold_ms = self._holding * MINUTE_MS
        grid = info.grid_ms
        first = grid[0] if info.first_ready_ms is None else max(int(grid[0]), int(info.first_ready_ms))
        eligible = grid[(grid >= first) & (grid + hold_ms + HOUR_MS < info.window_end_ms)]
        span = hold_ms + HOUR_MS
        accepted: list[int] = []
        directions: list[Action] = []
        for i in rng.permutation(len(eligible)):
            t = int(eligible[i])
            if any(t < a + span and a < t + span for a in accepted):
                continue
            accepted.append(t)
            directions.append(Action.LONG if int(rng.integers(0, 2)) == 1 else Action.SHORT)
            if len(accepted) == self._n:
                break
        self._schedule = dict(zip(accepted, directions))
        self.placed = len(accepted)
        self.skipped_not_ready = 0

    def decide(self, ctx: DecisionContext) -> Signal | None:
        action = self._schedule.get(ctx.now_ms)
        if action is None:
            return None
        if ctx.features.value("feat_ready") != 1.0:
            self.skipped_not_ready += 1
            return None
        return Signal(
            ctx.now_ms,
            action,
            notional_fraction=self._fraction,
            max_holding_minutes=self._holding,
            tag=f"random_entry:{self._index}",
        )

"""Signals that do not contradict each other (the owner's request, 2026-10-24).

Every strategy of a market keeps recording and tracking its own signals - its forward record stays its own. What
changes is what the owner is told: a new signal whose side is **opposite** to a signal of another strategy that is
still active on the same market (pending or open at the new signal's time) is marked "do not enter"; one on the same
side is marked "confirms". When two signals start at the same moment, the one with the higher priority counts as the
earlier: the higher timeframe first, then the order of ``config/live.yaml``. Pure functions; the live tick applies them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from arven.engine.signal_events import SignalUpdateKind

TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}


@dataclass(frozen=True, slots=True)
class ActiveSignal:
    signal_id: str
    strategy_id: str
    title: str
    tf: str
    side: int
    start_ms: int
    end_ms: int | None  # the close or cancellation; None while still pending / open
    priority: tuple[int, int]  # (-timeframe minutes, config order): smaller = stronger


def end_of(updates: Sequence) -> int | None:
    """When a signal stopped being active: its CLOSED or CANCELLED update, if any."""
    ends = [u.time_ms for u in updates if u.kind in (SignalUpdateKind.CLOSED, SignalUpdateKind.CANCELLED)]
    return min(ends) if ends else None


def priority(tf: str, order: int) -> tuple[int, int]:
    return (-TF_MINUTES.get(tf, 15), order)


def check(new: ActiveSignal, others: Sequence[ActiveSignal]) -> tuple[list[ActiveSignal], list[ActiveSignal]]:
    """``(opposite, same)``: other strategies' signals active when ``new`` started. A signal that started at the very
    same time counts only if it has the higher priority (so of two simultaneous opposite signals exactly one is
    flagged)."""
    t = new.start_ms
    opposite, same = [], []
    for o in others:
        if o.signal_id == new.signal_id or o.strategy_id == new.strategy_id:
            continue
        if o.start_ms > t or (o.end_ms is not None and o.end_ms <= t):
            continue
        if o.start_ms == t and o.priority >= new.priority:
            continue
        (opposite if o.side != new.side else same).append(o)
    key = lambda a: (a.priority, a.start_ms)  # noqa: E731
    return sorted(opposite, key=key), sorted(same, key=key)


__all__ = ["TF_MINUTES", "ActiveSignal", "check", "end_of", "priority"]

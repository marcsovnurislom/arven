"""Append-only updates to an already-announced :class:`~arven.engine.signal.EngineSignal` (section 5.3:
"Updates (TP hit, stop moved to break-even, closed) are separate append-only events linked by signal_id").
The signal itself never changes; its history is this sequence of events instead."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class SignalUpdateKind(StrEnum):
    TP_HIT = "TP_HIT"
    STOP_MOVED = "STOP_MOVED"  # e.g. moved to break-even after TP1
    CLOSED = "CLOSED"  # fully closed (stop, time stop, or a final rung) - the signal's life ends here
    CANCELLED = "CANCELLED"  # never filled (e.g. price never reached the planned entry)
    FILLED = "FILLED"  # a resting (limit) entry was filled - market-entry signals are filled at once and never get one


@dataclass(frozen=True, slots=True)
class SignalUpdate:
    signal_id: str
    time_ms: int
    kind: SignalUpdateKind
    detail: str  # deterministic key=value text with the numbers behind the update (same style as OrderEvent.detail)

    def __post_init__(self) -> None:
        if not self.signal_id:
            raise ValueError("signal_id must not be empty")
        if not math.isfinite(self.time_ms):
            raise ValueError("time_ms must be finite")

    def to_dict(self) -> dict:
        return {"signal_id": self.signal_id, "time_ms": self.time_ms, "kind": self.kind.value, "detail": self.detail}

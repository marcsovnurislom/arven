"""The v2 signal object (`docs/ARVEN_MASTER_PROMPT.md` section 5.3) - what the signal-product build-out
announces (Telegram/web, later phases) and paper-tracks. Additive: it does not replace, modify, or get
consumed by `core.signal.Signal` (the legacy decision-engine output `Backtester`/`EventBacktester` still
use unchanged) - this is a separate, richer object built *from* a decision, for display and forward
tracking, never fed back into the Stage 4 execution layer.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

from arven.engine.grading import Grade


@dataclass(frozen=True, slots=True)
class TPLevel:
    """One rung of the take-profit ladder, planned in R-multiples (not an absolute price - the same plan
    applies however large the position ends up being). ``price`` is derived, never independently supplied,
    so it can never silently disagree with ``r_multiple``."""

    r_multiple: float  # > 0: the planned reward at this rung, in units of the planned risk
    close_fraction: float  # in (0, 1]: fraction of the *original* size closed when this rung fills
    price: float  # entry +/- r_multiple * |entry - stop| (+ for long, - for short); see from_r_multiple

    def __post_init__(self) -> None:
        if not (math.isfinite(self.r_multiple) and self.r_multiple > 0):
            raise ValueError("r_multiple must be finite and positive")
        if not (math.isfinite(self.close_fraction) and 0 < self.close_fraction <= 1):
            raise ValueError("close_fraction must be in (0, 1]")
        if not math.isfinite(self.price):
            raise ValueError("price must be finite")

    @staticmethod
    def from_r_multiple(r_multiple: float, close_fraction: float, *, entry: float, stop: float, side: int) -> TPLevel:
        if side not in (1, -1):
            raise ValueError("side must be +1 or -1")
        risk_per_unit = abs(entry - stop)
        if not (math.isfinite(risk_per_unit) and risk_per_unit > 0):
            raise ValueError("entry and stop must be finite and distinct")
        price = entry + side * r_multiple * risk_per_unit
        return TPLevel(r_multiple, close_fraction, price)


def tp_ladder_from_r_multiples(
    levels: tuple[tuple[float, float], ...], *, entry: float, stop: float, side: int
) -> tuple[TPLevel, ...]:
    """Convenience: build a whole ladder from ``(r_multiple, close_fraction)`` pairs, nearest rung first."""
    return tuple(TPLevel.from_r_multiple(r, f, entry=entry, stop=stop, side=side) for r, f in levels)


def _validate_ladder(tp_ladder: tuple[TPLevel, ...], side: int, entry: float, stop: float) -> None:
    if not tp_ladder:
        raise ValueError("tp_ladder must have at least one level")
    total = sum(level.close_fraction for level in tp_ladder)
    if total > 1.0 + 1e-9:
        raise ValueError(f"tp_ladder close_fractions must not sum to more than 1.0, got {total}")
    rs = [level.r_multiple for level in tp_ladder]
    if rs != sorted(rs):
        raise ValueError("tp_ladder must be ordered nearest-rung-first (increasing r_multiple)")
    for level in tp_ladder:
        if side == 1 and level.price <= entry:
            raise ValueError("a long take-profit must be above entry")
        if side == -1 and level.price >= entry:
            raise ValueError("a short take-profit must be below entry")


@dataclass(frozen=True, slots=True)
class SignalVersions:
    """Exactly reproduces which data/code produced this signal (CLAUDE.md rule 10)."""

    feature_version: str
    config_hash: str
    git_commit: str | None
    data_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class EngineSignal:
    """One strategy's announcement at one event. Immutable: later developments (a rung filling, the stop
    moving to break-even, a close) are separate, append-only :class:`~arven.engine.signal_events.SignalUpdate`
    records linked by ``signal_id`` - this object itself never changes after construction."""

    symbol: str
    side: int  # +1 long, -1 short
    strategy_id: str
    strategy_version: str
    grade: Grade
    event_time_ms: int
    entry_reference: float  # a planning price (e.g. the trigger bar's close) - never the real fill
    stop: float
    tp_ladder: tuple[TPLevel, ...]
    risk_fraction: float  # fraction of equity risked (entry to stop), > 0
    confidence: float  # in [0, 1]
    regime: str  # Regime.label format (e.g. "TREND_UP/NORMAL"), matching reports.decision_summary()
    reasons: tuple[str, ...]
    risk_checks: tuple[str, ...]
    versions: SignalVersions
    max_holding_minutes: int | None = None
    signal_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if self.side not in (1, -1):
            raise ValueError("side must be +1 or -1")
        if not self.strategy_id or not self.strategy_version:
            raise ValueError("strategy_id and strategy_version must not be empty")
        if not (math.isfinite(self.entry_reference) and self.entry_reference > 0):
            raise ValueError("entry_reference must be finite and positive")
        if not (math.isfinite(self.stop) and self.stop > 0):
            raise ValueError("stop must be finite and positive")
        if (self.side == 1 and self.stop >= self.entry_reference) or (self.side == -1 and self.stop <= self.entry_reference):
            raise ValueError("stop must be on the losing side of entry_reference")
        _validate_ladder(self.tp_ladder, self.side, self.entry_reference, self.stop)
        if not (math.isfinite(self.risk_fraction) and self.risk_fraction > 0):
            raise ValueError("risk_fraction must be finite and positive")
        if not (math.isfinite(self.confidence) and 0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0, 1]")
        if self.max_holding_minutes is not None and self.max_holding_minutes < 1:
            raise ValueError("max_holding_minutes must be >= 1")
        object.__setattr__(self, "signal_id", self._compute_signal_id())

    @property
    def r_plan(self) -> tuple[float, ...]:
        """Reward:risk per target - read off the ladder, never stored separately (one source of truth)."""
        return tuple(level.r_multiple for level in self.tp_ladder)

    def _canonical_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "grade": self.grade.value,
            "event_time_ms": self.event_time_ms,
            "entry_reference": self.entry_reference,
            "stop": self.stop,
            "tp_ladder": [[lvl.r_multiple, lvl.close_fraction, lvl.price] for lvl in self.tp_ladder],
            "risk_fraction": self.risk_fraction,
            "confidence": self.confidence,
            "regime": self.regime,
            "reasons": list(self.reasons),
            "risk_checks": list(self.risk_checks),
            "versions": {
                "feature_version": self.versions.feature_version,
                "config_hash": self.versions.config_hash,
                "git_commit": self.versions.git_commit,
                "data_fingerprint": self.versions.data_fingerprint,
            },
            "max_holding_minutes": self.max_holding_minutes,
        }

    def _compute_signal_id(self) -> str:
        canonical = json.dumps(self._canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        """JSON-safe representation (for the signal store / later display layers), including ``signal_id``."""
        return {"signal_id": self.signal_id, **self._canonical_dict()}

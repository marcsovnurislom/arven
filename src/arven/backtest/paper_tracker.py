"""Walks 1m bars forward from an already-resolved entry fill to resolve an
:class:`~arven.engine.signal.EngineSignal`'s TP ladder and stop - the "paper tracker" of
`docs/ARVEN_MASTER_PROMPT.md` section 5.3 ("resolves every signal on 1m bars with the same cost model...
results in R and net of costs"). Lives in ``arven.backtest`` (not ``arven.engine``), the same resolution
Phase 3's ``event_engine.py`` already established: this module reuses ``arven.backtest.costs`` directly
(the fee/slippage model), so the dependency points ``backtest -> engine``, never the reverse
(``tests/backtest/test_paper_tracker_static_rules.py``).

**What this deliberately does not model (scope cut, documented, not an oversight):** funding payments.
CLAUDE.md rule 4 asks every *backtest* to model funding; this is a forward paper-tracker for one signal's
own life (typically hours, not the multi-year horizons funding mainly matters for), and Phase 4's own gate
is "hand-computed R/TP-ladder tests" - fees and slippage are the costs that scale with every leg of a
ladder and are therefore the ones that must be proven correct first. Funding is left for a later phase if
a real signal's holding time turns out to make it material.

**Intrabar tie rule (mirrors ``arven.backtest.execution``'s documented rule exactly):** a stop always beats
a take-profit in the same bar. This module adds one more, equally conservative rule of its own for the
ladder: **at most one rung (or the stop) resolves per bar** - even if a single bar's range would technically
reach two rungs at once (a large gap), only the nearer one is credited that bar; the next rung can resolve
no earlier than the following bar. This never assumes an order of events within one bar that the 1m data
cannot actually distinguish - the same spirit as CLAUDE.md's "assume the worse outcome when order is
unknown", applied here to "assume the slower outcome" rather than inventing a same-bar cascade.
"""

from __future__ import annotations

from dataclasses import dataclass

from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate
from arven.backtest.errors import DataError
from arven.backtest.marketdata import MarketData
from arven.core.config import CostsConfig
from arven.engine.ladder import ClosedLeg, LadderResolution, resolve_legs
from arven.engine.signal import EngineSignal
from arven.engine.signal_events import SignalUpdateKind


@dataclass(frozen=True, slots=True)
class TrackedUpdate:
    """One update the caller may turn into a real, persisted
    :class:`~arven.engine.signal_events.SignalUpdate` (this module does no I/O itself)."""

    time_ms: int
    kind: SignalUpdateKind
    detail: str


@dataclass(frozen=True, eq=False)
class PaperTrackResult:
    """``resolution`` is ``None`` when the available market data ran out before the stop, any TP level, or
    the deadline was ever touched - a legitimate "still open, nothing resolved yet" outcome, not an error
    (the caller simply has not fed enough forward data yet; re-run with more once it exists)."""

    resolution: LadderResolution | None
    updates: tuple[TrackedUpdate, ...]


def track_signal(
    signal: EngineSignal,
    entry_time_ms: int,
    entry_fill_price: float,
    market: MarketData,
    costs: CostsConfig,
    *,
    stress: bool = False,
    move_stop_to_breakeven_after_first_tp: bool = False,
) -> PaperTrackResult:
    """Resolve ``signal`` from its real fill forward, on ``market``'s 1m bars.

    ``entry_time_ms``/``entry_fill_price`` are facts already established elsewhere (the real fill, with
    its own latency and slippage - not this module's job to compute); ``market`` must contain
    ``entry_time_ms`` as one of its own 1m bar times.
    """
    side = signal.side
    stop_price = signal.stop
    levels = signal.tp_ladder
    fee_rate = taker_fee_rate(costs)

    start = market.first_at_or_after(entry_time_ms)
    if start >= len(market) or int(market.time_ms[start]) != entry_time_ms:
        raise DataError(f"entry_time_ms {entry_time_ms} is not a 1m bar time in the given market data")
    deadline_ms = None if signal.max_holding_minutes is None else entry_time_ms + signal.max_holding_minutes * 60_000

    remaining = 1.0
    next_level = 0
    effective_stop = stop_price
    legs: list[ClosedLeg] = []
    updates: list[TrackedUpdate] = []

    i = start
    while i < len(market) and remaining > 1e-9:
        t = int(market.time_ms[i])
        o, h, lo = float(market.open[i]), float(market.high[i]), float(market.low[i])

        if deadline_ms is not None and t >= deadline_ms:
            sigma = slippage_fraction(o, h, lo, costs, stress)
            exit_price = adverse_price(o, -side, sigma)
            fee = remaining * exit_price * fee_rate
            legs.append(ClosedLeg(remaining, exit_price, fee, "TIME_STOP"))
            updates.append(TrackedUpdate(t, SignalUpdateKind.CLOSED, f"reason=TIME_STOP;fraction={remaining:.8f}"))
            remaining = 0.0
            break

        stop_touched = (lo <= effective_stop) if side == 1 else (h >= effective_stop)
        if stop_touched:
            sigma = slippage_fraction(o, h, lo, costs, stress)
            exit_price = adverse_price(effective_stop, -side, sigma)
            fee = remaining * exit_price * fee_rate
            reason = "STOP" if effective_stop == stop_price else "STOP_BREAKEVEN"
            legs.append(ClosedLeg(remaining, exit_price, fee, reason))
            updates.append(TrackedUpdate(t, SignalUpdateKind.CLOSED, f"reason={reason};fraction={remaining:.8f}"))
            remaining = 0.0
            break

        if next_level < len(levels):
            level = levels[next_level]
            level_touched = (h >= level.price) if side == 1 else (lo <= level.price)
            if level_touched:
                sigma = slippage_fraction(o, h, lo, costs, stress)
                exit_price = adverse_price(level.price, -side, sigma)
                frac = min(level.close_fraction, remaining)
                fee = frac * exit_price * fee_rate
                tag = f"TP{next_level + 1}"
                legs.append(ClosedLeg(frac, exit_price, fee, tag))
                updates.append(TrackedUpdate(t, SignalUpdateKind.TP_HIT, f"level={tag};fraction={frac:.8f};price={exit_price:.8f}"))
                remaining -= frac
                next_level += 1
                if next_level == 1 and move_stop_to_breakeven_after_first_tp and remaining > 1e-9:
                    effective_stop = entry_fill_price
                    updates.append(TrackedUpdate(t, SignalUpdateKind.STOP_MOVED, f"new_stop={entry_fill_price:.8f}"))
                i += 1
                continue

        i += 1

    resolution = resolve_legs(entry_fill_price, stop_price, side, legs) if legs else None
    return PaperTrackResult(resolution, tuple(updates))

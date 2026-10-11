"""Pure message formatting (section 5.4's four message kinds). Every function takes already-computed data
(an :class:`EngineSignal`, a :class:`SignalUpdate`, a heartbeat dict, a small summary struct) and returns
plain text - none of them compute a trading number of their own (CLAUDE.md rule 9). Every message carries
the disclaimer (CLAUDE.md rule 6 / rule 12 - this is simulated, never a real order).
"""

from __future__ import annotations

from dataclasses import dataclass

from arven.core.time import from_ms
from arven.engine.signal import EngineSignal
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind

DISCLAIMER = "Paper signal only - simulated, not a real order, not financial advice (CLAUDE.md rules 6/12)."

_UPDATE_VERB = {
    SignalUpdateKind.TP_HIT: "TP hit",
    SignalUpdateKind.STOP_MOVED: "Stop moved",
    SignalUpdateKind.CLOSED: "Closed",
    SignalUpdateKind.CANCELLED: "Cancelled",
    SignalUpdateKind.FILLED: "Entry filled",
}


def _side_word(side: int) -> str:
    return "LONG" if side == 1 else "SHORT"


def _version(v: str) -> str:
    return v if v.startswith("v") else f"v{v}"


def _utc(ms: int) -> str:
    return from_ms(ms).strftime("%Y-%m-%d %H:%M UTC")


def format_new_signal(signal: EngineSignal) -> str:
    tp_lines = "\n".join(
        f"  TP{i + 1}: {lvl.price:.2f} ({lvl.r_multiple:.2f}R, close {lvl.close_fraction:.0%})"
        for i, lvl in enumerate(signal.tp_ladder)
    )
    if not signal.tp_ladder and signal.max_holding_minutes is not None:
        tp_lines = f"  No take-profit: time exit after {signal.max_holding_minutes / 60:g} h"
    if signal.entry_type == "limit":
        until = f" (valid until {_utc(signal.valid_until_ms)})" if signal.valid_until_ms else ""
        entry = f"Entry: LIMIT {signal.entry_reference:.2f}{until}"
    else:
        entry = f"Entry (ref): {signal.entry_reference:.2f}"
    reasons = "; ".join(signal.reasons[:3]) if signal.reasons else "(none recorded)"
    return (
        f"NEW SIGNAL [{signal.grade.value}]\n"
        f"{signal.symbol} {_side_word(signal.side)}  ({signal.strategy_id} {_version(signal.strategy_version)})  {_utc(signal.event_time_ms)}\n"
        f"{entry}\n"
        f"Stop: {signal.stop:.2f}\n"
        f"{tp_lines}\n"
        f"Risk: {signal.risk_fraction:.2%} of equity   Confidence: {signal.confidence:.0%}\n"
        f"Regime: {signal.regime}\n"
        f"Reasons: {reasons}\n\n{DISCLAIMER}"
    )


def format_signal_update(signal: EngineSignal, update: SignalUpdate) -> str:
    verb = _UPDATE_VERB[update.kind]
    return (
        f"{verb}: {signal.symbol} {_side_word(signal.side)} ({signal.strategy_id})  {_utc(update.time_ms)}\n"
        f"Signal of {_utc(signal.event_time_ms)}, entry {signal.entry_reference:.2f}, stop {signal.stop:.2f}\n"
        f"{update.detail}\n\n{DISCLAIMER}"
    )


def format_system_alert(title: str, detail: str) -> str:
    return f"SYSTEM ALERT: {title}\n{detail}"


@dataclass(frozen=True, slots=True)
class DailySummarySection:
    strategy_id: str
    grade: str
    n_signals: int
    n_closed: int
    net_r: float


def format_daily_summary(date_label: str, sections: tuple[DailySummarySection, ...]) -> str:
    if not sections:
        body = "No signals today."
    else:
        body = "\n".join(
            f"  {s.strategy_id} [{s.grade}]: {s.n_signals} signals, {s.n_closed} closed, net {s.net_r:+.2f}R"
            for s in sections
        )
    return f"Daily summary - {date_label}\n{body}\n\n{DISCLAIMER}"

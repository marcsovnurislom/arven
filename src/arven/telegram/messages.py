"""Pure message formatting (section 5.4's four message kinds). Every function takes already-computed data
(an :class:`EngineSignal`, a :class:`SignalUpdate`, a heartbeat dict, a small summary struct) and returns
plain text - none of them compute a trading number of their own (CLAUDE.md rule 9). Every message carries
the disclaimer (CLAUDE.md rule 6 / rule 12 - this is simulated, never a real order).
"""

from __future__ import annotations

from dataclasses import dataclass

from arven.engine.signal import EngineSignal
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind

DISCLAIMER = "Paper signal only - simulated, not a real order, not financial advice (CLAUDE.md rules 6/12)."

_UPDATE_VERB = {
    SignalUpdateKind.TP_HIT: "TP hit",
    SignalUpdateKind.STOP_MOVED: "Stop moved",
    SignalUpdateKind.CLOSED: "Closed",
    SignalUpdateKind.CANCELLED: "Cancelled",
}


def _side_word(side: int) -> str:
    return "LONG" if side == 1 else "SHORT"


def format_new_signal(signal: EngineSignal) -> str:
    tp_lines = "\n".join(
        f"  TP{i + 1}: {lvl.price:.2f} ({lvl.r_multiple:.2f}R, close {lvl.close_fraction:.0%})"
        for i, lvl in enumerate(signal.tp_ladder)
    )
    reasons = "; ".join(signal.reasons[:3]) if signal.reasons else "(none recorded)"
    return (
        f"NEW SIGNAL [{signal.grade.value}]\n"
        f"{signal.symbol} {_side_word(signal.side)}  ({signal.strategy_id} v{signal.strategy_version})\n"
        f"Entry (ref): {signal.entry_reference:.2f}\n"
        f"Stop: {signal.stop:.2f}\n"
        f"{tp_lines}\n"
        f"Risk: {signal.risk_fraction:.2%} of equity   Confidence: {signal.confidence:.0%}\n"
        f"Regime: {signal.regime}\n"
        f"Reasons: {reasons}\n\n{DISCLAIMER}"
    )


def format_signal_update(signal: EngineSignal, update: SignalUpdate) -> str:
    verb = _UPDATE_VERB[update.kind]
    return (
        f"{verb}: {signal.symbol} {_side_word(signal.side)} ({signal.strategy_id})\n"
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

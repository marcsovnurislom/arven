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


# How a feed symbol is shown to the owner: gold signals are computed on Binance's XAUUSDT perpetual, but the owner
# trades the XAUUSD CFD - say both, so a price is never mistaken for the broker's quote.
SYMBOL_LABELS = {"XAUUSDT": "GOLD XAUUSD (prices: Binance XAUUSDT)"}


def symbol_label(symbol: str) -> str:
    return SYMBOL_LABELS.get(symbol, symbol)


def _side_word(side: int) -> str:
    return "LONG" if side == 1 else "SHORT"


def _version(v: str) -> str:
    return v if v.startswith("v") else f"v{v}"


def _utc(ms: int) -> str:
    return from_ms(ms).strftime("%Y-%m-%d %H:%M UTC")


@dataclass(frozen=True, slots=True)
class TrackRecord:
    """The strategy's own paper record at alert time: closed signals since ``since_ms`` (the forward start)."""

    closed: int
    wins: int
    total_r: float
    since_ms: int


def _record_line(record: TrackRecord | None) -> str:
    if record is None:
        return "Record: not available"
    since = from_ms(record.since_ms).strftime("%Y-%m-%d")
    if record.closed == 0:
        return f"Record (paper since {since}): no closed signals yet"
    return (f"Record (paper since {since}): {record.closed} closed, win {record.wins / record.closed:.0%}, "
            f"net {record.total_r:+.2f} R")


def format_new_signal(signal: EngineSignal, record: TrackRecord | None = None) -> str:
    """No per-signal confidence: none is validated (the stored ``confidence`` is a placeholder or an untested setup
    heuristic), so the alert states that and shows the strategy's actual paper record instead."""
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
        f"{symbol_label(signal.symbol)} {_side_word(signal.side)}  ({signal.strategy_id} {_version(signal.strategy_version)})  {_utc(signal.event_time_ms)}\n"
        f"{entry}\n"
        f"Stop: {signal.stop:.2f}\n"
        f"{tp_lines}\n"
        f"Risk: {signal.risk_fraction:.2%} of equity (fixed rule, the same for every signal)\n"
        f"Quality: no validated per-signal estimate\n"
        f"{_record_line(record)}\n"
        f"Regime: {signal.regime}\n"
        f"Reasons: {reasons}\n\n{DISCLAIMER}"
    )


def format_signal_update(signal: EngineSignal, update: SignalUpdate) -> str:
    verb = _UPDATE_VERB[update.kind]
    return (
        f"{verb}: {symbol_label(signal.symbol)} {_side_word(signal.side)} ({signal.strategy_id})  {_utc(update.time_ms)}\n"
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


@dataclass(frozen=True, slots=True)
class WeeklyReportRow:
    """One strategy's whole forward record (closed signals, net R) and the forward review verdict."""

    strategy_id: str
    grade: str
    n_closed: int
    n_open: int
    total_r: float
    win_rate: float | None
    mean_r: float | None
    ci_low: float | None
    ci_high: float | None
    max_dd_r: float | None
    verdict: str  # too_few | losing | inconclusive | positive (arven.live.review)
    week_closed: int
    week_r: float


VERDICT_TEXT = {
    "too_few": "too few closed signals to judge",
    "losing": "LOSING: the 95% interval of mean R is below 0",
    "inconclusive": "inconclusive: the 95% interval contains 0",
    "positive": "positive so far (95% interval above 0) - still not validated",
}


def _num(x: float | None, spec: str) -> str:
    return "n/a" if x is None else format(x, spec)


def format_weekly_report(week_label: str, since_label: str, rows: tuple[WeeklyReportRow, ...]) -> str:
    blocks = []
    for r in rows:
        ci = f"[{_num(r.ci_low, '+.2f')}, {_num(r.ci_high, '+.2f')}]" if r.ci_low is not None else "n/a"
        win = _num(None if r.win_rate is None else r.win_rate * 100, ".0f")
        blocks.append(
            f"{r.strategy_id} [{r.grade}]\n"
            f"  this week: {r.week_closed} closed, {r.week_r:+.2f}R\n"
            f"  since {since_label}: {r.n_closed} closed ({r.n_open} open), {r.total_r:+.2f}R, win {win}%, "
            f"mean {_num(r.mean_r, '+.3f')}R, 95% CI {ci}, max DD {_num(r.max_dd_r, '.1f')}R\n"
            f"  review: {VERDICT_TEXT.get(r.verdict, r.verdict)}"
        )
    body = "\n".join(blocks) if blocks else "No strategies."
    return (f"Weekly forward report - {week_label}\n{body}\n\n"
            f"Net of costs, each signal tracked on its own. No strategy has a proven edge.\n{DISCLAIMER}")

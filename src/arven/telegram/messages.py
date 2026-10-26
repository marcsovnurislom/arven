"""Pure message formatting (section 5.4's four message kinds). Every function takes already-computed data
(an :class:`EngineSignal`, a :class:`SignalUpdate`, a heartbeat dict, a small summary struct) and returns
plain text - none of them compute a trading number of their own (CLAUDE.md rule 9). Every message carries
the disclaimer (CLAUDE.md rule 6 / rule 12 - this is simulated, never a real order).
"""

from __future__ import annotations

from dataclasses import dataclass

from arven.core.prices import fmt_price
from arven.core.time import from_ms
from arven.engine.signal import EngineSignal
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind
from arven.telegram import ru

LANGUAGES = ("en", "ru")  # config/live.yaml telegram.language; "en" is the original wording, unchanged

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
SYMBOL_LABELS = {"XAUUSDT": "GOLD XAUUSD (prices: Binance XAUUSDT)", "XAGUSDT": "SILVER XAGUSD (prices: Binance XAGUSDT)",
                 "EURUSD": "EUR/USD (prices: Dukascopy + Kraken)", "GBPUSD": "GBP/USD (prices: Dukascopy + Kraken)"}


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


def format_new_signal(signal: EngineSignal, record: TrackRecord | None = None, lang: str = "en") -> str:
    """No per-signal confidence: none is validated (the stored ``confidence`` is a placeholder or an untested setup
    heuristic), so the alert states that and shows the strategy's actual paper record instead."""
    if lang == "ru":
        rec = (ru.record_line(None, 0, 0.0, None) if record is None
               else ru.record_line(record.closed, record.wins, record.total_r, record.since_ms))
        return ru.new_signal(signal, rec)
    tp_lines = "\n".join(
        f"  TP{i + 1}: {fmt_price(lvl.price, signal.entry_reference)} ({lvl.r_multiple:.2f}R, close {lvl.close_fraction:.0%})"
        for i, lvl in enumerate(signal.tp_ladder)
    )
    if not signal.tp_ladder and signal.max_holding_minutes is not None:
        tp_lines = f"  No take-profit: time exit after {signal.max_holding_minutes / 60:g} h"
    if signal.entry_type == "limit":
        until = f" (valid until {_utc(signal.valid_until_ms)})" if signal.valid_until_ms else ""
        entry = f"Entry: LIMIT {fmt_price(signal.entry_reference)}{until}"
    else:
        entry = f"Entry (ref): {fmt_price(signal.entry_reference)}"
    reasons = "; ".join(signal.reasons[:3]) if signal.reasons else "(none recorded)"
    return (
        f"NEW SIGNAL [{signal.grade.value}]\n"
        f"{symbol_label(signal.symbol)} {_side_word(signal.side)}  ({signal.strategy_id} {_version(signal.strategy_version)})  {_utc(signal.event_time_ms)}\n"
        f"{entry}\n"
        f"Stop: {fmt_price(signal.stop, signal.entry_reference)}\n"
        f"{tp_lines}\n"
        f"Risk: {signal.risk_fraction:.2%} of equity (fixed rule, the same for every signal)\n"
        f"Quality: no validated per-signal estimate\n"
        f"{_record_line(record)}\n"
        f"Regime: {signal.regime}\n"
        f"Reasons: {reasons}\n\n{DISCLAIMER}"
    )


def chart_title(signal: EngineSignal, update: SignalUpdate | None = None, lang: str = "en") -> str:
    """The picture's headline (``arven.telegram.chart``), worded like the alert text."""
    if lang == "ru":
        return ru.chart_title(signal, update)
    head = f"{symbol_label(signal.symbol)} · {_side_word(signal.side)} · {signal.strategy_id} {_version(signal.strategy_version)}"
    return head if update is None else f"{_UPDATE_VERB[update.kind]}: {head}"


def update_label(update: SignalUpdate, lang: str = "en") -> str:
    """The event's name on the picture, with the exit reason when the detail carries one ("Closed: STOP")."""
    if lang == "ru":
        return ru.update_label(update)
    reason = next((p.split("=", 1)[1] for p in update.detail.split(";") if p.startswith("reason=")), None)
    return f"{_UPDATE_VERB[update.kind]}: {reason}" if reason else _UPDATE_VERB[update.kind]


def format_signal_update(signal: EngineSignal, update: SignalUpdate, lang: str = "en") -> str:
    if lang == "ru":
        return ru.signal_update(signal, update)
    verb = _UPDATE_VERB[update.kind]
    return (
        f"{verb}: {symbol_label(signal.symbol)} {_side_word(signal.side)} ({signal.strategy_id})  {_utc(update.time_ms)}\n"
        f"Signal of {_utc(signal.event_time_ms)}, entry {fmt_price(signal.entry_reference)}, stop {fmt_price(signal.stop, signal.entry_reference)}\n"
        f"{update.detail}\n\n{DISCLAIMER}"
    )


@dataclass(frozen=True, slots=True)
class EventReminderRow:
    """How one market moved in the first hour after past releases of this type (arven.event_moves), in percent."""

    market: str
    n: int
    median_range: float | None
    max_range: float | None
    median_baseline: float | None


EVENT_NAMES_EN = {"FOMC": "Fed rate decision (FOMC)", "CPI": "US inflation, CPI", "NFP": "US jobs report, NFP"}


def format_event_reminder(event_type: str, event_ms: int, minutes: int, rows: tuple[EventReminderRow, ...], lang: str = "en") -> str:
    if lang == "ru":
        return ru.event_reminder(event_type, event_ms, minutes,
                                 [(r.market, r.n, r.median_range, r.max_range, r.median_baseline) for r in rows])
    lines = []
    for r in rows:
        if not r.n or r.median_range is None:
            lines.append(f"  {r.market}: no measured history")
            continue
        usual = f", an ordinary day at this hour {r.median_baseline:.2f} %" if r.median_baseline else ""
        lines.append(f"  {r.market}: median {r.median_range:.2f} %, largest {r.max_range:.2f} %{usual} ({r.n} releases)")
    body = "\n".join(lines)
    return (f"In {minutes} min: {EVENT_NAMES_EN.get(event_type, event_type)}, {from_ms(event_ms).strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"Price range in the first hour after past releases (size, not direction):\n{body}\n"
            "History of past releases, not a forecast.")


def format_system_alert(title: str, detail: str, lang: str = "en") -> str:
    if lang == "ru":
        return ru.system_alert(title, detail)
    return f"SYSTEM ALERT: {title}\n{detail}"


@dataclass(frozen=True, slots=True)
class DailySummarySection:
    strategy_id: str
    grade: str
    n_signals: int
    n_closed: int
    net_r: float


def format_daily_summary(date_label: str, sections: tuple[DailySummarySection, ...], lang: str = "en") -> str:
    if lang == "ru":
        return ru.daily_summary(date_label, [(s.strategy_id, s.grade, s.n_signals, s.n_closed, s.net_r) for s in sections])
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


def format_conflict_note(opposite, same, mode: str, lang: str = "en") -> str | None:
    """The line put above a new-signal alert when another strategy's signal is active on the same market
    (``arven.live.conflicts``): opposite -> "do not enter" (``block``) or a warning (``note``); same side -> confirms."""
    if mode == "off" or not (opposite or same):
        return None
    if lang == "ru":
        return ru.conflict_note([(o.title, o.tf, o.side, o.start_ms) for o in opposite], [(o.title, o.tf, o.side, o.start_ms) for o in same], mode)
    side = {1: "LONG", -1: "SHORT"}
    item = lambda o: f"{o.title} ({o.tf}, {side[o.side]} since {from_ms(o.start_ms).strftime('%d.%m %H:%M UTC')})"  # noqa: E731
    lines = []
    if opposite:
        head = "DO NOT ENTER - contradicts" if mode == "block" else "Contradicts"
        lines.append(f"{head} an active signal: " + "; ".join(item(o) for o in opposite) + ".")
        if mode == "block":
            lines.append("This signal is recorded for the statistics only.")
    if same:
        lines.append("Confirms: " + "; ".join(item(o) for o in same) + ".")
    return "\n".join(lines)


def format_mistakes_summary(blocks: tuple[tuple[str, str | None, tuple[dict, ...]], ...], lang: str = "en") -> str:
    """Weekly "learning from mistakes" note: per market, when it was built and its clear differences (``proposals`` of
    ``scripts/research/mistakes.py``) - ideas to check, never changes."""
    if lang == "ru":
        return ru.mistakes_summary(blocks)
    lines = ["Learning from mistakes"]
    for market, built, proposals in blocks:
        when = f" (built {built[:10]})" if built else " (not built yet)"
        if not proposals:
            lines.append(f"{market}{when}: no circumstance is clearly worse or better yet - too few trades for a conclusion.")
            continue
        lines.append(f"{market}{when}:")
        for p in proposals[:5]:
            word = "worse" if p["flag"] == "worse" else "better"
            lines.append(f"  {p['strategy']} ({p['part']}): {p['feature']} = {p['value']} - {word} than usual, "
                         f"{p['trades']} trades, {p['mean_r']:+.2f}R vs {p['rest_mean_r']:+.2f}R")
    lines.append("Ideas to check on fresh data, not changes. Details: Research -> Learning from mistakes.")
    return "\n".join(lines)


def format_weekly_report(week_label: str, since_label: str, rows: tuple[WeeklyReportRow, ...], lang: str = "en") -> str:
    blocks = []
    for r in rows:
        ci = f"[{_num(r.ci_low, '+.2f')}, {_num(r.ci_high, '+.2f')}]" if r.ci_low is not None else "n/a"
        win = _num(None if r.win_rate is None else r.win_rate * 100, ".0f")
        if lang == "ru":
            blocks.append(ru.weekly_block(r.strategy_id, r.grade, r.week_closed, r.week_r, since_label, r.n_closed, r.n_open, r.total_r,
                                          win, _num(r.mean_r, '+.3f'), ci, _num(r.max_dd_r, '.1f'), r.verdict))
            continue
        blocks.append(
            f"{r.strategy_id} [{r.grade}]\n"
            f"  this week: {r.week_closed} closed, {r.week_r:+.2f}R\n"
            f"  since {since_label}: {r.n_closed} closed ({r.n_open} open), {r.total_r:+.2f}R, win {win}%, "
            f"mean {_num(r.mean_r, '+.3f')}R, 95% CI {ci}, max DD {_num(r.max_dd_r, '.1f')}R\n"
            f"  review: {VERDICT_TEXT.get(r.verdict, r.verdict)}"
        )
    if lang == "ru":
        return ru.weekly_report(week_label, blocks)
    body = "\n".join(blocks) if blocks else "No strategies."
    return (f"Weekly forward report - {week_label}\n{body}\n\n"
            f"Net of costs, each signal tracked on its own. No strategy has a proven edge.\n{DISCLAIMER}")

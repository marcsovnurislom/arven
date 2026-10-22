"""The always-on live process (`arven live run`): one asyncio loop, one DuckDB writer.

Every ``poll_seconds``:
- if a new 15m close is due (``event_delay_seconds`` after it) and not yet covered, run :func:`run_live_tick` in a
  worker thread (REST update -> strategies -> signal store -> Telegram outbox); a tick that did not reach the due close
  (data not published yet, stale data, an error) is simply retried at the next poll;
- once per new hour, optionally the Stage 8 hourly ``paper run`` (``run_legacy_paper``), so no second process (the
  old scheduled task) competes for the database;
- drain the Telegram outbox and answer bot commands (both never raise);
- once a day at ``daily_summary_hour_utc``, queue a daily summary (and on ``weekly_report_weekday`` a weekly forward
  report); system alerts on start, on stale data and after repeated errors;
- once a day at ``maintenance.hour_utc``, the housekeeping: a backup and the paper-run retention rule;
- ``telegram.event_reminder_minutes`` before each FOMC / CPI / NFP release, one reminder with how BTC and gold moved
  after past releases (``arven.event_moves``);
- write the heartbeat (``<data_dir>/live/heartbeat.json``, the same format as the Phase 5 runtime's, so
  ``arven live heartbeat``, ``/status`` and the web app read it) and a JSONL log.

Every step is wrapped: one failure is logged and the loop carries on (an always-on process must not die of one bad
response). Stops on ``stop_event`` (Ctrl+C / a stop file, see the CLI).
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arven.core.config import AppConfig
from arven.core.macro_config import MacroEvent
from arven.core.live_config import LiveConfig
from arven.core.time import from_ms, to_ms, utc_now
from arven.core.timeframes import Timeframe
from arven.event_moves import due_reminders
from arven.paper.runtime import log_event, write_heartbeat

MIN15 = Timeframe.M15.ms
HOUR_MS = 3_600_000
ERROR_ALERT_AFTER = 3  # consecutive failed ticks before a system alert


def live_dir(app: AppConfig) -> Path:
    return app.data.data_dir / "live"


def due_close_ms(now_ms: int, event_delay_ms: int) -> int:
    """The latest 15m close the loop should have evaluated by now."""
    return (now_ms - event_delay_ms) // MIN15 * MIN15


@dataclass
class LoopState:
    """What the loop remembers between polls (persisted in ``<data_dir>/live/state.json``: restart-safe)."""

    done_through_ms: int | None = None  # the last 15m close fully evaluated
    legacy_hour_ms: int | None = None  # the last hour the Stage 8 paper run was done for
    last_tick_ms: int | None = None
    summary_date: str | None = None  # the last UTC date a daily summary was queued for
    weekly_date: str | None = None  # the last UTC date a weekly report was queued for
    maintenance_date: str | None = None  # the last UTC date the daily housekeeping ran (or was attempted)
    consecutive_errors: int = 0
    stale_alerted: bool = False
    telegram_update_id: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def load(path: Path) -> LoopState:
        if not path.exists():
            return LoopState()
        d = json.loads(path.read_text(encoding="utf-8"))
        return LoopState(**{k: v for k, v in d.items() if k in LoopState.__dataclass_fields__})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)


@dataclass
class LoopDeps:
    """Everything with side effects, injectable for tests (each callable runs in a worker thread)."""

    live_tick: Callable[[datetime], Any]  # -> LiveTickOutcome
    legacy_tick: Callable[[datetime], Any] | None  # -> paper.runtime.TickResult
    send_telegram: Callable[[], Any] | None  # drain the outbox
    poll_commands: Callable[[int], int] | None  # (last_update_id) -> new last_update_id
    queue_system: Callable[[str, str, str], None] | None  # (event_key, title, detail)
    queue_daily_summary: Callable[[str], None] | None  # (date label)
    queue_weekly_report: Callable[[str], None] | None = None  # (today's UTC date) - the 7 days before it
    maintenance: Callable[[datetime], Any] | None = None  # daily backup + paper-run retention -> dict for the log
    # further markets (config/live.yaml ``markets``), by instrument: their own tick and optional hourly S1-S3 paper run.
    # Each keeps its own progress in ``state.extra["markets"][instrument]``, so one market never holds another back.
    market_ticks: dict[str, Callable[[datetime], Any]] = field(default_factory=dict)
    market_legacy_ticks: dict[str, Callable[[datetime], Any]] = field(default_factory=dict)
    queue_event_reminder: Callable[[MacroEvent], None] | None = None  # one FOMC / CPI / NFP reminder
    macro_events: tuple[MacroEvent, ...] = ()  # config/macro_events.csv


async def _run(fn: Callable[..., Any], *args: Any) -> tuple[Any, str | None]:
    try:
        return await asyncio.to_thread(fn, *args), None
    except Exception as exc:  # noqa: BLE001 - never let one step kill the process
        return None, f"{type(exc).__name__}: {exc}"


async def poll_once(live: LiveConfig, deps: LoopDeps, state: LoopState, now: datetime, log_path: Path) -> tuple[str, str]:
    """One poll; returns ``(heartbeat status, detail)``."""
    now_ms = to_ms(now)
    status, detail = "idle", ""
    due = due_close_ms(now_ms, live.event_delay_seconds * 1000)
    if state.done_through_ms is None or state.done_through_ms < due:
        out, err = await _run(deps.live_tick, now)
        if err is not None:
            status, detail = "error", err
        else:
            status, detail = out.status, out.detail
            if out.through_ms is not None and out.status in ("ok", "error"):
                state.done_through_ms = out.through_ms if state.done_through_ms is None else max(state.done_through_ms, out.through_ms)
            if out.status in ("ok", "error", "stale"):
                state.last_tick_ms = now_ms
            new = {sid: len(st.new_signals) for sid, st in out.strategies.items() if st.new_signals}
            log_event(log_path, event="live_tick", status=out.status, detail=out.detail, through_ms=out.through_ms,
                      new_signals=new, new_updates=sum(st.new_updates for st in out.strategies.values()), alerts=out.queued_alerts)
        state.consecutive_errors = state.consecutive_errors + 1 if status == "error" else 0
        if state.consecutive_errors == ERROR_ALERT_AFTER and deps.queue_system:
            await _run(deps.queue_system, f"errors:{now_ms // HOUR_MS}", "repeated errors", f"{ERROR_ALERT_AFTER} ticks in a row failed: {detail}")
        if status == "stale" and not state.stale_alerted and deps.queue_system:
            await _run(deps.queue_system, f"stale:{now_ms // HOUR_MS}", "market data stale", f"{detail} - no new signals until it is fresh again (NO_TRADE)")
            state.stale_alerted = True
        elif status == "ok":
            state.stale_alerted = False
        if status == "error":
            log_event(log_path, event="live_tick", status="error", detail=detail)

    for name, tick in deps.market_ticks.items():
        await _market_tick(name, tick, deps, state, now, due, log_path)

    if deps.legacy_tick is not None and live.run_legacy_paper:
        hour = now_ms // HOUR_MS * HOUR_MS
        if state.legacy_hour_ms is None or state.legacy_hour_ms < hour:
            res, err = await _run(deps.legacy_tick, now)
            if err is None and getattr(res, "status", None) in ("ticked", "idle"):
                state.legacy_hour_ms = hour
            log_event(log_path, event="legacy_paper", status=getattr(res, "status", "error"), detail=err or getattr(res, "detail", ""))

    for name, tick in deps.market_legacy_ticks.items():
        ms = _market_state(state, name)
        hour = now_ms // HOUR_MS * HOUR_MS
        if ms["legacy_hour_ms"] is None or ms["legacy_hour_ms"] < hour:
            res, err = await _run(tick, now)
            if err is None and getattr(res, "status", None) in ("ticked", "idle"):
                ms["legacy_hour_ms"] = hour
            log_event(log_path, event="legacy_paper", market=name, status=getattr(res, "status", "error"), detail=err or getattr(res, "detail", ""))

    if deps.queue_daily_summary is not None and live.telegram.daily_summary_hour_utc is not None:
        today = now.astimezone(UTC).date().isoformat()
        if state.summary_date is None:
            state.summary_date = today  # first ever run: start with tomorrow's summary, not one at start-up
        elif now.astimezone(UTC).hour >= live.telegram.daily_summary_hour_utc and state.summary_date != today:
            _, err = await _run(deps.queue_daily_summary, today)
            if err is None:
                state.summary_date = today

    weekday = live.telegram.weekly_report_weekday
    if deps.queue_weekly_report is not None and weekday is not None and live.telegram.daily_summary_hour_utc is not None:
        utc = now.astimezone(UTC)
        today = utc.date().isoformat()
        if utc.weekday() == weekday and utc.hour >= live.telegram.daily_summary_hour_utc and state.weekly_date != today:
            _, err = await _run(deps.queue_weekly_report, today)
            log_event(log_path, event="weekly_report", status="error" if err else "queued", detail=err or "")
            if err is None:
                state.weekly_date = today

    if deps.maintenance is not None and live.maintenance.hour_utc is not None:
        utc = now.astimezone(UTC)
        today = utc.date().isoformat()
        if utc.hour >= live.maintenance.hour_utc and state.maintenance_date != today:
            state.maintenance_date = today  # once a day even if it fails: a broken backup must not repeat every poll
            res, err = await _run(deps.maintenance, now)
            log_event(log_path, event="maintenance", status="error" if err else "ok", detail=err or json.dumps(res, sort_keys=True))
            if err and deps.queue_system is not None:
                await _run(deps.queue_system, f"maintenance:{today}", "daily backup failed", err)

    lead = live.telegram.event_reminder_minutes
    if deps.queue_event_reminder is not None and lead is not None:
        sent: list[str] = state.extra.setdefault("event_reminders", [])
        for e in due_reminders(deps.macro_events, now_ms, lead):
            key = f"{e.event_type}:{e.scheduled_at_ms}"
            if key in sent:
                continue
            _, err = await _run(deps.queue_event_reminder, e)
            log_event(log_path, event="event_reminder", status="error" if err else "queued", detail=err or key)
            if err is None:
                sent.append(key)
                del sent[:-50]

    if deps.send_telegram is not None:
        res, err = await _run(deps.send_telegram)
        if err:
            log_event(log_path, event="telegram_send", status="error", detail=err)
        elif getattr(res, "errors", None):
            log_event(log_path, event="telegram_send", status="error", detail="; ".join(res.errors)[:500])
    if deps.poll_commands is not None and live.telegram.commands:
        new_id, err = await _run(deps.poll_commands, state.telegram_update_id)
        if err is None and new_id is not None:
            state.telegram_update_id = new_id
    return status, detail


def _market_state(state: LoopState, name: str) -> dict[str, Any]:
    markets = state.extra.setdefault("markets", {})
    ms = markets.setdefault(name, {})
    for key, default in (("done_through_ms", None), ("stale_alerted", False), ("consecutive_errors", 0), ("legacy_hour_ms", None),
                         ("last_tick_ms", None)):
        ms.setdefault(key, default)
    return ms


async def _market_tick(
    name: str, tick: Callable[[datetime], Any], deps: LoopDeps, state: LoopState, now: datetime, due: int, log_path: Path,
) -> None:
    """One extra market's tick: the same rules as the default market's above, with its own state and labelled alerts."""
    ms = _market_state(state, name)
    now_ms = to_ms(now)
    if ms["done_through_ms"] is not None and ms["done_through_ms"] >= due:
        return
    out, err = await _run(tick, now)
    if err is not None:
        status, detail = "error", err
        log_event(log_path, event="live_tick", market=name, status="error", detail=detail)
    else:
        status, detail = out.status, out.detail
        if out.through_ms is not None and out.status in ("ok", "error"):
            ms["done_through_ms"] = out.through_ms if ms["done_through_ms"] is None else max(ms["done_through_ms"], out.through_ms)
        if out.status in ("ok", "error", "stale"):
            ms["last_tick_ms"] = now_ms
        new = {sid: len(st.new_signals) for sid, st in out.strategies.items() if st.new_signals}
        log_event(log_path, event="live_tick", market=name, status=out.status, detail=out.detail, through_ms=out.through_ms,
                  new_signals=new, new_updates=sum(st.new_updates for st in out.strategies.values()), alerts=out.queued_alerts)
    ms["consecutive_errors"] = ms["consecutive_errors"] + 1 if status == "error" else 0
    if ms["consecutive_errors"] == ERROR_ALERT_AFTER and deps.queue_system:
        await _run(deps.queue_system, f"errors:{name}:{now_ms // HOUR_MS}", f"{name}: repeated errors",
                   f"{ERROR_ALERT_AFTER} ticks in a row failed: {detail}")
    if status == "stale" and not ms["stale_alerted"] and deps.queue_system:
        await _run(deps.queue_system, f"stale:{name}:{now_ms // HOUR_MS}", f"{name}: market data stale",
                   f"{detail} - no new {name} signals until it is fresh again (NO_TRADE)")
        ms["stale_alerted"] = True
    elif status == "ok":
        ms["stale_alerted"] = False


async def run_live_forever(
    app: AppConfig, live: LiveConfig, deps: LoopDeps, *, now_fn: Callable[[], datetime] = utc_now,
    stop_event: asyncio.Event | None = None, max_iterations: int | None = None,
) -> None:
    root = live_dir(app)
    state_path, heartbeat_path, log_path = root / "state.json", root / "heartbeat.json", root / "live.jsonl"
    state = LoopState.load(state_path)
    stop_event = stop_event or asyncio.Event()
    started = to_ms(now_fn())
    log_event(log_path, event="start", done_through_ms=state.done_through_ms)
    if deps.queue_system is not None:
        await _run(deps.queue_system, f"start:{started}", "live loop started",
                   f"ARVEN live signals started at {from_ms(started).isoformat()}; last evaluated 15m close: "
                   f"{from_ms(state.done_through_ms).isoformat() if state.done_through_ms else 'none (first run)'}")
    iterations = 0
    while not stop_event.is_set():
        now = now_fn()
        status, detail = await poll_once(live, deps, state, now, log_path)
        state.save(state_path)
        write_heartbeat(heartbeat_path, status=status, checked_at_ms=to_ms(now), last_tick_ms=state.last_tick_ms, detail=detail)
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=live.poll_seconds)
        except TimeoutError:
            pass
    log_event(log_path, event="stop")


__all__ = ["LoopDeps", "LoopState", "due_close_ms", "live_dir", "poll_once", "run_live_forever"]

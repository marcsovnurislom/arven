"""The always-on live process (`arven live run`): one asyncio loop, one DuckDB writer.

Every ``poll_seconds``:
- if a new 15m close is due (``event_delay_seconds`` after it) and not yet covered, run :func:`run_live_tick` in a
  worker thread (REST update -> strategies -> signal store -> Telegram outbox); a tick that did not reach the due close
  (data not published yet, stale data, an error) is simply retried at the next poll;
- once per new hour, optionally the Stage 8 hourly ``paper run`` (``run_legacy_paper``), so no second process (the
  old scheduled task) competes for the database;
- drain the Telegram outbox and answer bot commands (both never raise);
- once a day at ``daily_summary_hour_utc``, queue a daily summary; system alerts on start, on stale data and after
  repeated errors;
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
from arven.core.live_config import LiveConfig
from arven.core.time import from_ms, to_ms, utc_now
from arven.core.timeframes import Timeframe
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

    if deps.legacy_tick is not None and live.run_legacy_paper:
        hour = now_ms // HOUR_MS * HOUR_MS
        if state.legacy_hour_ms is None or state.legacy_hour_ms < hour:
            res, err = await _run(deps.legacy_tick, now)
            if err is None and getattr(res, "status", None) in ("ticked", "idle"):
                state.legacy_hour_ms = hour
            log_event(log_path, event="legacy_paper", status=getattr(res, "status", "error"), detail=err or getattr(res, "detail", ""))

    if deps.queue_daily_summary is not None and live.telegram.daily_summary_hour_utc is not None:
        today = now.astimezone(UTC).date().isoformat()
        if state.summary_date is None:
            state.summary_date = today  # first ever run: start with tomorrow's summary, not one at start-up
        elif now.astimezone(UTC).hour >= live.telegram.daily_summary_hour_utc and state.summary_date != today:
            _, err = await _run(deps.queue_daily_summary, today)
            if err is None:
                state.summary_date = today

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

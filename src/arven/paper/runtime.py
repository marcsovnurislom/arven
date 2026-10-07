"""Phase 5 of `docs/ARVEN_MASTER_PROMPT.md`: the always-on runtime (section 5.2) - one long-running
process that polls every ``poll_seconds`` instead of being re-invoked externally (Windows Task Scheduler)
once an hour the way Stage 8's `arven paper run` already is.

No new decision/execution logic lives here: every tick calls the existing, already-idempotent,
already-catch-up-capable `arven.paper.runs.run_paper_tick` unchanged - REST-tail/backfill, resampling and
the real `Stage5Pipeline`/`Backtester` are all reused exactly as Stage 8 built them (including its own fix
for the staged-bulk-load DuckDB trap `ARVEN_MASTER_PROMPT.md` section 5.2 warns about again - already
applied in `data/rest_ingestion.py`, not re-done here).

**Why a tick is skipped, not just cheap**: `run_paper_tick` has no "nothing changed" short-circuit of its
own - every call that reaches `execute_run` writes a brand-new run artifact under `data/paper/`, even when
the forward decision grid has not advanced since the last call. Polling every 10-20s without the guard in
`run_once` below (skip whenever `latest_forward_window_end_ms` has not changed) would flood that directory
with hundreds of fully-duplicate artifacts per hour - this is the one genuinely new piece of decision logic
here, and it is a pure, cheap, no-I/O time comparison, never a second guess about what to decide.

**"Persist the last processed event, restart-safe"**: already true of `run_paper_tick` itself (it always
replays `[forward_start, now)` fresh from the database, the source of truth - see `arven.paper.runs`'s own
module docstring), so this module adds no second, redundant cursor file. What *is* new here is purely for
external monitoring - a heartbeat file (``write_heartbeat``) and a structured, append-only tick log
(``log_event``) - and the polling loop's own in-memory "did the grid advance" check, which an ordinary
restart simply re-derives from scratch (one harmless, bounded extra tick right after restart, not a
correctness issue - see `docs/current_state.md`'s "Phase 5" section).

Graceful shutdown is cooperative (an injectable `asyncio.Event`), not signal-based: Windows' asyncio event
loop does not support POSIX signal handlers, so the CLI command built on `run_forever` instead installs a
plain `KeyboardInterrupt` handler (Ctrl+C) and an optional stop-file sentinel, both portable.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from arven.backtest.provider import SignalProvider
from arven.core.backtest_config import BacktestConfig
from arven.core.config import AppConfig
from arven.core.features_config import FeaturesConfig
from arven.core.time import to_ms, utc_now
from arven.data.download import Downloader
from arven.paper.runs import PaperTickOutcome, latest_forward_window_end_ms, run_paper_tick

# --- heartbeat (external monitoring: "is the process alive and doing something sane") ---------------


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write-then-rename so a concurrent reader (a health check, a dashboard) never observes a half
    written file - the same hazard this project is already careful about elsewhere (staged DB loads)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".heartbeat-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_heartbeat(path: Path, *, status: str, checked_at_ms: int, last_tick_ms: int | None, detail: str = "") -> None:
    _atomic_write_json(path, {"status": status, "checked_at_ms": checked_at_ms, "last_tick_ms": last_tick_ms, "detail": detail})


def read_heartbeat(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def is_stale(heartbeat: dict[str, Any] | None, now_ms: int, max_age_ms: int) -> bool:
    """True if there is no heartbeat at all, or its own last check is older than ``max_age_ms`` - the
    runtime equivalent of CLAUDE.md rule 5 ("missing or stale data => NO_TRADE"), for monitoring the
    *process* itself rather than any one data source."""
    return heartbeat is None or now_ms - heartbeat["checked_at_ms"] > max_age_ms


# --- structured, append-only tick log ------------------------------------------------------------------


def log_event(path: Path, **fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"time_ms": to_ms(utc_now()), **fields}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")


# --- one poll -------------------------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class TickResult:
    status: str  # "ticked" | "idle" | "error"
    detail: str
    outcome: PaperTickOutcome | None
    end_ms: int | None  # the latest_forward_window_end_ms observed this poll (None only on a clock/config error)


def run_once(
    app: AppConfig,
    fcfg: FeaturesConfig,
    bt_cfg: BacktestConfig,
    provider_factory: Callable[[], SignalProvider],
    *,
    now: datetime | None = None,
    downloader: Downloader | None = None,
    last_end_ms: int | None = None,
) -> TickResult:
    """One poll. Never raises: a transient REST failure or an unexpected error is reported in the result
    (``status="error"``) so the caller's loop can log it and keep polling - one bad tick must not kill an
    always-on process."""
    now = now or utc_now()
    try:
        end_ms = latest_forward_window_end_ms(app, now)
    except Exception as exc:  # noqa: BLE001 - a config/clock problem; still must not crash the loop
        return TickResult("error", f"{type(exc).__name__}: {exc}", None, None)
    if last_end_ms is not None and end_ms == last_end_ms:
        return TickResult("idle", "no new decision time since the last tick", None, end_ms)
    try:
        outcome = run_paper_tick(app, fcfg, bt_cfg, provider_factory(), now=now, downloader=downloader)
    except Exception as exc:  # noqa: BLE001
        return TickResult("error", f"{type(exc).__name__}: {exc}", None, end_ms)
    if not outcome.rest_summary.ok:
        return TickResult("error", f"REST errors: {outcome.rest_summary.errors}", outcome, end_ms)
    return TickResult("ticked", "", outcome, end_ms)


# --- the always-on loop ---------------------------------------------------------------------------------


async def run_forever(
    app: AppConfig,
    fcfg: FeaturesConfig,
    bt_cfg: BacktestConfig,
    provider_factory: Callable[[], SignalProvider],
    *,
    heartbeat_path: Path,
    log_path: Path,
    poll_seconds: float = 15.0,
    downloader_factory: Callable[[], Downloader] | None = None,
    now_fn: Callable[[], datetime] = utc_now,
    stop_event: asyncio.Event | None = None,
    max_iterations: int | None = None,
) -> None:
    """Poll forever (or ``max_iterations`` times, for tests) until ``stop_event`` is set. Each tick's
    (blocking) REST/DuckDB work runs in a worker thread (`asyncio.to_thread`) so the event loop - shared,
    in later phases, with Telegram/the web server - is never blocked by it.
    """
    stop_event = stop_event or asyncio.Event()
    last_end_ms: int | None = None
    last_tick_ms: int | None = None
    iterations = 0
    while not stop_event.is_set():
        now = now_fn()
        now_ms = to_ms(now)
        downloader = downloader_factory() if downloader_factory else None
        result = await asyncio.to_thread(
            run_once, app, fcfg, bt_cfg, provider_factory, now=now, downloader=downloader, last_end_ms=last_end_ms,
        )
        if result.end_ms is not None:
            last_end_ms = result.end_ms
        if result.status == "ticked":
            last_tick_ms = now_ms
        write_heartbeat(heartbeat_path, status=result.status, checked_at_ms=now_ms, last_tick_ms=last_tick_ms, detail=result.detail)
        run_id = result.outcome.run.run_id if result.outcome and result.outcome.run else None
        log_event(log_path, event="tick", status=result.status, detail=result.detail, run_id=run_id, end_ms=result.end_ms)
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            return
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
        except TimeoutError:
            pass

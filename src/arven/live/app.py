"""Wiring the live loop's side effects (:class:`arven.live.loop.LoopDeps`) to the real database, signal store and
Telegram outbox. The CLI calls :func:`build_deps`; tests build ``LoopDeps`` from fakes instead."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from arven.core.config import AppConfig
from arven.core.features_config import FeaturesConfig
from arven.core.live_config import LiveConfig
from arven.core.telegram_config import TelegramConfig, _load_dotenv_once
from arven.core.time import to_ms, utc_now
from arven.data.storage.db import connect
from arven.engine.signal_events import SignalUpdateKind
from arven.engine.signal_store import read_signals, read_updates
from arven.live.loop import LoopDeps, live_dir
from arven.live.registry import build_strategies
from arven.live.service import run_live_tick
from arven.paper.runs import paper_dir

DAY_MS = 86_400_000


def telegram_token_configured() -> bool:
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        _load_dotenv_once()
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))


def daily_summary_sections(app: AppConfig, day: str) -> tuple[Any, ...]:
    """Per strategy for the UTC day ``day`` (``YYYY-MM-DD``): signals announced, signals closed, net R of those closed."""
    from arven.telegram.messages import DailySummarySection

    start = to_ms(datetime.fromisoformat(day).replace(tzinfo=UTC))
    end = start + DAY_MS
    root = app.data.data_dir / "signals"
    summary_path = paper_dir(app) / "strategies_summary.json"
    closed_r = {}
    if summary_path.exists():
        closed_r = {d["signal_id"]: d["r"] for d in json.loads(summary_path.read_text(encoding="utf-8")).get("closed_signals", [])}
    out = []
    for sid in sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        sigs = read_signals(root, sid)
        announced = [s for s in sigs if start <= s.event_time_ms < end]
        closed_ids = {u.signal_id for u in read_updates(root, sid) if u.kind == SignalUpdateKind.CLOSED and start <= u.time_ms < end}
        grade = sigs[-1].grade.value if sigs else "EXPERIMENTAL"
        if announced or closed_ids:
            out.append(DailySummarySection(sid, grade, len(announced), len(closed_ids), float(sum(closed_r.get(i) or 0.0 for i in closed_ids))))
    return tuple(out)


def build_deps(
    app: AppConfig, fcfg: FeaturesConfig, live: LiveConfig, config_dir: Path, tcfg: TelegramConfig, chat_ids: frozenset[str],
    *, legacy_tick: Callable[[datetime], Any] | None = None,
) -> LoopDeps:
    from arven.telegram.messages import format_daily_summary, format_system_alert
    from arven.telegram.outbox import enqueue
    from arven.telegram.runs import run_telegram_commands_tick, run_telegram_send_tick

    strategies = build_strategies(live)  # validates every enabled strategy's config at start-up
    db = app.data.database_path
    alerts_on = live.telegram.enabled and bool(chat_ids)

    def live_tick(now: datetime) -> Any:
        return run_live_tick(app, fcfg, live, config_dir, now=now, chat_ids=chat_ids if alerts_on else frozenset(), strategies=strategies)

    def send() -> Any:
        with connect(db) as con:
            return run_telegram_send_tick(con, tcfg)

    def commands(last_update_id: int) -> int:
        quick = tcfg.model_copy(update={"command_poll_timeout_seconds": 0})  # never block the loop on a long poll
        with connect(db) as con:
            _, new_id = run_telegram_commands_tick(con, quick, app.data.data_dir / "signals", live_dir(app) / "heartbeat.json",
                                                   last_update_id=last_update_id, allowed_chats=chat_ids)
        return new_id

    def queue_system(key: str, title: str, detail: str) -> None:
        now_ms = to_ms(utc_now())
        with connect(db) as con:
            for chat in sorted(chat_ids):
                enqueue(con, signal_id="system", event_type=key, chat_id=chat, text=format_system_alert(title, detail), now_ms=now_ms)

    def queue_daily(today: str) -> None:
        day = (datetime.fromisoformat(today) - timedelta(days=1)).date().isoformat()  # summarise the day that just ended
        text = format_daily_summary(day, daily_summary_sections(app, day))
        now_ms = to_ms(utc_now())
        with connect(db) as con:
            for chat in sorted(chat_ids):
                enqueue(con, signal_id="daily_summary", event_type=day, chat_id=chat, text=text, now_ms=now_ms)

    return LoopDeps(
        live_tick=live_tick,
        legacy_tick=legacy_tick if live.run_legacy_paper else None,
        send_telegram=send if live.telegram.enabled else None,
        poll_commands=commands if live.telegram.commands and chat_ids and telegram_token_configured() else None,
        queue_system=queue_system if alerts_on else None,
        queue_daily_summary=queue_daily if alerts_on else None,
    )


__all__ = ["build_deps", "daily_summary_sections", "telegram_token_configured"]

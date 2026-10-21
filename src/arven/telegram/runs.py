"""Composition roots for Phase 6: draining the outbox (``run_telegram_send_tick``) and polling/replying to
bot commands (``run_telegram_commands_tick``). All DB/network I/O lives here, mirroring
``arven.news.runs``'s own split between storage, the API call, and composition.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from arven.core.telegram_config import TelegramConfig
from arven.core.time import to_ms, utc_now
from arven.telegram.client import CAPTION_LIMIT, get_updates, send_message, send_photo
from arven.telegram.commands import NOT_AUTHORIZED_TEXT, CommandContext, handle_command
from arven.telegram.outbox import is_paused, load_chart, mark_failed, mark_sent, pending_entries


@dataclass
class SendTickSummary:
    sent: int = 0
    skipped_paused: int = 0
    failed: int = 0
    dry_run: bool = False
    errors: list[str] = field(default_factory=list)
    photos: int = 0  # sent as a picture with the text as its caption
    photo_fallbacks: list[str] = field(default_factory=list)  # a picture failed; the text was sent instead

    @property
    def ok(self) -> bool:
        return not self.errors


def run_telegram_send_tick(
    con: duckdb.DuckDBPyConnection, cfg: TelegramConfig, *,
    token: str | None = None, opener=urllib.request.urlopen, sleep=time.sleep, now=None, charts_root: Path | None = None,
) -> SendTickSummary:
    """Drain pending outbox entries, oldest first. An entry with a stored picture (``charts_root``,
    ``telegram.outbox.save_chart``) goes out as a photo with its text as the caption; if the picture cannot be sent
    (or the text is longer than a caption may be) the text is sent on its own. Never raises: one entry's send failure is recorded on
    its own row (``mark_failed``) and the tick continues with the next entry - the same
    never-let-one-bad-item-stop-the-rest discipline ``arven.news.runs.run_news_tick`` already uses."""
    summary = SendTickSummary(dry_run=cfg.dry_run)
    now_ts = to_ms(now) if now is not None else to_ms(utc_now())
    for entry in pending_entries(con):
        if is_paused(con, entry.chat_id):
            summary.skipped_paused += 1
            continue
        if cfg.dry_run:
            mark_sent(con, entry.outbox_id, telegram_message_id=-1, now_ms=now_ts)
            summary.sent += 1
            continue
        try:
            png = load_chart(charts_root, entry.signal_id, entry.event_type)
            sent = None
            if png is not None and len(entry.text) <= CAPTION_LIMIT:
                try:
                    sent = send_photo(entry.chat_id, png, entry.text, token=token, max_attempts=cfg.max_send_attempts, opener=opener, sleep=sleep)
                    summary.photos += 1
                except Exception as exc:  # noqa: BLE001 - the picture is optional: fall back to the text, never lose the alert
                    summary.photo_fallbacks.append(f"{entry.outbox_id}: {exc}")
            if sent is None:
                sent = send_message(entry.chat_id, entry.text, token=token, max_attempts=cfg.max_send_attempts, opener=opener, sleep=sleep)
            mark_sent(con, entry.outbox_id, telegram_message_id=sent.message_id, now_ms=now_ts)
            summary.sent += 1
        except Exception as exc:  # noqa: BLE001 - recorded on this row only, other entries still get a chance
            mark_failed(con, entry.outbox_id, error=str(exc), max_attempts=cfg.max_send_attempts)
            summary.failed += 1
            summary.errors.append(f"{entry.outbox_id}: {exc}")
    return summary


@dataclass
class CommandsTickSummary:
    updates_seen: int = 0
    replied: int = 0
    unauthorized: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def read_update_cursor(path: Path) -> int:
    """The last processed Telegram ``update_id`` (0 if never run). Losing this file in a crash costs at
    most a few harmlessly-replayed updates (every command is either read-only or idempotent, see
    ``telegram.outbox``'s pause/resume) - not worth the atomic-write ritual ``paper.runtime``'s heartbeat
    uses for something higher-stakes."""
    if not path.exists():
        return 0
    return json.loads(path.read_text(encoding="utf-8"))["last_update_id"]


def write_update_cursor(path: Path, last_update_id: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_update_id": last_update_id}), encoding="utf-8")


def run_telegram_commands_tick(
    con: duckdb.DuckDBPyConnection, cfg: TelegramConfig, signals_root: Path, heartbeat_path: Path, *,
    last_update_id: int, allowed_chats: frozenset[str], token: str | None = None,
    opener=urllib.request.urlopen, sleep=time.sleep, now=None, extra_signal_roots: tuple[tuple[str, Path], ...] = (),
    lang: str = "en",
) -> tuple[CommandsTickSummary, int]:
    """One ``getUpdates`` poll + reply cycle. Returns the summary and the new ``last_update_id`` the
    caller should persist (`write_update_cursor`) so no update is processed twice next time. Never raises:
    a missing bot token or a transient network failure on the poll itself is recorded in the summary
    (`errors`), the same discipline every other tick-based composition root in this project already
    follows for its own primary call (`arven.news.runs.run_news_tick`'s feed fetch,
    `arven.paper.runtime.run_once`'s REST tail)."""
    summary = CommandsTickSummary()
    now_ts = to_ms(now) if now is not None else to_ms(utc_now())
    try:
        updates = get_updates(last_update_id + 1, timeout_seconds=cfg.command_poll_timeout_seconds, token=token, opener=opener, sleep=sleep)
    except Exception as exc:  # noqa: BLE001 - e.g. TELEGRAM_BOT_TOKEN not configured, or a network failure
        summary.errors.append(f"getUpdates failed: {exc}")
        return summary, last_update_id
    ctx = CommandContext(con, signals_root, heartbeat_path, now_ts, extra_signal_roots, lang)
    new_last_id = last_update_id
    for update in updates:
        summary.updates_seen += 1
        new_last_id = max(new_last_id, update.update_id)
        if update.chat_id not in allowed_chats:
            summary.unauthorized += 1
            try:
                send_message(update.chat_id, NOT_AUTHORIZED_TEXT, token=token, opener=opener, sleep=sleep)
            except Exception as exc:  # noqa: BLE001
                summary.errors.append(f"reply to unauthorized chat: {exc}")
            continue
        reply = handle_command(update.text, update.chat_id, ctx)
        if reply is None:
            continue
        try:
            send_message(update.chat_id, reply, token=token, opener=opener, sleep=sleep)
            summary.replied += 1
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"reply failed: {exc}")
    return summary, new_last_id

"""The persisted outbox (``telegram_outbox``): "idempotent sends (dedupe by signal_id + event type,
persisted outbox table)" (section 5.4). Enqueuing the same ``(signal_id, event_type, chat_id)`` twice is a
no-op - the id is a deterministic hash of exactly those three fields, and the primary key does the rest.
No network call happens here; this module is DB I/O only, mirroring ``arven.news.runs``'s own split
between storage and the actual API call.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import duckdb


def outbox_id(signal_id: str, event_type: str, chat_id: str) -> str:
    return hashlib.sha256(f"{signal_id}:{event_type}:{chat_id}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    outbox_id: str
    signal_id: str
    event_type: str
    chat_id: str
    text: str
    status: str
    telegram_message_id: int | None
    attempts: int
    last_error: str | None
    created_at_ms: int
    sent_at_ms: int | None


def enqueue(con: duckdb.DuckDBPyConnection, *, signal_id: str, event_type: str, chat_id: str, text: str, now_ms: int) -> str:
    """Insert a pending entry, or do nothing if this exact (signal_id, event_type, chat_id) already exists -
    the caller never needs its own "have I already queued this" check."""
    oid = outbox_id(signal_id, event_type, chat_id)
    con.execute(
        "INSERT INTO telegram_outbox (outbox_id, signal_id, event_type, chat_id, text, status, telegram_message_id, "
        "attempts, last_error, created_at_ms, sent_at_ms) VALUES (?, ?, ?, ?, ?, 'pending', NULL, 0, NULL, ?, NULL) "
        "ON CONFLICT (outbox_id) DO NOTHING",
        [oid, signal_id, event_type, chat_id, text, now_ms],
    )
    return oid


def _row_to_entry(r: tuple) -> OutboxEntry:
    return OutboxEntry(*r)


def pending_entries(con: duckdb.DuckDBPyConnection, limit: int = 50) -> list[OutboxEntry]:
    rows = con.execute(
        "SELECT outbox_id, signal_id, event_type, chat_id, text, status, telegram_message_id, attempts, "
        "last_error, created_at_ms, sent_at_ms FROM telegram_outbox WHERE status = 'pending' "
        "ORDER BY created_at_ms ASC LIMIT ?",
        [limit],
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


def mark_sent(con: duckdb.DuckDBPyConnection, oid: str, *, telegram_message_id: int, now_ms: int) -> None:
    con.execute(
        "UPDATE telegram_outbox SET status = 'sent', telegram_message_id = ?, sent_at_ms = ?, "
        "attempts = attempts + 1 WHERE outbox_id = ?",
        [telegram_message_id, now_ms, oid],
    )


def mark_failed(con: duckdb.DuckDBPyConnection, oid: str, *, error: str, max_attempts: int) -> None:
    """After ``max_attempts`` the entry becomes permanently ``"failed"`` (never retried again, never
    silently dropped - visible in `telegram_outbox` either way) rather than retried forever."""
    con.execute(
        "UPDATE telegram_outbox SET attempts = attempts + 1, last_error = ?, "
        "status = CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE 'pending' END WHERE outbox_id = ?",
        [error, max_attempts, oid],
    )


def get_entry(con: duckdb.DuckDBPyConnection, oid: str) -> OutboxEntry | None:
    row = con.execute(
        "SELECT outbox_id, signal_id, event_type, chat_id, text, status, telegram_message_id, attempts, "
        "last_error, created_at_ms, sent_at_ms FROM telegram_outbox WHERE outbox_id = ?",
        [oid],
    ).fetchone()
    return _row_to_entry(row) if row else None


# --- signal pictures (docs/FEATURES_PLAN.md H5): one PNG per (signal_id, event_type), shared by every chat ---------
# Files next to the outbox instead of a table column: the entry stays text (the fallback), the picture is optional.


def charts_dir(data_dir: Path) -> Path:
    """Every market's pictures in one place: the one outbox (and its sender) serves all markets."""
    return data_dir / "telegram" / "charts"


def chart_path(root: Path, signal_id: str, event_type: str) -> Path:
    return root / f"{hashlib.sha256(f'{signal_id}:{event_type}'.encode()).hexdigest()[:32]}.png"


def save_chart(root: Path, signal_id: str, event_type: str, png: bytes) -> Path:
    path = chart_path(root, signal_id, event_type)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(png)
    tmp.replace(path)  # atomic: the sender never reads a half-written picture
    return path


def load_chart(root: Path | None, signal_id: str, event_type: str) -> bytes | None:
    if root is None:
        return None
    path = chart_path(root, signal_id, event_type)
    return path.read_bytes() if path.exists() else None


# --- per-chat pause/resume (section 5.4's /pause, /resume - notification muting only, never the trading loop) ---


def set_paused(con: duckdb.DuckDBPyConnection, chat_id: str, paused: bool, *, now_ms: int) -> None:
    con.execute(
        "INSERT INTO telegram_chat_state (chat_id, paused, updated_at_ms) VALUES (?, ?, ?) "
        "ON CONFLICT (chat_id) DO UPDATE SET paused = excluded.paused, updated_at_ms = excluded.updated_at_ms",
        [chat_id, paused, now_ms],
    )


def is_paused(con: duckdb.DuckDBPyConnection, chat_id: str) -> bool:
    row = con.execute("SELECT paused FROM telegram_chat_state WHERE chat_id = ?", [chat_id]).fetchone()
    return bool(row[0]) if row else False

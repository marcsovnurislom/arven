"""Bot commands (section 5.4): ``/start /status /signals /history /strategies /pause /resume /help``.
Every command is read-only over already-stored data (the heartbeat, the signal store) or toggles this
chat's own notification muting (``/pause``/``/resume`` - never the trading loop itself, see
``telegram.outbox``'s module docstring). No command can trigger a backtest, a paper tick, or any write
outside ``telegram_chat_state``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

from arven.core.time import from_ms
from arven.engine.signal_store import read_signals
from arven.paper.runtime import read_heartbeat
from arven.telegram.outbox import is_paused, set_paused

HELP_TEXT = (
    "Commands:\n"
    "/status - runtime heartbeat (alive? last tick? any error?)\n"
    "/signals - most recent signals across all strategies\n"
    "/history - longer signal history\n"
    "/strategies - known strategies and their current grade\n"
    "/pause - stop sending alerts to this chat\n"
    "/resume - resume alerts to this chat\n"
    "/help - this message"
)
WELCOME_TEXT = "ARVEN paper-signal bot. Research only - never a real order (CLAUDE.md rule 12). /help for commands."
NOT_AUTHORIZED_TEXT = "This chat is not authorized."


@dataclass(frozen=True, eq=False)
class CommandContext:
    con: duckdb.DuckDBPyConnection
    signals_root: Path
    heartbeat_path: Path
    now_ms: int


def _strategy_ids(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def _recent_signals_across_strategies(root: Path, n: int) -> list:
    all_signals = []
    for strategy_id in _strategy_ids(root):
        all_signals.extend(read_signals(root, strategy_id))
    all_signals.sort(key=lambda s: s.event_time_ms)
    return all_signals[-n:]


def _cmd_status(ctx: CommandContext) -> str:
    hb = read_heartbeat(ctx.heartbeat_path)
    if hb is None:
        return "No heartbeat recorded yet - the runtime may never have been started."
    age_s = (ctx.now_ms - hb["checked_at_ms"]) / 1000
    last_tick = from_ms(hb["last_tick_ms"]).isoformat() if hb["last_tick_ms"] else "never"
    lines = [f"status={hb['status']}  checked {age_s:.0f}s ago  last_tick={last_tick}"]
    if hb["detail"]:
        lines.append(f"detail: {hb['detail']}")
    return "\n".join(lines)


def _cmd_signals(ctx: CommandContext, n: int = 5) -> str:
    signals = _recent_signals_across_strategies(ctx.signals_root, n)
    if not signals:
        return "No signals recorded yet."
    return "\n".join(
        f"{from_ms(s.event_time_ms).isoformat()}  {s.symbol} {'LONG' if s.side == 1 else 'SHORT'} "
        f"({s.strategy_id}) [{s.grade.value}]"
        for s in signals
    )


def _cmd_strategies(ctx: CommandContext) -> str:
    ids = _strategy_ids(ctx.signals_root)
    if not ids:
        return "No strategies with recorded signals yet."
    lines = []
    for sid in ids:
        sigs = read_signals(ctx.signals_root, sid)
        grade = sigs[-1].grade.value if sigs else "EXPERIMENTAL"
        lines.append(f"{sid}: {len(sigs)} signals, current grade {grade}")
    return "\n".join(lines)


def handle_command(text: str, chat_id: str, ctx: CommandContext) -> str | None:
    """Returns the reply text, or ``None`` if ``text`` was not a recognised command (silently ignored -
    this is a signal/alerts bot, not a general chat assistant)."""
    command = text.strip().split()[0].split("@")[0].lower() if text.strip() else ""
    if command == "/start":
        return WELCOME_TEXT
    if command == "/help":
        return HELP_TEXT
    if command == "/status":
        return _cmd_status(ctx)
    if command == "/signals":
        return _cmd_signals(ctx, n=5)
    if command == "/history":
        return _cmd_signals(ctx, n=20)
    if command == "/strategies":
        return _cmd_strategies(ctx)
    if command == "/pause":
        set_paused(ctx.con, chat_id, True, now_ms=ctx.now_ms)
        return "Paused - you will not receive alerts until /resume."
    if command == "/resume":
        set_paused(ctx.con, chat_id, False, now_ms=ctx.now_ms)
        return "Resumed - alerts will be sent again."
    return None


__all__ = ["CommandContext", "NOT_AUTHORIZED_TEXT", "handle_command", "is_paused"]

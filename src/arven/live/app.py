"""Wiring the live loop's side effects (:class:`arven.live.loop.LoopDeps`) to the real database, signal store and
Telegram outbox. The CLI calls :func:`build_deps`; tests build ``LoopDeps`` from fakes instead."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from arven.core.config import AppConfig
from arven.core.features_config import FeaturesConfig
from arven.core.live_config import LiveConfig, LiveMarketConfig
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


def daily_summary_sections(app: AppConfig, day: str, label: str = "") -> tuple[Any, ...]:
    """Per strategy for the UTC day ``day`` (``YYYY-MM-DD``): signals announced, signals closed, net R of those closed.
    ``label`` prefixes the strategy ids of a further market (e.g. "Gold")."""
    from arven.telegram.messages import DailySummarySection

    start = to_ms(datetime.fromisoformat(day).replace(tzinfo=UTC))
    end = start + DAY_MS
    root = app.market_root / "signals"
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
            out.append(DailySummarySection(f"{label}: {sid}" if label else sid, grade, len(announced), len(closed_ids),
                                           float(sum(closed_r.get(i) or 0.0 for i in closed_ids))))
    return tuple(out)


def weekly_report_rows(app: AppConfig, today: str, label: str = "") -> tuple[Any, ...]:
    """Per strategy: the whole forward record and its review (from ``strategies_summary.json``) plus the signals that
    closed in the 7 UTC days before ``today``. ``label`` prefixes the strategy ids of a further market."""
    from arven.telegram.messages import WeeklyReportRow

    summary_path = paper_dir(app) / "strategies_summary.json"
    if not summary_path.exists():
        return ()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    end = to_ms(datetime.fromisoformat(today).replace(tzinfo=UTC))
    start = end - 7 * DAY_MS
    week: dict[str, list[float]] = {}
    for d in summary.get("closed_signals", []):
        if start <= d["closed_ms"] < end and d.get("r") is not None:
            week.setdefault(d["strategy"], []).append(float(d["r"]))
    root = app.market_root / "signals"
    rows = []
    for sid, st in sorted(summary.get("strategies", {}).items()):
        rv = st.get("review") or {}
        sigs = read_signals(root, sid) if (root / sid).exists() else []
        rows.append(WeeklyReportRow(
            f"{label}: {sid}" if label else sid, sigs[-1].grade.value if sigs else "EXPERIMENTAL", st.get("closed", 0), st.get("open", 0) + st.get("pending", 0),
            float(st.get("total_r") or 0.0), st.get("win_rate"), st.get("mean_r"), rv.get("ci_low"), rv.get("ci_high"),
            rv.get("max_dd_r"), rv.get("verdict", "too_few"), len(week.get(sid, [])), float(sum(week.get(sid, []))),
        ))
    return tuple(rows)


def run_maintenance(
    app: AppConfig, live: LiveConfig, config_dir: Path, now: datetime, market_apps: tuple[AppConfig, ...] = (),
) -> dict[str, Any]:
    """The daily housekeeping (``config/live.yaml`` ``maintenance``): backup, then the paper-run retention rule (also for
    the further markets' own paper directories)."""
    from arven.live.backup import make_backup
    from arven.live.maintenance import prune_paper_runs

    m = live.maintenance
    out: dict[str, Any] = {}
    if m.backup:
        res = make_backup(app.data.data_dir, config_dir, now, keep=m.backup_keep,
                          database_path=app.data.database_path if m.backup_with_db else None)
        out["backup"] = res.path.name
        out["backup_mb"] = round(res.path.stat().st_size / 1e6, 1)
    if m.paper_keep_recent is not None:
        pr = prune_paper_runs(paper_dir(app), m.paper_keep_recent)
        out["paper_runs_kept"], out["paper_runs_removed"] = len(pr.kept), len(pr.removed)
        out["paper_mb_freed"] = round(pr.bytes_freed / 1e6, 1)
        for a in market_apps:
            if paper_dir(a).is_dir():
                mp = prune_paper_runs(paper_dir(a), m.paper_keep_recent)
                out[f"{a.instrument}_paper_runs_removed"] = len(mp.removed)
    return out


def build_deps(
    app: AppConfig, fcfg: FeaturesConfig, live: LiveConfig, config_dir: Path, tcfg: TelegramConfig, chat_ids: frozenset[str],
    *, legacy_tick: Callable[[datetime], Any] | None = None,
    markets: Mapping[str, tuple[LiveMarketConfig, AppConfig]] | None = None,
    market_legacy_ticks: Mapping[str, Callable[[datetime], Any]] | None = None,
) -> LoopDeps:
    """``markets``: the further markets to run (``config/live.yaml`` ``markets``), by instrument, with their loaded
    instrument configuration; their legacy S1-S3 paper ticks in ``market_legacy_ticks``."""
    from arven.telegram.messages import format_daily_summary, format_system_alert
    from arven.telegram.outbox import charts_dir, enqueue
    from arven.telegram.runs import run_telegram_commands_tick, run_telegram_send_tick

    strategies = build_strategies(live)  # validates every enabled strategy's config at start-up
    db = app.data.database_path
    alerts_on = live.telegram.enabled and bool(chat_ids)
    lang = live.telegram.language
    markets = dict(markets or {})
    labels = {name: (m.title or name) for name, (m, _) in markets.items()}

    def market_tick(m_live: LiveConfig, m_app: AppConfig, m_strategies: list) -> Callable[[datetime], Any]:
        return lambda now: run_live_tick(m_app, fcfg, m_live, config_dir, now=now, chat_ids=chat_ids if alerts_on else frozenset(),
                                         strategies=m_strategies)

    market_ticks = {}
    for name, (m, m_app) in markets.items():
        m_live = live.for_market(m)
        market_ticks[name] = market_tick(m_live, m_app, build_strategies(m_live))

    def live_tick(now: datetime) -> Any:
        return run_live_tick(app, fcfg, live, config_dir, now=now, chat_ids=chat_ids if alerts_on else frozenset(), strategies=strategies)

    def send() -> Any:
        with connect(db) as con:
            return run_telegram_send_tick(con, tcfg, charts_root=charts_dir(app.data.data_dir))

    def commands(last_update_id: int) -> int:
        quick = tcfg.model_copy(update={"command_poll_timeout_seconds": 0})  # never block the loop on a long poll
        with connect(db) as con:
            _, new_id = run_telegram_commands_tick(con, quick, app.data.data_dir / "signals", live_dir(app) / "heartbeat.json",
                                                   last_update_id=last_update_id, allowed_chats=chat_ids, lang=lang,
                                                   extra_signal_roots=tuple((labels[n], a.market_root / "signals") for n, (_, a) in markets.items()))
        return new_id

    def queue_system(key: str, title: str, detail: str) -> None:
        now_ms = to_ms(utc_now())
        with connect(db) as con:
            for chat in sorted(chat_ids):
                enqueue(con, signal_id="system", event_type=key, chat_id=chat, text=format_system_alert(title, detail, lang), now_ms=now_ms)

    def queue_daily(today: str) -> None:
        day = (datetime.fromisoformat(today) - timedelta(days=1)).date().isoformat()  # summarise the day that just ended
        sections = daily_summary_sections(app, day) + tuple(
            x for n, (_, a) in markets.items() for x in daily_summary_sections(a, day, labels[n]))
        text = format_daily_summary(day, sections, lang)
        now_ms = to_ms(utc_now())
        with connect(db) as con:
            for chat in sorted(chat_ids):
                enqueue(con, signal_id="daily_summary", event_type=day, chat_id=chat, text=text, now_ms=now_ms)

    def queue_weekly(today: str) -> None:
        from arven.telegram.messages import format_weekly_report

        end = datetime.fromisoformat(today).date()
        label = f"{(end - timedelta(days=7)).isoformat()} - {(end - timedelta(days=1)).isoformat()}"
        since = app.splits.forward_start.date().isoformat()
        rows = weekly_report_rows(app, today) + tuple(x for n, (_, a) in markets.items() for x in weekly_report_rows(a, today, labels[n]))
        text = format_weekly_report(label, since, rows, lang)
        now_ms = to_ms(utc_now())
        with connect(db) as con:
            for chat in sorted(chat_ids):
                enqueue(con, signal_id="weekly_report", event_type=today, chat_id=chat, text=text, now_ms=now_ms)

    def maintenance(now: datetime) -> dict[str, Any]:
        return run_maintenance(app, live, config_dir, now, tuple(a for _, a in markets.values()))

    return LoopDeps(
        live_tick=live_tick,
        legacy_tick=legacy_tick if live.run_legacy_paper else None,
        send_telegram=send if live.telegram.enabled else None,
        poll_commands=commands if live.telegram.commands and chat_ids and telegram_token_configured() else None,
        queue_system=queue_system if alerts_on else None,
        queue_daily_summary=queue_daily if alerts_on else None,
        queue_weekly_report=queue_weekly if alerts_on else None,
        maintenance=maintenance if live.maintenance.hour_utc is not None else None,
        market_ticks=market_ticks,
        market_legacy_ticks=dict(market_legacy_ticks or {}),
    )


__all__ = ["build_deps", "daily_summary_sections", "run_maintenance", "telegram_token_configured", "weekly_report_rows"]

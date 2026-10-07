"""Stage 10: gather already-stored artifacts (the latest paper run's metrics/decisions, recent structured
news) into one plain-text context block for Q&A (``llm.qa``). Read-only; never computes anything new -
every number here was already written to disk or the database by an earlier stage's own run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from arven.core.config import AppConfig
from arven.core.time import from_ms


def _paper_dir(app: AppConfig) -> Path:
    # Mirrors arven.paper.runs.paper_dir exactly (data_dir / "paper") without importing arven.paper itself -
    # llm/ stays a leaf package (see llm/__init__.py's module docstring) even though this path is trivial.
    return app.data.data_dir / "paper"


def latest_paper_run_dir(app: AppConfig) -> Path | None:
    index = _paper_dir(app) / "runs.jsonl"
    if not index.exists():
        return None
    lines = index.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        return None
    entry = json.loads(lines[-1])
    run_dir = _paper_dir(app) / entry["run_id"]
    return run_dir if run_dir.exists() else None


def load_latest_paper_context(app: AppConfig, n_decisions: int = 20) -> dict[str, Any] | None:
    run_dir = latest_paper_run_dir(app)
    if run_dir is None:
        return None
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    decisions_path = run_dir / "decisions.jsonl"
    decisions: list[dict[str, Any]] = []
    if decisions_path.exists():
        lines = decisions_path.read_text(encoding="utf-8").strip().splitlines()
        decisions = [json.loads(line) for line in lines[-n_decisions:]] if lines else []
    return {"run_id": manifest["run_id"], "metrics": manifest["metrics"], "recent_decisions": decisions}


def load_recent_news(app: AppConfig, limit: int = 10) -> list[dict[str, Any]]:
    if not app.data.database_path.exists():
        return []
    con = duckdb.connect(str(app.data.database_path), read_only=True)
    try:
        has_table = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'news_items'"
        ).fetchone()
        if not has_table:
            return []
        rows = con.execute(
            """
            SELECT n.published_at_ms, n.source, n.title, e.event_type, e.direction_bias, e.summary
            FROM news_items n LEFT JOIN news_events e ON e.news_id = n.news_id
            ORDER BY n.published_at_ms DESC LIMIT ?
            """,
            [limit],
        ).fetchall()
    finally:
        con.close()
    return [
        {"published_at": from_ms(r[0]).isoformat(), "source": r[1], "title": r[2], "event_type": r[3], "direction_bias": r[4], "summary": r[5]}
        for r in rows
    ]


def format_context(paper_ctx: dict[str, Any] | None, news: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    if paper_ctx is None:
        lines.append("No paper-trading run has been recorded yet.")
    else:
        lines.append(f"Latest paper run: {paper_ctx['run_id']}")
        lines.append(f"Metrics: {json.dumps(paper_ctx['metrics'], sort_keys=True)}")
        lines.append(f"Recent decisions (oldest first, most recent {len(paper_ctx['recent_decisions'])}):")
        for d in paper_ctx["recent_decisions"]:
            lines.append(f"  {json.dumps(d, sort_keys=True)}")
    if news:
        lines.append("Recent news items:")
        for n in news:
            lines.append(f"  {json.dumps(n, sort_keys=True)}")
    else:
        lines.append("No news items recorded yet.")
    return "\n".join(lines)


def build_context(app: AppConfig, *, n_decisions: int = 20, n_news: int = 10) -> str:
    return format_context(load_latest_paper_context(app, n_decisions), load_recent_news(app, n_news))

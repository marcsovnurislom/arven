"""Stage 9b composition root: fetch RSS -> store new items -> structure up to a capped number of
unstructured items via the LLM -> store results. All DB I/O lives here (mirrors ``runs.py``/``paper/runs.py``'s
own role for earlier stages); ``news.rss``/``news.schema``/``news.structure``/``llm.anthropic_client`` stay
pure or I/O-isolated to exactly one external call each.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from arven.core.config import AppConfig
from arven.core.news_config import NewsConfig
from arven.core.time import to_ms, utc_now
from arven.data.download import Downloader, RetryPolicy
from arven.data.storage.db import now_ms
from arven.news.rss import RawNewsItem, fetch_feed, parse_rss
from arven.news.schema import PROMPT_VERSION
from arven.news.structure import StructuredResult, structure_item


@dataclass
class NewsTickSummary:
    items_fetched: int = 0
    items_new: int = 0
    items_structured: int = 0
    items_parse_failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _store_new_items(con: duckdb.DuckDBPyConnection, items: tuple[RawNewsItem, ...], now: int) -> int:
    written = 0
    for it in items:
        exists = con.execute("SELECT 1 FROM news_items WHERE news_id = ?", [it.news_id]).fetchone()
        if exists:
            continue
        available_at = max(it.published_at_ms, now)
        con.execute(
            "INSERT INTO news_items (news_id, source, url, title, published_at_ms, ingested_at_ms, available_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [it.news_id, it.source, it.url, it.title, it.published_at_ms, now, available_at],
        )
        written += 1
    return written


def _unstructured_items(con: duckdb.DuckDBPyConnection, llm_model: str, prompt_version: str, limit: int) -> list[tuple[str, str]]:
    rows = con.execute(
        """
        SELECT n.news_id, n.title FROM news_items n
        LEFT JOIN news_events e ON e.news_id = n.news_id AND e.llm_model = ? AND e.prompt_version = ?
        WHERE e.news_id IS NULL
        ORDER BY n.published_at_ms ASC
        LIMIT ?
        """,
        [llm_model, prompt_version, limit],
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _store_result(con: duckdb.DuckDBPyConnection, r: StructuredResult, processed_at: int) -> None:
    e = r.event
    con.execute(
        "INSERT OR REPLACE INTO news_events "
        "(news_id, llm_model, prompt_version, event_type, asset_relevance, direction_bias, severity, "
        " confidence, summary, raw_response, parse_error, processed_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            r.news_id, r.llm_model, r.prompt_version,
            e.event_type if e else None, e.asset_relevance if e else None, e.direction_bias if e else None,
            e.severity if e else None, e.confidence if e else None, e.summary if e else None,
            r.raw_response, r.parse_error, processed_at,
        ],
    )


def run_news_tick(
    app: AppConfig, news_cfg: NewsConfig, con: duckdb.DuckDBPyConnection, *,
    downloader: Downloader | None = None, api_key: str | None = None, now=None,
) -> NewsTickSummary:
    """One ``arven news run`` invocation. Idempotent: re-running never re-fetches an already-stored item
    (deduplicated by ``news_id = sha256(source, url)``) and never re-structures an item that already has a
    row for this exact ``(llm_model, prompt_version)`` - a prompt or model change naturally produces a new
    row rather than overwriting the old one, so a before/after comparison is always possible."""
    summary = NewsTickSummary()
    downloader = downloader or Downloader(RetryPolicy.from_config(app.download))
    now_ts = to_ms(now) if now is not None else now_ms()

    for source, url in news_cfg.feeds.items():
        try:
            raw = fetch_feed(downloader, url)
            items = parse_rss(raw, source)
        except Exception as exc:  # noqa: BLE001 - recorded per feed, other feeds still get a chance
            summary.errors.append(f"{source}: fetch/parse failed: {exc}")
            continue
        summary.items_fetched += len(items)
        summary.items_new += _store_new_items(con, items, now_ts)

    pending = _unstructured_items(con, news_cfg.llm_model, PROMPT_VERSION, news_cfg.max_items_per_tick)
    for news_id, title in pending:
        try:
            result = structure_item(news_id, title, llm_model=news_cfg.llm_model, max_tokens=news_cfg.max_tokens, api_key=api_key)
        except Exception as exc:  # noqa: BLE001 - recorded, the tick continues with the next item
            summary.errors.append(f"structuring {news_id}: {exc}")
            continue
        _store_result(con, result, now_ms())
        summary.input_tokens += result.input_tokens
        summary.output_tokens += result.output_tokens
        if result.event is not None:
            summary.items_structured += 1
        else:
            summary.items_parse_failed += 1
    return summary

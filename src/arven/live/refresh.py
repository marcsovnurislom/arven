"""Fresh 1m data for every market between 15m closes (2026-10-27: the data-age gauge showed up to 15 minutes).

Three steps so the database is held as briefly as possible (the web app reads it many times a minute):
1. one short connection: the last stored minute of every symbol;
2. no connection: every market's new closed minutes are fetched at the same time (Binance REST klines, or Kraken for
   spot forex) - the same normalisation and session filter the tick's REST tail uses;
3. one short connection: the minutes are written and their derived bars rebuilt (``resample`` over the same range the
   tick's update would rebuild).
Strategies are not run here; the 15m tick still evaluates every close and starts with its own REST tail. Errors are
returned per market, never raised. Public endpoints only (CLAUDE.md rule 12).
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from arven.core.config import AppConfig
from arven.core.time import from_ms, to_ms
from arven.core.timeframes import Timeframe
from arven.data.adapters.binance_rest import fetch_klines
from arven.data.download import Downloader, RetryPolicy
from arven.data.kraken_live import fetch_new as kraken_fetch
from arven.data.kraken_live import write_new as kraken_write
from arven.data.resample import DERIVED_TIMEFRAMES, resample
from arven.data.rest_ingestion import RestTailSummary, _write_klines
from arven.data.storage.db import connect

MIN_MS = Timeframe.M1.ms
BUFFER_MS = 2 * 86_400_000  # as arven.paper.runs.RESAMPLE_BOUNDARY_BUFFER_MS: the 1d bucket straddling old / new data


def _binance_new(app: AppConfig, last: int | None, end_ms: int, downloader: Downloader, summary: RestTailSummary) -> list[Any]:
    if last is None:
        return []  # no history: the bulk backfill's job
    cursor, cal, out = last + MIN_MS, app.session_calendar(), []
    if not cal.always_open:
        opens = cal.open_minutes(cursor, end_ms)
        if not len(opens):
            return []
        cursor = int(opens[0])
    while cursor < end_ms:
        try:
            page = fetch_klines(downloader, app.download.rest_base_url, app.market.symbol, "1m", cursor, end_ms)
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            summary.errors.append(f"klines@{cursor}: {exc}")
            break
        summary.pages += 1
        if not page:
            break
        summary.klines_fetched += len(page)
        out.extend(page)
        cursor = page[-1].open_time_ms + MIN_MS
    if out and not cal.always_open:
        ok = cal.is_open([k.open_time_ms for k in out])
        out = [k for k, o in zip(out, ok) if o]
    return out


def refresh_markets(apps: Sequence[tuple[str, AppConfig]], db: Path, now: datetime, downloader: Downloader | None = None,
                    wait_seconds: float = 15.0) -> dict[str, str]:
    """``apps``: (label, configuration) of every market. Returns ``{label: first error}`` for the markets that failed."""
    if not apps:
        return {}
    now_ms = to_ms(now)
    end_ms = now_ms // MIN_MS * MIN_MS  # the minute still forming is never fetched
    downloader = downloader or Downloader(RetryPolicy.from_config(apps[0][1].download))
    with connect(db, wait_seconds=wait_seconds) as con:
        last = {a.market.symbol: con.execute("SELECT max(open_time_ms) FROM ohlcv_1m WHERE symbol = ?", [a.market.symbol]).fetchone()[0]
                for _, a in apps}

    def fetch(item: tuple[str, AppConfig]) -> tuple[str, AppConfig, list[Any], RestTailSummary]:
        label, a = item
        s = RestTailSummary()
        prev = last[a.market.symbol]
        prev = None if prev is None else int(prev)
        rows = kraken_fetch(a, prev, now_ms, downloader, s) if a.market.exchange == "dukascopy" else _binance_new(a, prev, end_ms, downloader, s)
        return label, a, rows, s

    with ThreadPoolExecutor(max_workers=min(8, len(apps))) as pool:
        fetched = list(pool.map(fetch, apps))
    errors = {label: s.errors[0][:200] for label, _, _, s in fetched if s.errors}
    todo = [(label, a, rows) for label, a, rows, _ in fetched if rows]
    if not todo:
        return errors
    with connect(db, wait_seconds=wait_seconds) as con:
        for label, a, rows in todo:
            sym = a.market.symbol
            try:
                if a.market.exchange == "dukascopy":
                    kraken_write(con, sym, rows)
                else:
                    _write_klines(con, sym, rows, f"rest/{sym}/klines/1m/{rows[0].open_time_ms}")
                anchor = int(last[sym]) if last[sym] is not None else end_ms
                lo = max(to_ms(a.data.history_start), anchor - BUFFER_MS)
                resample(con, sym, from_ms(lo), from_ms(end_ms), DERIVED_TIMEFRAMES, calendar=a.session_calendar())
            except Exception as exc:  # noqa: BLE001 - one market must not stop the others
                errors[label] = f"{type(exc).__name__}: {exc}"[:200]
    return errors


__all__ = ["refresh_markets"]

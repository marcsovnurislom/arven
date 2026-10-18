"""Dukascopy 1m history: download (no database) -> decode BID + ASK -> mid candles -> session filter -> ``ohlcv_1m``.

Two separate steps, so the slow, rate-limited download never holds the DuckDB writer lock (the live loop is the
only writer while it runs):

1. :meth:`DukascopyIngestor.download` fetches ``.bi5`` files into ``data/raw/dukascopy/...``. A file already on
   disk that decodes cleanly is kept without network access; a server 404 for a finished day is remembered with an
   empty ``<file>.404`` marker. Requests are spaced by ``dukascopy.request_interval_seconds`` and retried with
   backoff (the public feed answers 503 / times out under load, notably during weekend maintenance).
2. :meth:`DukascopyIngestor.ingest` turns each UTC day with both sides on disk into mid-price 1m rows, keeps only the
   minutes the session calendar marks open (``AppConfig.market.session``) and replaces that day's rows in one
   transaction together with its ``source_files`` record (dataset ``dukascopy_m1``, one record per day).

Idempotency: the day's ``ingested_sha256`` is a digest of both raw files, the price point and the calendar's closed
windows for that day, so a re-run skips unchanged days and re-ingests exactly the days whose files or session
closures changed.

Columns Dukascopy does not have are stored as neutral values: ``trade_count = 0``, ``taker_buy_volume = 0``,
``taker_buy_quote_volume = 0``, ``quote_volume = volume * close``. ``volume`` is the BID-side tick volume - a
liquidity proxy, not exchange volume (see ``arven.data.adapters.dukascopy``).
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime

import duckdb
import numpy as np

from arven.core.config import AppConfig
from arven.core.time import utc_now
from arven.data.adapters.dukascopy import (
    DukaDayFile,
    DukascopyFormatError,
    M1Candles,
    day_key,
    decode_m1,
    mid_candles,
    plan_days,
    plan_files,
)
from arven.data.download import DownloadError, Downloader, NotAvailableError, RetryPolicy, sha256_file
from arven.data.rest_ingestion import bulk_insert_or_replace
from arven.data.storage.db import SourceFileRecord, get_source_file, new_run_id, now_ms, upsert_source_file

DATASET = "dukascopy_m1"
_OHLCV_COLS = ["symbol", "open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume", "quote_volume",
               "trade_count", "taker_buy_volume", "taker_buy_quote_volume", "source_key", "ingested_at_ms"]
_OHLCV_TYPES = {"symbol": "VARCHAR", "open_time_ms": "BIGINT", "close_time_ms": "BIGINT", "open": "DOUBLE",
                "high": "DOUBLE", "low": "DOUBLE", "close": "DOUBLE", "volume": "DOUBLE", "quote_volume": "DOUBLE",
                "trade_count": "BIGINT", "taker_buy_volume": "DOUBLE", "taker_buy_quote_volume": "DOUBLE",
                "source_key": "VARCHAR", "ingested_at_ms": "BIGINT"}


@dataclass
class DownloadSummary:
    planned: int = 0
    present: int = 0
    downloaded: int = 0
    not_available: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0


@dataclass
class DayIngestSummary:
    run_id: str
    planned_days: int = 0
    ingested: int = 0
    skipped: int = 0
    missing_raw: int = 0
    not_available: int = 0
    failed: int = 0
    rows_written: int = 0
    out_of_session_dropped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0


class DukascopyIngestor:
    def __init__(
        self,
        cfg: AppConfig,
        downloader: Downloader | None = None,
        sleep: Callable[[float], None] = time.sleep,
        today: Callable[[], date] = lambda: utc_now().date(),
    ) -> None:
        if cfg.dukascopy is None or cfg.market.exchange != "dukascopy":
            raise ValueError("DukascopyIngestor needs an instrument whose market.exchange is dukascopy")
        self.cfg = cfg
        self.duka = cfg.dukascopy
        policy = RetryPolicy(
            max_attempts=self.duka.max_attempts,
            timeout_seconds=self.duka.timeout_seconds,
            backoff_initial_seconds=max(1.0, self.duka.request_interval_seconds),
            backoff_multiplier=2.0,
            backoff_max_seconds=self.duka.backoff_max_seconds,
        )
        self.downloader = downloader or Downloader(policy)
        self.sleep = sleep
        self.today = today
        self.raw_dir = cfg.data.raw_dir
        self.symbol = cfg.market.symbol
        self.calendar = cfg.session_calendar()

    # -- step 1: download (no database) -------------------------------------------------------------

    def _valid_on_disk(self, f: DukaDayFile) -> bool:
        path = self.raw_dir / f.key
        if not path.exists():
            return False
        try:
            decode_m1(path.read_bytes(), f.day, self.duka.point)
        except DukascopyFormatError:
            path.unlink(missing_ok=True)  # corrupt (e.g. truncated by an interrupted copy): fetch again
            return False
        return True

    def download(self, start: datetime, end: datetime, progress: Callable[[str], None] | None = None) -> DownloadSummary:
        """Fetch every missing file of ``[start, end)``; ``dukascopy.workers`` requests run in parallel, each worker
        pausing ``request_interval_seconds`` before a request. Failures are counted and left for the next run."""
        files = plan_files(self.duka.instrument, start, end)
        summary = DownloadSummary(planned=len(files))
        today = self.today()
        todo: list[DukaDayFile] = []
        for f in files:
            path = self.raw_dir / f.key
            if path.with_name(path.name + ".404").exists() or f.day >= today:
                summary.not_available += 1  # a remembered 404, or a day not published before it is over
            elif self._valid_on_disk(f):
                summary.present += 1
            else:
                todo.append(f)
        lock = threading.Lock()

        def fetch(f: DukaDayFile) -> None:
            path = self.raw_dir / f.key
            self.sleep(self.duka.request_interval_seconds)
            try:
                self.downloader.download_file(f.url(self.duka.base_url), path, None)
                decode_m1(path.read_bytes(), f.day, self.duka.point)
            except NotAvailableError:
                marker = path.with_name(path.name + ".404")
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_bytes(b"")
                with lock:
                    summary.not_available += 1
                return
            except (DownloadError, DukascopyFormatError, OSError) as exc:
                path.unlink(missing_ok=True)
                with lock:
                    summary.failed += 1
                    summary.errors.append(f"{f.key}: {exc}")
                return
            with lock:
                summary.downloaded += 1
                done = summary.downloaded + summary.failed
                if progress and done % 50 == 0:
                    progress(f"{done}/{len(todo)} fetched ({summary.downloaded} ok, {summary.failed} failed)")

        if self.duka.workers == 1:
            for f in todo:
                fetch(f)
        else:
            with ThreadPoolExecutor(max_workers=self.duka.workers) as pool:
                list(pool.map(fetch, todo))
        summary.errors.sort()
        return summary

    # -- step 2: ingest (database) ---------------------------------------------------------------------

    def _day_files(self, day: date) -> tuple[DukaDayFile, DukaDayFile]:
        return DukaDayFile(self.duka.instrument, day, "BID"), DukaDayFile(self.duka.instrument, day, "ASK")

    def _fingerprint(self, day: date, bid_sha: str, ask_sha: str) -> str:
        bid = self._day_files(day)[0]
        windows = self.calendar.closed_windows(bid.start_ms, bid.end_ms)
        text = f"{bid_sha}:{ask_sha}:{self.duka.point}:{self.calendar.kind}:{windows}"
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def session_rows(self, bid: M1Candles, ask: M1Candles) -> tuple[M1Candles, int]:
        """Mid candles of the open minutes only, and the number of out-of-session minutes dropped."""
        mid = mid_candles(bid, ask)
        keep = self.calendar.is_open(mid.time_ms) if len(mid) else np.zeros(0, dtype=bool)
        kept = M1Candles(*(getattr(mid, n)[keep] for n in ("time_ms", "open", "high", "low", "close", "volume")))
        return kept, int(len(mid) - keep.sum())

    def ingest(self, con: duckdb.DuckDBPyConnection, start: datetime, end: datetime, refresh: bool = False) -> DayIngestSummary:
        days = plan_days(self.duka.instrument, start, end)
        summary = DayIngestSummary(run_id=new_run_id(), planned_days=len(days))
        for day in days:
            self._ingest_day(con, day, summary, refresh)
        return summary

    def _ingest_day(self, con: duckdb.DuckDBPyConnection, day: date, summary: DayIngestSummary, refresh: bool) -> None:
        bid_f, ask_f = self._day_files(day)
        paths = [self.raw_dir / bid_f.key, self.raw_dir / ask_f.key]
        if any(p.with_name(p.name + ".404").exists() for p in paths):
            summary.not_available += 1
            return
        if not all(p.exists() for p in paths):
            summary.missing_raw += 1
            return
        key = day_key(self.duka.instrument, day)
        bid_sha, ask_sha = (sha256_file(p) for p in paths)
        fingerprint = self._fingerprint(day, bid_sha, ask_sha)
        record = get_source_file(con, key)
        if not refresh and record is not None and record.status == "ingested" and record.ingested_sha256 == fingerprint:
            summary.skipped += 1
            return
        record = record or SourceFileRecord(
            source_key=key, url=bid_f.url(self.duka.base_url), dataset=DATASET, granularity="daily",
            symbol=self.symbol, interval="1m", period_start_ms=bid_f.start_ms, period_end_ms=bid_f.end_ms,
            status="planned", updated_at_ms=now_ms(),
        )
        record.actual_sha256 = hashlib.sha256(f"{bid_sha}:{ask_sha}".encode()).hexdigest()
        record.size_bytes = sum(p.stat().st_size for p in paths)
        try:
            bid = decode_m1(paths[0].read_bytes(), day, self.duka.point)
            ask = decode_m1(paths[1].read_bytes(), day, self.duka.point)
            rows, dropped = self.session_rows(bid, ask)
        except DukascopyFormatError as exc:
            summary.failed += 1
            summary.errors.append(f"{key}: {exc}")
            self._save(con, record, summary, status="failed", error=str(exc))
            return
        ingested_at = now_ms()
        data = [
            (self.symbol, int(t), int(t) + 60_000, float(o), float(h), float(lo), float(c), float(v), float(v * c), 0, 0.0, 0.0,
             key, ingested_at)
            for t, o, h, lo, c, v in zip(rows.time_ms, rows.open, rows.high, rows.low, rows.close, rows.volume)
        ]
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("DELETE FROM ohlcv_1m WHERE source_key = ?", [key])
            bulk_insert_or_replace(con, "ohlcv_1m", _OHLCV_COLS, _OHLCV_TYPES, data)
            self._save(con, record, summary, status="ingested", ingested_at_ms=ingested_at, ingested_sha256=fingerprint,
                       row_count=len(data), duplicate_rows_dropped=0, error=None)
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        summary.ingested += 1
        summary.rows_written += len(data)
        summary.out_of_session_dropped += dropped

    @staticmethod
    def _save(con: duckdb.DuckDBPyConnection, record: SourceFileRecord, summary: DayIngestSummary, **changes: object) -> None:
        for name, value in changes.items():
            setattr(record, name, value)
        record.updated_at_ms = now_ms()
        record.last_run_id = summary.run_id
        upsert_source_file(con, record)


def zero_volume_runs(candles: M1Candles, min_minutes: int) -> list[tuple[int, int]]:
    """``[start_ms, end_ms)`` stretches of at least ``min_minutes`` consecutive zero-volume candles (closed-market
    evidence; used to derive and verify the holiday/early-close list)."""
    out: list[tuple[int, int]] = []
    zero = candles.volume == 0
    n, i = len(zero), 0
    while i < n:
        if zero[i]:
            j = i
            while j + 1 < n and zero[j + 1] and candles.time_ms[j + 1] == candles.time_ms[j] + 60_000:
                j += 1
            if j - i + 1 >= min_minutes:
                out.append((int(candles.time_ms[i]), int(candles.time_ms[j]) + 60_000))
            i = j + 1
        else:
            i += 1
    return out

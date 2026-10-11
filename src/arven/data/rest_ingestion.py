"""Stage 8: incremental REST "tail" updates - the live counterpart of ``ingestion.py``'s bulk-file loader.

Writes into the exact same ``ohlcv_1m`` / ``funding_rates`` tables the bulk pipeline uses (there is one
market-data history, not a separate "live" copy); only the source differs. One ``source_key`` per fetched
REST page (``rest/<symbol>/<dataset>/<page_start_ms>``), so a re-run safely replaces exactly the rows that
page covers (``DELETE`` + ``INSERT OR REPLACE``, same idiom ``ingestion.py`` uses per bulk file).

Open interest and the long/short ratios are tailed only on request (``tail(..., include_open_interest=True)``, used by
the live signal loop): Binance serves them for the latest 30 days only, so an older gap stays a gap (NaN features,
the existing staleness policy). Stored under the bulk ``create_time`` convention (see ``binance_rest``) with the same
``available_at_ms = ts_ms + open_interest_availability_delay_seconds`` as the bulk loader.
"""

from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from arven.core.config import AppConfig
from arven.core.timeframes import Timeframe
from arven.data.adapters.binance_rest import (
    OI_COLUMNS,
    REST_STATS_LIMIT,
    STATS_PERIOD_MS,
    RestFunding,
    RestKline,
    RestOpenInterest,
    fetch_funding_rate,
    fetch_klines,
    fetch_open_interest_stats,
)
from arven.data.download import Downloader, RetryPolicy
from arven.data.storage.db import now_ms

FUNDING_GRID_MS = 3_600_000
FUNDING_MAX_DRIFT_MS = 1_000
OI_REST_HISTORY_MS = 29 * 86_400_000  # Binance keeps 30 days of these statistics; stay a day inside that
OI_REFETCH_MS = 1_800_000


def _sql_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def _bulk_insert_or_replace(
    con: duckdb.DuckDBPyConnection, table: str, cols: list[str], types: dict[str, str], rows: list[tuple],
) -> None:
    """``INSERT OR REPLACE`` via a staged bulk load (CSV -> ``read_csv`` -> temp table -> one ``INSERT``),
    never row-by-row parameter binding: a single large ``executemany``/parameterised ``INSERT`` into a table
    with a PRIMARY KEY ART index is pathologically slow in the installed DuckDB version (measured
    ~20-30ms/row). Mirrors ``ingestion.py``'s own staged-load idiom exactly (the same pitfall is documented
    in docs/current_state.md's "Operational notes", first hit by this project's own test infrastructure)."""
    if not rows:
        return
    fd, path = tempfile.mkstemp(suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            w.writerows(rows)
        type_literal = "{" + ", ".join(f"'{name}': '{typ}'" for name, typ in types.items()) + "}"
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE _rest_stage AS SELECT * FROM "
            f"read_csv('{_sql_path(Path(path))}', header=true, delim=',', columns={type_literal}, auto_detect=false)"
        )
        con.execute(f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM _rest_stage")
    finally:
        con.execute("DROP TABLE IF EXISTS _rest_stage")
        Path(path).unlink(missing_ok=True)


class RestIngestError(Exception):
    """A REST response violated the same normalisation contract the bulk loader enforces."""


@dataclass
class RestTailSummary:
    klines_fetched: int = 0
    klines_written: int = 0
    funding_fetched: int = 0
    funding_written: int = 0
    oi_fetched: int = 0
    oi_written: int = 0
    pages: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _last_stored_ms(con: duckdb.DuckDBPyConnection, table: str, time_col: str, symbol: str) -> int | None:
    row = con.execute(f"SELECT max({time_col}) FROM {table} WHERE symbol = ?", [symbol]).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _write_klines(con: duckdb.DuckDBPyConnection, symbol: str, rows: list[RestKline], source_key: str) -> int:
    tf_ms = Timeframe.M1.ms
    for k in rows:
        if k.close_time_ms != k.open_time_ms + tf_ms - 1:
            raise RestIngestError(f"{source_key}: close_time {k.close_time_ms} != open_time + duration - 1ms")
        if k.open_time_ms % tf_ms:
            raise RestIngestError(f"{source_key}: open_time {k.open_time_ms} not aligned to 1m")
    ingested_at = now_ms()
    con.execute("DELETE FROM ohlcv_1m WHERE source_key = ?", [source_key])
    cols = ["symbol", "open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume",
            "quote_volume", "trade_count", "taker_buy_volume", "taker_buy_quote_volume", "source_key", "ingested_at_ms"]
    types = {"symbol": "VARCHAR", "open_time_ms": "BIGINT", "close_time_ms": "BIGINT", "open": "DOUBLE",
             "high": "DOUBLE", "low": "DOUBLE", "close": "DOUBLE", "volume": "DOUBLE", "quote_volume": "DOUBLE",
             "trade_count": "BIGINT", "taker_buy_volume": "DOUBLE", "taker_buy_quote_volume": "DOUBLE",
             "source_key": "VARCHAR", "ingested_at_ms": "BIGINT"}
    data = [
        (symbol, k.open_time_ms, k.open_time_ms + tf_ms, k.open, k.high, k.low, k.close, k.volume,
         k.quote_volume, k.trade_count, k.taker_buy_volume, k.taker_buy_quote_volume, source_key, ingested_at)
        for k in rows
    ]
    _bulk_insert_or_replace(con, "ohlcv_1m", cols, types, data)
    return len(rows)


def _write_funding(
    con: duckdb.DuckDBPyConnection, symbol: str, rows: list[RestFunding], source_key: str, interval_hours: int,
) -> int:
    ingested_at = now_ms()
    normalized = []
    for f in rows:
        funding_time_ms = round(f.funding_time_ms / FUNDING_GRID_MS) * FUNDING_GRID_MS
        drift = abs(f.funding_time_ms - funding_time_ms)
        if drift > FUNDING_MAX_DRIFT_MS:
            raise RestIngestError(f"{source_key}: funding time drift {drift} ms exceeds {FUNDING_MAX_DRIFT_MS} ms")
        available_at_ms = max(f.funding_time_ms, funding_time_ms)
        normalized.append((funding_time_ms, f.funding_time_ms, f.funding_rate, interval_hours, available_at_ms))
    con.execute("DELETE FROM funding_rates WHERE source_key = ?", [source_key])
    cols = ["symbol", "funding_time_ms", "raw_funding_time_ms", "funding_rate", "funding_interval_hours",
            "available_at_ms", "source_key", "ingested_at_ms"]
    types = {"symbol": "VARCHAR", "funding_time_ms": "BIGINT", "raw_funding_time_ms": "BIGINT",
             "funding_rate": "DOUBLE", "funding_interval_hours": "INTEGER", "available_at_ms": "BIGINT",
             "source_key": "VARCHAR", "ingested_at_ms": "BIGINT"}
    data = [(symbol, *row, source_key, ingested_at) for row in normalized]
    _bulk_insert_or_replace(con, "funding_rates", cols, types, data)
    return len(normalized)


def _write_open_interest(
    con: duckdb.DuckDBPyConnection, symbol: str, rows: list[RestOpenInterest], source_key: str, delay_ms: int,
) -> int:
    ingested_at = now_ms()
    con.execute("DELETE FROM open_interest WHERE source_key = ?", [source_key])
    cols = ["symbol", "ts_ms", "available_at_ms", *OI_COLUMNS, "source_key", "ingested_at_ms"]
    types = {"symbol": "VARCHAR", "ts_ms": "BIGINT", "available_at_ms": "BIGINT", **{c: "DOUBLE" for c in OI_COLUMNS},
             "source_key": "VARCHAR", "ingested_at_ms": "BIGINT"}
    data = [(symbol, r.ts_ms, r.ts_ms + delay_ms, *(r.values[c] for c in OI_COLUMNS), source_key, ingested_at) for r in rows]
    _bulk_insert_or_replace(con, "open_interest", cols, types, data)
    return len(rows)


class RestIngestor:
    def __init__(self, cfg: AppConfig, con: duckdb.DuckDBPyConnection, downloader: Downloader | None = None) -> None:
        self.cfg = cfg
        self.con = con
        self.downloader = downloader or Downloader(RetryPolicy.from_config(cfg.download))
        self.symbol = cfg.market.symbol
        self.base_url = cfg.download.rest_base_url

    def tail(self, end_ms: int, *, include_open_interest: bool = False) -> RestTailSummary:
        """Fetch and store every closed 1m bar and funding settlement in ``(last stored, end_ms)`` (and, if asked, the
        5-minute open-interest statistics)."""
        summary = RestTailSummary()
        self._tail_klines(end_ms, summary)
        self._tail_funding(end_ms, summary)
        if include_open_interest:
            self._tail_open_interest(end_ms, summary)
        return summary

    def _tail_open_interest(self, end_ms: int, summary: RestTailSummary) -> None:
        last = _last_stored_ms(self.con, "open_interest", "ts_ms", self.symbol)
        if last is None:
            return  # no history at all: the bulk backfill's job, as for klines
        # re-read the last half hour of REST rows too (an endpoint can publish a 5-minute row a little later than the
        # others); never re-read rows that came from a bulk file (more decimals than the REST ratios)
        row = self.con.execute(
            "SELECT max(ts_ms) FROM open_interest WHERE symbol = ? AND source_key NOT LIKE 'rest/%'", [self.symbol]
        ).fetchone()
        last_bulk = int(row[0]) if row and row[0] is not None else last
        resume = max(min(last, last - OI_REFETCH_MS), last_bulk) + STATS_PERIOD_MS
        cursor = max(resume, (end_ms - OI_REST_HISTORY_MS) // STATS_PERIOD_MS * STATS_PERIOD_MS)
        delay_ms = self.cfg.data.open_interest_availability_delay_seconds * 1000
        while cursor < end_ms:
            page_end = min(end_ms, cursor + REST_STATS_LIMIT * STATS_PERIOD_MS)
            try:
                page = fetch_open_interest_stats(self.downloader, self.base_url, self.symbol, cursor, page_end)
            except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                summary.errors.append(f"openInterest@{cursor}: {exc}")
                return
            summary.pages += 1
            summary.oi_fetched += len(page)
            if page:
                summary.oi_written += _write_open_interest(self.con, self.symbol, page, f"rest/{self.symbol}/openInterest/{cursor}", delay_ms)
            elif page_end >= end_ms:
                return
            cursor = page_end

    def _tail_klines(self, end_ms: int, summary: RestTailSummary) -> None:
        tf_ms = Timeframe.M1.ms
        last = _last_stored_ms(self.con, "ohlcv_1m", "open_time_ms", self.symbol)
        cursor = (last + tf_ms) if last is not None else end_ms  # no history at all: nothing to "tail" from here
        while cursor < end_ms:
            try:
                page = fetch_klines(self.downloader, self.base_url, self.symbol, "1m", cursor, end_ms)
            except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                summary.errors.append(f"klines@{cursor}: {exc}")
                return
            summary.pages += 1
            if not page:
                return
            summary.klines_fetched += len(page)
            source_key = f"rest/{self.symbol}/klines/1m/{cursor}"
            try:
                summary.klines_written += _write_klines(self.con, self.symbol, page, source_key)
            except RestIngestError as exc:
                summary.errors.append(str(exc))
                return
            cursor = page[-1].open_time_ms + tf_ms

    def _tail_funding(self, end_ms: int, summary: RestTailSummary) -> None:
        interval_hours = self.cfg.costs.funding.default_interval_hours
        last = _last_stored_ms(self.con, "funding_rates", "funding_time_ms", self.symbol)
        cursor = (last + 1) if last is not None else end_ms
        while cursor < end_ms:
            try:
                page = fetch_funding_rate(self.downloader, self.base_url, self.symbol, cursor, end_ms)
            except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                summary.errors.append(f"fundingRate@{cursor}: {exc}")
                return
            summary.pages += 1
            if not page:
                return
            summary.funding_fetched += len(page)
            source_key = f"rest/{self.symbol}/fundingRate/{cursor}"
            try:
                summary.funding_written += _write_funding(self.con, self.symbol, page, source_key, interval_hours)
            except RestIngestError as exc:
                summary.errors.append(str(exc))
                return
            cursor = page[-1].funding_time_ms + 1

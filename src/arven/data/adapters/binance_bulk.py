"""Binance public bulk data (https://data.binance.vision), USD-M futures.

Layout: ``data/futures/um/{monthly|daily}/{dataset}/{SYMBOL}/[{interval}/]{file}.zip`` with a sibling
``{file}.zip.CHECKSUM`` containing ``<sha256>  <file>.zip``.

Datasets used by ARVEN:

- ``klines``      monthly and daily; 12 columns; older files have no header row.
- ``fundingRate`` monthly only; ``calc_time, funding_interval_hours, last_funding_rate``.
- ``metrics``     daily only, from 2020-09-01; 5-minute OI / long-short snapshots; ``create_time`` is a
                  ``YYYY-MM-DD HH:MM:SS`` UTC string. Early files contain exact duplicate rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from arven.core.time import UTC, ensure_utc
from arven.core.timeframes import Timeframe


class Dataset(StrEnum):
    KLINES = "klines"
    FUNDING_RATE = "fundingRate"
    METRICS = "metrics"


class Granularity(StrEnum):
    MONTHLY = "monthly"
    DAILY = "daily"


# Name of the first column; used to detect whether a CSV starts with a header row.
HEADER_FIRST_FIELD: dict[Dataset, str] = {
    Dataset.KLINES: "open_time",
    Dataset.FUNDING_RATE: "calc_time",
    Dataset.METRICS: "create_time",
}

KLINE_COLUMNS: tuple[str, ...] = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)
FUNDING_COLUMNS: tuple[str, ...] = ("calc_time", "funding_interval_hours", "last_funding_rate")
METRICS_COLUMNS: tuple[str, ...] = (
    "create_time",
    "symbol",
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)

_MARKET_PREFIX = "data/futures/um"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SourceFile:
    """One downloadable bulk file, covering ``[period_start, period_end)``."""

    dataset: Dataset
    granularity: Granularity
    symbol: str
    period_start: datetime
    interval: Timeframe | None = None

    def __post_init__(self) -> None:
        if (self.dataset is Dataset.KLINES) != (self.interval is not None):
            raise ValueError("interval is required for klines and not allowed for other datasets")
        start = ensure_utc(self.period_start)
        if (start.hour, start.minute, start.second, start.microsecond) != (0, 0, 0, 0):
            raise ValueError("period_start must be midnight UTC")
        if self.granularity is Granularity.MONTHLY and start.day != 1:
            raise ValueError("monthly period_start must be the first day of a month")

    @property
    def period_end(self) -> datetime:
        if self.granularity is Granularity.DAILY:
            return self.period_start + timedelta(days=1)
        return _add_month(self.period_start)

    @property
    def period_tag(self) -> str:
        fmt = "%Y-%m" if self.granularity is Granularity.MONTHLY else "%Y-%m-%d"
        return self.period_start.strftime(fmt)

    @property
    def filename(self) -> str:
        middle = self.interval.value if self.dataset is Dataset.KLINES else self.dataset.value
        return f"{self.symbol}-{middle}-{self.period_tag}.zip"

    @property
    def key(self) -> str:
        """Path relative to the bucket root; also the local path under ``raw_dir`` and the provenance key."""
        parts = [_MARKET_PREFIX, self.granularity.value, self.dataset.value, self.symbol]
        if self.interval is not None:
            parts.append(self.interval.value)
        return "/".join([*parts, self.filename])

    @property
    def checksum_key(self) -> str:
        return self.key + ".CHECKSUM"

    def url(self, base_url: str) -> str:
        return f"{base_url.rstrip('/')}/{self.key}"

    def checksum_url(self, base_url: str) -> str:
        return f"{base_url.rstrip('/')}/{self.checksum_key}"


def _month_start(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, 1, tzinfo=UTC)


def _add_month(dt: datetime) -> datetime:
    return datetime(dt.year + dt.month // 12, dt.month % 12 + 1, 1, tzinfo=UTC)


def _require_midnight(dt: datetime, name: str) -> datetime:
    dt = ensure_utc(dt)
    if (dt.hour, dt.minute, dt.second, dt.microsecond) != (0, 0, 0, 0):
        raise ValueError(f"{name} must be midnight UTC, got {dt.isoformat()}")
    return dt


def plan_files(
    dataset: Dataset,
    symbol: str,
    start: datetime,
    end: datetime,
    interval: Timeframe | None = None,
) -> list[SourceFile]:
    """Files needed to cover ``[start, end)`` (day-aligned).

    - ``metrics``: one daily file per day.
    - ``fundingRate``: every monthly file overlapping the range (no daily files exist).
    - ``klines``: monthly files for whole months, daily files for partial months at the edges.
    """
    start = _require_midnight(start, "start")
    end = _require_midnight(end, "end")
    if start >= end:
        return []

    def daily(lo: datetime, hi: datetime) -> list[SourceFile]:
        days = (hi - lo).days
        return [
            SourceFile(dataset, Granularity.DAILY, symbol, lo + timedelta(days=i), interval) for i in range(days)
        ]

    if dataset is Dataset.METRICS:
        return daily(start, end)

    files: list[SourceFile] = []
    month = _month_start(start)
    while month < end:
        next_month = _add_month(month)
        if dataset is Dataset.FUNDING_RATE or (start <= month and next_month <= end):
            files.append(SourceFile(dataset, Granularity.MONTHLY, symbol, month, interval))
        else:
            files.extend(daily(max(month, start), min(next_month, end)))
        month = next_month
    return files


def parse_checksum(text: str, expected_filename: str) -> str:
    """Extract the SHA-256 hex digest from a ``.CHECKSUM`` file and verify it names the right file."""
    parts = text.strip().split()
    if len(parts) != 2:
        raise ValueError(f"unexpected CHECKSUM format: {text!r}")
    digest, name = parts[0].lower(), parts[1].lstrip("*")
    if not _SHA256_RE.match(digest):
        raise ValueError(f"invalid SHA-256 digest in CHECKSUM: {digest!r}")
    if name != expected_filename:
        raise ValueError(f"CHECKSUM refers to {name!r}, expected {expected_filename!r}")
    return digest


def has_header(first_line: str, dataset: Dataset) -> bool:
    """True if the CSV's first line is a header row (newer files) rather than data (older files)."""
    return first_line.split(",", 1)[0].strip().lstrip("﻿") == HEADER_FIRST_FIELD[dataset]

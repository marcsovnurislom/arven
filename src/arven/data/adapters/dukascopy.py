"""Dukascopy public datafeed: 1-minute candles, one LZMA-compressed ``.bi5`` file per UTC day and price side.

URL: ``<base_url>/<INSTRUMENT>/<YYYY>/<MM-1>/<DD>/<BID|ASK>_candles_min_1.bi5`` - the month is **zero-based**
(``.../2024/02/05/...`` is 2024-03-05). A file decompresses to 24-byte big-endian records
``(uint32 seconds since 00:00 UTC, uint32 open, uint32 close, uint32 low, uint32 high, float32 volume)``; prices are
integers in units of ``1 / point`` (XAUUSD: point 1000, so 2114455 -> 2114.455). Note the field order
open, **close**, low, high. Verified on 2024-03-05: 1440 records, first minute O 2114.455 C 2114.865 L 2114.165
H 2114.975, matching the market. A closed market (weekend, holiday) still yields records: flat candles with zero
volume. A day that has not finished yet is not published (HTTP 404).

There is no published checksum, so integrity is checked structurally on decode (LZMA stream valid, whole records,
times inside the day on whole minutes and strictly increasing, positive prices, ``low <= open, close <= high``).
"""

from __future__ import annotations

import lzma
import struct
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

import numpy as np

from arven.core.time import UTC, ensure_utc, to_ms

Side = Literal["BID", "ASK"]
SIDES: tuple[Side, ...] = ("BID", "ASK")
RECORD = struct.Struct(">5If")
_DTYPE = np.dtype([("t", ">u4"), ("o", ">u4"), ("c", ">u4"), ("l", ">u4"), ("h", ">u4"), ("v", ">f4")])
assert _DTYPE.itemsize == RECORD.size
DAY_MS = 86_400_000


class DukascopyFormatError(Exception):
    """A ``.bi5`` file violated the format contract."""


@dataclass(frozen=True)
class DukaDayFile:
    """One day of 1m candles for one price side."""

    instrument: str
    day: date
    side: Side

    @property
    def key(self) -> str:
        """Path under ``data/raw`` (and the ``source_files`` key prefix)."""
        return f"dukascopy/{self.instrument}/m1/{self.side}/{self.day.year}/{self.day.isoformat()}.bi5"

    def url(self, base_url: str) -> str:
        d = self.day
        return f"{base_url.rstrip('/')}/{self.instrument}/{d.year}/{d.month - 1:02d}/{d.day:02d}/{self.side}_candles_min_1.bi5"

    @property
    def start_ms(self) -> int:
        return to_ms(datetime(self.day.year, self.day.month, self.day.day, tzinfo=UTC))

    @property
    def end_ms(self) -> int:
        return self.start_ms + DAY_MS


def day_key(instrument: str, day: date) -> str:
    """``source_files`` key of one ingested day (both sides combined)."""
    return f"dukascopy/{instrument}/m1/{day.year}/{day.isoformat()}"


def plan_days(instrument: str, start: datetime, end: datetime) -> list[date]:
    """UTC days overlapping ``[start, end)``."""
    s, e = ensure_utc(start), ensure_utc(end)
    if s >= e:
        return []
    first = s.date()
    last = (e - timedelta(microseconds=1)).date()
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def plan_files(instrument: str, start: datetime, end: datetime) -> list[DukaDayFile]:
    return [DukaDayFile(instrument, d, side) for d in plan_days(instrument, start, end) for side in SIDES]


@dataclass(frozen=True)
class M1Candles:
    """Decoded candles of one day and side, oldest first."""

    time_ms: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    def __len__(self) -> int:
        return len(self.time_ms)


def decode_m1(raw: bytes, day: date, point: int) -> M1Candles:
    """Decode one day's ``.bi5`` content (``b""`` = a published but empty file -> no candles)."""
    if raw:
        try:
            body = lzma.decompress(raw)
        except lzma.LZMAError as exc:
            raise DukascopyFormatError(f"{day}: not a valid LZMA stream ({exc})") from exc
    else:
        body = b""
    if len(body) % RECORD.size:
        raise DukascopyFormatError(f"{day}: {len(body)} bytes is not a whole number of {RECORD.size}-byte records")
    n = len(body) // RECORD.size
    if n == 0:
        z = np.zeros(0)
        return M1Candles(np.zeros(0, dtype=np.int64), z, z, z, z, z)
    rec = np.frombuffer(body, dtype=_DTYPE)
    sec = rec["t"].astype(np.int64)
    if np.any(sec % 60) or np.any(sec >= 86_400):
        raise DukascopyFormatError(f"{day}: candle times not on whole minutes inside the day")
    if np.any(np.diff(sec) <= 0):
        raise DukascopyFormatError(f"{day}: candle times not strictly increasing")
    o, c, lo, hi = (rec[f].astype(np.float64) / point for f in ("o", "c", "l", "h"))
    if np.any(np.minimum.reduce([o, c, lo, hi]) <= 0):
        raise DukascopyFormatError(f"{day}: non-positive price")
    if np.any(lo > np.minimum(o, c)) or np.any(hi < np.maximum(o, c)):
        raise DukascopyFormatError(f"{day}: inconsistent OHLC (low above open/close or high below them)")
    vol = rec["v"].astype(np.float64)
    if np.any(~np.isfinite(vol)) or np.any(vol < 0):
        raise DukascopyFormatError(f"{day}: negative or non-finite volume")
    base = DukaDayFile("X", day, "BID").start_ms
    return M1Candles(base + sec * 1000, o, hi, lo, c, vol)


def mid_candles(bid: M1Candles, ask: M1Candles) -> M1Candles:
    """Mid-price candles ``(bid + ask) / 2`` field by field; the volume is the BID-side tick volume.

    The mid high/low is the average of the two sides' extremes (Dukascopy publishes no mid series); it still
    satisfies ``low <= open, close <= high`` because each side does. Both sides must cover the same minutes."""
    if len(bid) != len(ask) or not np.array_equal(bid.time_ms, ask.time_ms):
        raise DukascopyFormatError(f"BID and ASK cover different minutes ({len(bid)} vs {len(ask)} candles)")
    if np.any(ask.close < bid.close - 1e-9) or np.any(ask.open < bid.open - 1e-9):
        raise DukascopyFormatError("ASK below BID")
    return M1Candles(
        bid.time_ms,
        (bid.open + ask.open) / 2,
        (bid.high + ask.high) / 2,
        (bid.low + ask.low) / 2,
        (bid.close + ask.close) / 2,
        bid.volume,
    )

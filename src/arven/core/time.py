"""Strict UTC time helpers.

ARVEN never works with naive or local-time datetimes. Every datetime is timezone-aware UTC;
integer timestamps are UTC epoch milliseconds (the exchange convention).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MS = timedelta(milliseconds=1)


def ensure_utc(dt: datetime) -> datetime:
    """Return ``dt`` converted to UTC. Naive datetimes are rejected."""
    if not isinstance(dt, datetime):
        raise TypeError(f"expected datetime, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"naive datetime {dt!r} is not allowed; use timezone-aware UTC")
    return dt.astimezone(UTC)


def to_ms(dt: datetime) -> int:
    """UTC datetime -> epoch milliseconds (exact integer arithmetic, sub-ms truncated toward -inf)."""
    return (ensure_utc(dt) - EPOCH) // _ONE_MS


def from_ms(ms: int) -> datetime:
    """Epoch milliseconds -> UTC datetime."""
    if isinstance(ms, bool) or not isinstance(ms, int):
        raise TypeError(f"expected int milliseconds, got {type(ms).__name__}")
    return EPOCH + timedelta(milliseconds=ms)


def to_utc_datetime(value: datetime | date | str) -> datetime:
    """Coerce config-style values to a UTC datetime.

    - ``datetime``: must be timezone-aware.
    - ``date`` or ``"YYYY-MM-DD"``: interpreted as 00:00 UTC of that day.
    - ISO datetime string: must carry an offset (``Z`` or ``+00:00``).
    """
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 10:
            return to_utc_datetime(date.fromisoformat(text))
        return ensure_utc(datetime.fromisoformat(text))
    raise TypeError(f"cannot convert {type(value).__name__} to UTC datetime")


def utc_now() -> datetime:
    return datetime.now(UTC)

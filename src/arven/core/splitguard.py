"""Development / validation / sealed-test boundaries.

Every backtest reads data through an :class:`AllowedWindow`. A window can only be created by
:meth:`SplitGuard.resolve`, which

- confines it to exactly one configured period (a range that crosses a period boundary is refused),
- refuses the sealed test period unless the caller explicitly acknowledges it with a reason, and
- appends every allowed sealed access to an append-only log *before* any data is loaded (so an aborted
  attempt is logged too).

Data loaders take an ``AllowedWindow`` (not raw dates) and assert that what they loaded lies inside it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from arven.core.config import Period, SplitsConfig
from arven.core.time import to_ms, utc_now

HOUR_MS = 3_600_000
_TOKEN = object()


class BacktestPeriod(StrEnum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    TEST = "test"
    FORWARD = "forward"  # Stage 8: real paper trading from splits.forward_start onward; never sealed,
    #                      has no fixed end (it grows with real time), so SplitGuard.resolve requires an
    #                      explicit end_ms for it rather than defaulting to a configured period end.


class SplitViolation(Exception):
    """A requested range crosses a period boundary or leaves the configured periods."""


class SealedAccessError(SplitViolation):
    """The sealed test period was requested without the explicit acknowledgement."""


@dataclass(frozen=True)
class AllowedWindow:
    """Half-open UTC range ``[start_ms, end_ms)`` inside exactly one period."""

    period: BacktestPeriod
    start_ms: int
    end_ms: int
    sealed: bool
    sealed_reason: str | None = None
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _TOKEN:
            raise SplitViolation("AllowedWindow can only be created by SplitGuard.resolve")

    def contains_ms(self, t_ms: int) -> bool:
        return self.start_ms <= t_ms < self.end_ms

    def assert_inside(self, first_ms: int | None, last_ms: int | None, what: str) -> None:
        """Assert that loaded timestamps ``first_ms`` .. ``last_ms`` lie inside the window."""
        for t in (first_ms, last_ms):
            if t is not None and not self.contains_ms(int(t)):
                raise SplitViolation(f"{what}: timestamp {t} outside the allowed window [{self.start_ms}, {self.end_ms})")

    @property
    def n_hours(self) -> int:
        return (self.end_ms - self.start_ms) // HOUR_MS


def append_sealed_log(path: Path, entry: dict[str, Any]) -> None:
    """Append one JSON line and force it to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


class SplitGuard:
    def __init__(self, splits: SplitsConfig, sealed_log_path: Path | None = None) -> None:
        self._periods: dict[BacktestPeriod, Period] = {
            BacktestPeriod.DEVELOPMENT: splits.development,
            BacktestPeriod.VALIDATION: splits.validation,
            BacktestPeriod.TEST: splits.test,
        }
        self._forward_start_ms = to_ms(splits.forward_start)
        self._log_path = sealed_log_path

    def period_bounds(self, period: BacktestPeriod) -> tuple[int, int]:
        """Bounds of a *fixed* period (development/validation/test). ``FORWARD`` has no fixed upper bound
        and is not resolvable through this method - see :meth:`resolve`."""
        p = self._periods[period]
        return to_ms(p.start), to_ms(p.end)

    def resolve(
        self,
        period: BacktestPeriod,
        start_ms: int | None = None,
        end_ms: int | None = None,
        *,
        allow_sealed: bool = False,
        reason: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> AllowedWindow:
        if period == BacktestPeriod.FORWARD:
            return self._resolve_forward(start_ms, end_ms)
        p_start, p_end = self.period_bounds(period)
        start = p_start if start_ms is None else int(start_ms)
        end = p_end if end_ms is None else int(end_ms)
        if start >= end:
            raise SplitViolation("window start must be before end")
        if start < p_start or end > p_end:
            raise SplitViolation(
                f"range [{start}, {end}) leaves the {period.value} period [{p_start}, {p_end}); "
                "ranges may not cross period boundaries"
            )
        if start % HOUR_MS or end % HOUR_MS:
            raise SplitViolation("window bounds must be whole hours (1h decision grid)")

        sealed = period == BacktestPeriod.TEST
        if sealed:
            if not allow_sealed or not (reason and reason.strip()):
                raise SealedAccessError(
                    "the test period is sealed: pass allow_sealed=True and a non-empty reason "
                    "(the access is logged permanently)"
                )
            if self._log_path is None:
                raise SealedAccessError("no sealed-access log configured; refusing to open the test period unlogged")
            append_sealed_log(
                self._log_path,
                {
                    "accessed_at": utc_now().isoformat(),
                    "period": period.value,
                    "window_start_ms": start,
                    "window_end_ms": end,
                    "reason": reason.strip(),
                    **(context or {}),
                },
            )
        return AllowedWindow(period, start, end, sealed, reason.strip() if sealed and reason else None, _token=_TOKEN)

    def _resolve_forward(self, start_ms: int | None, end_ms: int | None) -> AllowedWindow:
        """The forward (paper-trading) period: ``[forward_start, end_ms)`` where ``end_ms`` is the caller's
        own single read of "now" (floored to a whole hour) - there is nothing else to default it to, and
        ``SplitGuard`` itself never reads the wall clock. Never sealed: there is no future beyond "now" to
        leak, so nothing here needs acknowledgement or logging."""
        if end_ms is None:
            raise SplitViolation("the forward period has no fixed end; end_ms must be given explicitly")
        p_start = self._forward_start_ms
        start = p_start if start_ms is None else int(start_ms)
        end = int(end_ms)
        if start >= end:
            raise SplitViolation("window start must be before end")
        if start < p_start:
            raise SplitViolation(f"range [{start}, {end}) starts before the forward period [{p_start}, +inf)")
        if start % HOUR_MS or end % HOUR_MS:
            raise SplitViolation("window bounds must be whole hours (1h decision grid)")
        return AllowedWindow(BacktestPeriod.FORWARD, start, end, sealed=False, sealed_reason=None, _token=_TOKEN)

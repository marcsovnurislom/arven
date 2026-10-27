"""BarSeries.regularized_until(t) == available_until(t).regularized(), exactly - around the clock and on a session
market, with missing and incomplete bars, at every kind of t (2026-10-27 speed-up of S4-S6)."""

from __future__ import annotations

import numpy as np
import pytest

from arven.core.series import BarSeries
from arven.core.sessions import SessionCalendar
from arven.core.timeframes import Timeframe

T0 = 1_767_225_600_000  # 2026-01-01 00:00 UTC (a Thursday)


def _series(cal: SessionCalendar | None, seed: int) -> BarSeries:
    tf = Timeframe.H1
    rng = np.random.default_rng(seed)
    grid = np.arange(T0, T0 + 24 * 40 * tf.ms, tf.ms, dtype=np.int64)
    if cal is not None:
        grid = grid[np.asarray(cal.is_open(grid), dtype=bool)]
    opens = grid[rng.random(len(grid)) > 0.08]  # some bars missing
    n = len(opens)
    c = 100 + np.cumsum(rng.normal(0, 1, n))
    return BarSeries(tf, 0, opens, c, c + 1, c - 1, c, rng.uniform(1, 2, n), rng.uniform(1, 9, n), rng.uniform(0, 1, n),
                     rng.random(n) > 0.05, cal)


def _same(a: BarSeries, b: BarSeries) -> None:
    assert len(a) == len(b)
    np.testing.assert_array_equal(a.open_time_ms, b.open_time_ms)
    np.testing.assert_array_equal(a.complete, b.complete)
    for name in ("open", "high", "low", "close", "volume", "trade_count", "taker_buy_volume"):
        np.testing.assert_array_equal(getattr(a, name), getattr(b, name))  # NaN == NaN here
    assert (a.timeframe, a.delay_ms, a.calendar) == (b.timeframe, b.delay_ms, b.calendar)


@pytest.mark.parametrize("cal", [None, SessionCalendar("cme_metals"), SessionCalendar("fx")])
def test_regularized_until_equals_truncate_then_regularize(cal):
    s = _series(cal, 5)
    ts = [T0 - 1, T0, s.available_at_ms[0], s.available_at_ms[0] - 1, int(s.available_at_ms[-1]) + 10 ** 9]
    ts += [int(x) for x in s.available_at_ms[::7]] + [int(x) + 1234 for x in s.available_at_ms[3::11]]
    for t in ts:
        _same(s.regularized_until(t), s.available_until(t).regularized())

import numpy as np
import pytest

from arven.core.series import BarSeries, FundingSeries, OpenInterestSeries
from arven.core.timeframes import Timeframe
from arven.features.asof import asof_index, asof_join

H = 3_600_000


def bars(open_times, tf=Timeframe.H1, delay_ms=0, complete=None):
    n = len(open_times)
    vals = np.arange(1.0, n + 1)
    return BarSeries(
        tf, delay_ms, np.array(open_times, dtype=np.int64), vals, vals + 1, vals - 0.5, vals, vals * 10, vals * 3, vals * 2,
        np.ones(n, dtype=bool) if complete is None else np.array(complete),
    )


def test_bar_series_validates_order_alignment_and_lengths():
    with pytest.raises(ValueError, match="strictly increasing"):
        bars([H, H])
    with pytest.raises(ValueError, match="aligned"):
        bars([H + 1])
    with pytest.raises(ValueError, match="delay"):
        bars([H], delay_ms=-1)


def test_bar_available_at_is_close_plus_delay():
    s = bars([0, H], delay_ms=60_000)
    np.testing.assert_array_equal(s.available_at_ms, [H + 60_000, 2 * H + 60_000])


def test_available_until_includes_bar_closing_exactly_at_t_only_without_delay():
    s = bars([0, H, 2 * H])
    assert len(s.available_until(2 * H)) == 2  # bar 1 closes at 2H: usable at 2H
    assert len(s.available_until(2 * H - 1)) == 1
    delayed = bars([0, H, 2 * H], delay_ms=1)
    assert len(delayed.available_until(2 * H)) == 1  # closes at 2H but usable from 2H + 1ms


def test_regularized_inserts_nan_rows_for_gaps_and_incomplete_bars():
    s = bars([0, 2 * H, 3 * H, 4 * H], complete=[True, True, False, True])
    r = s.regularized()
    np.testing.assert_array_equal(r.open_time_ms, [0, H, 2 * H, 3 * H, 4 * H])
    assert list(r.complete) == [True, False, True, False, True]
    assert np.isnan(r.close[[1, 3]]).all() and not np.isnan(r.close[[0, 2, 4]]).any()
    assert r.close[2] == s.close[1]  # real values are not moved or filled


def test_regularized_of_empty_series_is_empty():
    assert len(bars([]).regularized()) == 0


def test_funding_and_oi_validation_and_truncation():
    with pytest.raises(ValueError):
        FundingSeries(np.array([2, 1]), np.array([2, 1]), np.array([0.0, 0.0]), np.array([8, 8]))
    f = FundingSeries(np.array([0, 8 * H]), np.array([0, 8 * H + 30]), np.array([1e-4, 2e-4]), np.array([8, 8]))
    assert len(f.available_until(8 * H)) == 1  # the second is published 30 ms after its nominal time
    assert len(f.available_until(8 * H + 30)) == 2
    oi = OpenInterestSeries(np.array([0, 300_000]), np.array([300_000, 600_000]), np.ones(2), np.ones(2), np.ones(2))
    assert len(oi.available_until(599_999)) == 1


def test_asof_index_is_backward_and_inclusive():
    avail = np.array([10, 20, 30])
    np.testing.assert_array_equal(asof_index(avail, np.array([5, 10, 19, 20, 99])), [-1, 0, 0, 1, 2])


def test_asof_join_never_uses_a_record_before_it_is_available():
    avail = np.array([10, 20, 30])
    vals = np.array([1.0, 2.0, 3.0])
    out = asof_join(avail, vals, np.array([9, 10, 29, 30]))
    np.testing.assert_array_equal(out, [np.nan, 1.0, 2.0, 3.0])


def test_asof_join_staleness_gives_nan_not_carry_forward():
    avail = np.array([0, 100])
    vals = np.array([1.0, 2.0])
    out = asof_join(avail, vals, np.array([50, 150, 250]), max_age_ms=100)
    np.testing.assert_array_equal(out, [1.0, 2.0, np.nan])


def test_asof_join_can_measure_age_from_event_time():
    avail, event = np.array([300, 600]), np.array([0, 300])
    out = asof_join(avail, np.array([1.0, 2.0]), np.array([700, 1000]), max_age_ms=500, event_time_ms=event)
    np.testing.assert_array_equal(out, [2.0, np.nan])  # age is t - event_time, not t - available_at


def test_asof_join_rejects_unsorted_availability_and_handles_empty():
    with pytest.raises(ValueError, match="sorted"):
        asof_index(np.array([5, 1]), np.array([3]))
    np.testing.assert_array_equal(asof_join(np.array([], dtype=np.int64), np.array([]), np.array([1, 2])), [np.nan, np.nan])

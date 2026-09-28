"""Funding, open-interest and time features: availability, staleness, gaps, contiguity."""

import math

import numpy as np
import pytest
from synthetic_market import DAY, HOUR, START_MS, make_funding, make_oi

from arven.core.features_config import load_features_config
from arven.core.series import FundingSeries, OpenInterestSeries
from arven.features.futures import compute_funding, compute_oi, compute_time

CFG = load_features_config()


def ts(*hours):
    return np.array([START_MS + h * HOUR for h in hours], dtype=np.int64)


# --- funding ------------------------------------------------------------------------------------


def test_funding_uses_the_latest_settled_record_and_hours_to_next():
    f = make_funding(200)
    out = compute_funding(f, ts(8, 9, 15), CFG)
    assert out["fund_rate"][0] == f.funding_rate[1]  # funding at +8h is usable at +8h
    assert out["fund_rate"][1] == f.funding_rate[1]
    assert out["fund_hours_to_next"][0] == 8.0 and out["fund_hours_to_next"][1] == 7.0 and out["fund_hours_to_next"][2] == 1.0
    assert out["funding_available"].tolist() == [1.0, 1.0, 1.0]


def test_funding_published_after_its_nominal_time_is_not_used_early():
    f = make_funding(200, jitter_ms=25)  # available_at = funding_time + 25 ms
    out = compute_funding(f, ts(8), CFG)
    assert out["fund_rate"][0] == f.funding_rate[0]  # the +8h funding is not yet published at exactly +8h


def test_funding_stale_record_is_nan():
    f = make_funding(2)  # 6 fundings, the last at +40h
    out = compute_funding(f, ts(40 + 12, 40 + 13), CFG)  # 1.5 intervals = 12h after the last is still allowed
    assert np.isfinite(out["fund_rate"][0]) and np.isnan(out["fund_rate"][1])
    assert out["funding_available"].tolist() == [1.0, 0.0]


def test_funding_z_and_sum_match_naive_and_need_contiguous_history():
    f = make_funding(60)
    w, m = CFG.funding.z_window, CFG.funding.sum_periods
    k = 100  # record index
    t = ts(8 * k)
    out = compute_funding(f, t, CFG)
    window = f.funding_rate[k - w + 1 : k + 1]
    assert out["fund_z"][0] == pytest.approx((f.funding_rate[k] - window.mean()) / window.std())
    assert out[f"fund_sum_last_{m}"][0] == pytest.approx(f.funding_rate[k - m + 1 : k + 1].sum())
    assert np.isnan(compute_funding(f, ts(8 * (w - 2)), CFG)["fund_z"][0])  # not enough history

    # Drop one funding inside the window: the z-score must be NaN until 90 contiguous fundings exist again.
    keep = np.ones(len(f), dtype=bool)
    keep[50] = False
    g = FundingSeries(f.funding_time_ms[keep], f.available_at_ms[keep], f.funding_rate[keep], f.interval_hours[keep])
    out = compute_funding(g, ts(8 * 60, 8 * 139, 8 * 140), CFG)
    assert np.isnan(out["fund_z"][0]) and np.isnan(out["fund_z"][1]) and np.isfinite(out["fund_z"][2])
    assert np.isfinite(out["fund_rate"][0])  # the level itself is unaffected


def test_funding_empty_series_is_all_nan():
    empty = FundingSeries(*(np.array([], dtype=np.int64),) * 2, np.array([]), np.array([], dtype=np.int64))
    out = compute_funding(empty, ts(1, 2), CFG)
    assert all(np.isnan(v).all() for k, v in out.items() if k != "funding_available")
    assert out["funding_available"].tolist() == [0.0, 0.0]


# --- open interest ------------------------------------------------------------------------------


def test_oi_uses_publication_delay():
    oi = make_oi(30)  # snapshot stamped T is usable from T + 5 min
    out = compute_oi(oi, ts(48), CFG)
    # At +48h exactly, the latest usable snapshot is the one stamped +47h55m.
    ts_latest = START_MS + 48 * HOUR - 300_000
    assert out["oi_age_s"][0] == 300.0
    idx = int((ts_latest - START_MS) // 300_000)
    assert out["oi_top_ls_log"][0] == pytest.approx(math.log(oi.top_trader_ls_ratio[idx]))


def test_oi_change_matches_hourly_asof_values():
    oi = make_oi(30)
    out = compute_oi(oi, ts(24 * 5, 24 * 5 + 1), CFG)

    def level(hour):  # latest snapshot usable at START + hour: stamped hour - 5 min
        return oi.sum_open_interest[int((hour * HOUR - 300_000) // 300_000)]

    assert out["oi_chg_1h"][1] == pytest.approx(math.log(level(24 * 5 + 1) / level(24 * 5)))
    assert out["oi_chg_24h"][1] == pytest.approx(math.log(level(24 * 5 + 1) / level(24 * 4 + 1)))
    assert out["oi_available"].tolist() == [1.0, 1.0]


def test_oi_gap_gives_nan_and_never_interpolates_or_shifts_windows():
    oi = make_oi(30)
    gap_start, gap_end = 100 * HOUR - 30 * 60_000, 100 * HOUR + 40 * 60_000  # no snapshots near +100h
    keep = ~((oi.ts_ms - START_MS >= gap_start) & (oi.ts_ms - START_MS < gap_end))
    g = OpenInterestSeries(oi.ts_ms[keep], oi.available_at_ms[keep], oi.sum_open_interest[keep], oi.top_trader_ls_ratio[keep], oi.taker_ls_vol_ratio[keep])
    out = compute_oi(g, ts(99, 100, 101, 102), CFG)
    # At +100h the latest usable snapshot is stamped +99h25m (35 min old > 15 min limit): NaN, not carried forward.
    # At +101h a fresh snapshot exists again, but its 1h-earlier reference (+100h) is missing.
    assert out["oi_available"].tolist() == [1.0, 0.0, 1.0, 1.0]
    assert np.isnan(out["oi_chg_1h"][1]) and np.isnan(out["oi_chg_1h"][2])
    assert np.isfinite(out["oi_chg_1h"][3])
    assert np.isfinite(out["oi_chg_24h"][0]) and np.isnan(out["oi_chg_24h"][1])
    assert np.isnan(out["oi_age_s"][1])


def test_oi_stale_snapshot_is_nan_and_history_before_first_record_is_nan():
    oi = make_oi(2)  # 2 days of snapshots
    late = compute_oi(oi, ts(48 + 3), CFG)
    assert np.isnan(late["oi_top_ls_log"][0]) and late["oi_available"][0] == 0.0
    early = compute_oi(oi, ts(0), CFG)
    assert np.isnan(early["oi_top_ls_log"][0]) and early["oi_available"][0] == 0.0  # first snapshot usable at +5 min


def test_oi_z_needs_window_and_tolerates_isolated_gaps():
    oi = make_oi(60)
    w = CFG.open_interest.z_window_hours
    out = compute_oi(oi, ts(w - 5, w + 20, w + 21), CFG)
    assert np.isnan(out["oi_z"][0]) and np.isfinite(out["oi_z"][1])
    # An isolated missing hourly value does not blank the next 30 days (>= 90% of the window is enough).
    hole = ((oi.ts_ms - START_MS) >= (w + 5) * HOUR - 3 * 300_000) & ((oi.ts_ms - START_MS) < (w + 5) * HOUR + 3 * 300_000)
    g = OpenInterestSeries(*(a[~hole] for a in (oi.ts_ms, oi.available_at_ms, oi.sum_open_interest, oi.top_trader_ls_ratio, oi.taker_ls_vol_ratio)))
    assert np.isfinite(compute_oi(g, ts(w + 20), CFG)["oi_z"][0])


def test_oi_rejects_off_grid_decision_times():
    with pytest.raises(ValueError, match="whole hours"):
        compute_oi(make_oi(3), np.array([START_MS + 1], dtype=np.int64), CFG)


def test_oi_empty_series_is_all_nan_with_flag_zero():
    empty = OpenInterestSeries(*(np.array([], dtype=np.int64),) * 2, *(np.array([]),) * 3)
    out = compute_oi(empty, ts(1), CFG)
    assert out["oi_available"].tolist() == [0.0] and np.isnan(out["oi_z"]).all()


# --- time ---------------------------------------------------------------------------------------


def test_time_features_hand_values():
    out = compute_time(np.array([START_MS + 12 * HOUR, START_MS + 3 * DAY + 6 * HOUR], dtype=np.int64))  # Mon 12:00, Thu 06:00
    assert out["time_hour_sin"][0] == pytest.approx(0.0, abs=1e-12) and out["time_hour_cos"][0] == pytest.approx(-1.0)
    assert out["time_hour_sin"][1] == pytest.approx(1.0) and out["time_hour_cos"][1] == pytest.approx(0.0, abs=1e-12)
    assert out["time_dow_sin"][0] == 0.0 and out["time_dow_cos"][0] == 1.0  # Monday = 0
    assert out["time_dow_sin"][1] == pytest.approx(math.sin(2 * math.pi * 3 / 7))

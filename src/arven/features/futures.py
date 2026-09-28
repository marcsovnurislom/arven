"""Futures-market features: funding rate and open interest.

Both are event streams with their own ``available_at``. At decision time ``t`` only records with
``available_at <= t`` are used, a record that is too old is NaN (never carried forward), and gaps are never
interpolated. Windows over funding count *settled fundings* and require them to be contiguous; windows
over open interest use hourly as-of values, so a source gap makes the affected values NaN instead of
shifting the window.
"""

from __future__ import annotations

import math

import numpy as np

from arven.core.features_config import FeaturesConfig
from arven.core.series import FundingSeries, OpenInterestSeries
from arven.features import indicators as ind
from arven.features.asof import asof_index, asof_join
from arven.features.spec import FeatureSpec

HOUR_MS = 3_600_000


def funding_specs(cfg: FeaturesConfig) -> list[FeatureSpec]:
    f = cfg.funding
    return [
        FeatureSpec("fund_rate", "funding", "funding", 1, True, "latest settled funding rate"),
        FeatureSpec("fund_z", "funding", "funding", f.z_window, True,
                    f"z-score of the latest funding vs the trailing {f.z_window} fundings"),
        FeatureSpec(f"fund_sum_last_{f.sum_periods}", "funding", "funding", f.sum_periods, True,
                    f"sum of the last {f.sum_periods} settled funding rates"),
        FeatureSpec("fund_hours_to_next", "funding", "funding", 1, True,
                    "hours until the next funding (last funding time + its interval - t)"),
        FeatureSpec("funding_available", "funding", "funding", 1, False, "1 if a fresh funding record is available"),
    ]


def compute_funding(funding: FundingSeries, t_ms: np.ndarray, cfg: FeaturesConfig) -> dict[str, np.ndarray]:
    fc = cfg.funding
    names = [s.name for s in funding_specs(cfg)]
    out = {name: np.full(len(t_ms), np.nan) for name in names}
    out["funding_available"] = np.zeros(len(t_ms))
    n = len(funding)
    if n == 0:
        return out

    interval_ms = funding.interval_hours * HOUR_MS
    k = asof_index(funding.available_at_ms, t_ms)
    ok = k >= 0
    ks = np.where(ok, k, 0)
    ok &= (t_ms - funding.available_at_ms[ks]) <= fc.max_age_intervals * interval_ms[ks]

    # run[i] = number of consecutive, evenly spaced fundings ending at record i.
    contiguous = np.zeros(n, dtype=bool)
    contiguous[1:] = np.diff(funding.funding_time_ms) == interval_ms[1:]
    run = np.ones(n, dtype=np.int64)
    for i in range(1, n):
        if contiguous[i]:
            run[i] = run[i - 1] + 1

    rate = funding.funding_rate
    w = fc.z_window
    mean, std = ind.rolling_mean(rate, w), ind.rolling_std(rate, w, ddof=0)
    z_rec = np.where((run >= w) & (std > 0), ind.safe_divide(rate - mean, std), np.nan)
    m = fc.sum_periods
    sum_rec = np.where(run >= m, ind.rolling_sum(rate, m), np.nan)
    hours_next = (funding.funding_time_ms[ks] + interval_ms[ks] - t_ms) / HOUR_MS
    hours_next = np.where(hours_next >= 0, hours_next, np.nan)

    def pick(rec: np.ndarray) -> np.ndarray:
        return np.where(ok, rec[ks], np.nan)

    out["fund_rate"] = pick(rate)
    out["fund_z"] = pick(z_rec)
    out[f"fund_sum_last_{m}"] = pick(sum_rec)
    out["fund_hours_to_next"] = np.where(ok, hours_next, np.nan)
    out["funding_available"] = ok.astype(np.float64)
    return {name: ind.finite_or_nan(out[name]) for name in names}


def oi_specs(cfg: FeaturesConfig) -> list[FeatureSpec]:
    o = cfg.open_interest
    specs = [
        FeatureSpec(f"oi_chg_{h}h", "open_interest", "oi", h + 1, False,
                    f"log change of open interest over {h}h (hourly as-of values)")
        for h in o.change_hours
    ]
    specs += [
        FeatureSpec("oi_z", "open_interest", "oi", o.z_window_hours, False,
                    f"z-score of log open interest vs the trailing {o.z_window_hours}h"),
        FeatureSpec("oi_top_ls_log", "open_interest", "oi", 1, False, "log top-trader long/short (position) ratio"),
        FeatureSpec("oi_taker_ls_log", "open_interest", "oi", 1, False, "log taker buy/sell volume ratio"),
        FeatureSpec("oi_age_s", "open_interest", "oi", 1, False, "seconds since the latest usable OI snapshot timestamp"),
        FeatureSpec("oi_available", "open_interest", "oi", 1, False, "1 if a fresh OI snapshot is available"),
    ]
    return specs


def _log_positive(x: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        return np.where(x > 0, np.log(np.where(x > 0, x, 1.0)), np.nan)


def compute_oi(oi: OpenInterestSeries, t_ms: np.ndarray, cfg: FeaturesConfig) -> dict[str, np.ndarray]:
    oc = cfg.open_interest
    names = [s.name for s in oi_specs(cfg)]
    out = {name: np.full(len(t_ms), np.nan) for name in names}
    out["oi_available"] = np.zeros(len(t_ms))
    if len(oi) == 0 or len(t_ms) == 0:
        return out
    if np.any(t_ms % HOUR_MS != 0):
        raise ValueError("decision times must be whole hours")
    stale_ms = oc.max_staleness_seconds * 1000

    # Hourly as-of series of log OI on a global hour grid. Each value uses only snapshots available at
    # that hour and is NaN when the latest one is stale, so source gaps stay visible as NaN.
    g0 = -(-int(oi.available_at_ms[0]) // HOUR_MS) * HOUR_MS
    g1 = int(t_ms.max())
    if g1 >= g0:
        grid = np.arange(g0, g1 + 1, HOUR_MS, dtype=np.int64)
        level = asof_join(oi.available_at_ms, oi.sum_open_interest, grid, max_age_ms=stale_ms, event_time_ms=oi.ts_ms)
        log_oi = _log_positive(level)
        series = {f"oi_chg_{h}h": log_oi - ind.shift(log_oi, h) for h in oc.change_hours}
        series["oi_z"] = ind.rolling_nan_zscore(
            log_oi, oc.z_window_hours, math.ceil(oc.z_min_valid_fraction * oc.z_window_hours)
        )
        series["oi_available"] = np.isfinite(log_oi).astype(np.float64)
        pos = (t_ms - g0) // HOUR_MS
        in_grid = t_ms >= g0
        for name, arr in series.items():
            out[name] = np.where(in_grid, arr[np.where(in_grid, pos, 0)], np.nan)
        out["oi_available"] = np.where(in_grid, out["oi_available"], 0.0)

    for name, col in (("oi_top_ls_log", oi.top_trader_ls_ratio), ("oi_taker_ls_log", oi.taker_ls_vol_ratio)):
        out[name] = _log_positive(
            asof_join(oi.available_at_ms, col, t_ms, max_age_ms=stale_ms, event_time_ms=oi.ts_ms)
        )
    k = asof_index(oi.available_at_ms, t_ms)
    ks = np.where(k >= 0, k, 0)
    age_ms = t_ms - oi.ts_ms[ks]
    fresh = (k >= 0) & (age_ms <= stale_ms)
    out["oi_age_s"] = np.where(fresh, age_ms / 1000.0, np.nan)
    return {name: ind.finite_or_nan(out[name]) for name in names}


def time_specs() -> list[FeatureSpec]:
    return [
        FeatureSpec(name, "time", "time", 1, True, desc)
        for name, desc in (
            ("time_hour_sin", "sin of UTC hour-of-day angle"),
            ("time_hour_cos", "cos of UTC hour-of-day angle"),
            ("time_dow_sin", "sin of UTC day-of-week angle"),
            ("time_dow_cos", "cos of UTC day-of-week angle"),
        )
    ]


def compute_time(t_ms: np.ndarray) -> dict[str, np.ndarray]:
    """Calendar features from the decision time alone."""
    day_ms = 24 * HOUR_MS
    hour = (t_ms % day_ms) / HOUR_MS
    dow = ((t_ms // day_ms) + 3) % 7  # 1970-01-01 was a Thursday; Monday = 0
    return {
        "time_hour_sin": np.sin(2 * math.pi * hour / 24.0),
        "time_hour_cos": np.cos(2 * math.pi * hour / 24.0),
        "time_dow_sin": np.sin(2 * math.pi * dow / 7.0),
        "time_dow_cos": np.cos(2 * math.pi * dow / 7.0),
    }

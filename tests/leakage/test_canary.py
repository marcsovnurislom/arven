"""Test the tests: deliberately leaky features must be caught by the leakage checks.

If any of these stopped failing detection, the truncation / perturbation tests would be worthless.
A causal control feature must NOT be flagged (no false positives).
"""

import numpy as np
import pytest
from leakage_harness import perturbation_leaks, sample_times, truncation_leaks
from synthetic_market import hourly_grid, make_market

from arven.core.features_config import load_features_config
from arven.core.timeframes import Timeframe
from arven.features import indicators as ind
from arven.features.asof import asof_join
from arven.features.builder import build_features

CFG = load_features_config()


def close_at_t(inputs, t_ms):
    """1h close of the bar that closes at t (the legitimate 'now' value)."""
    h1 = inputs.bars[Timeframe.H1]
    return asof_join(h1.available_at_ms, h1.close, t_ms, max_age_ms=h1.timeframe.ms - 1), h1


def canary(kind):
    def compute(inputs, t_ms):
        cols = dict(build_features(inputs, t_ms, CFG).columns)
        now, h1 = close_at_t(inputs, t_ms)
        if kind == "future_close":  # the close of the bar that is still open at t
            idx = np.searchsorted(h1.open_time_ms, t_ms)
            safe = np.minimum(idx, len(h1) - 1)
            match = (idx < len(h1)) & (h1.open_time_ms[safe] == t_ms)
            cols["canary"] = np.where(match, h1.close[safe], np.nan)
        elif kind == "centered_mean":  # rolling mean centred on t: uses 2 bars of the future
            series = ind.rolling_mean(h1.close, 5)
            centred = np.full(len(h1), np.nan)
            centred[:-2] = series[2:]  # value for bar i taken from the window ending at i + 2
            cols["canary"] = asof_join(h1.available_at_ms, centred, t_ms, max_age_ms=h1.timeframe.ms - 1)
        elif kind == "full_sample_zscore":  # normalised with statistics of all data present
            cols["canary"] = (now - np.nanmean(h1.close)) / np.nanstd(h1.close)
        elif kind == "trailing_control":  # causal: trailing 24-bar mean
            cols["canary"] = asof_join(h1.available_at_ms, ind.rolling_mean(h1.close, 24), t_ms, max_age_ms=h1.timeframe.ms - 1)
        else:  # pragma: no cover
            raise AssertionError(kind)
        return cols

    return compute


@pytest.fixture(scope="module")
def setup():
    market = make_market(n_days=40, seed=12)
    grid = hourly_grid(market, first_hour=30)
    return market, grid, sample_times(grid, 14, seed=5, tail=3)


@pytest.mark.parametrize("kind", ["future_close", "centered_mean", "full_sample_zscore"])
def test_truncation_test_catches_leaky_feature(kind, setup):
    market, grid, samples = setup
    leaks = truncation_leaks(canary(kind), market, grid, samples)
    assert "canary" in leaks, f"truncation test failed to catch the {kind} leak"
    assert set(leaks) == {"canary"}, "the real features must not be flagged"


@pytest.mark.parametrize("kind", ["future_close", "centered_mean", "full_sample_zscore"])
def test_perturbation_test_catches_leaky_feature(kind, setup):
    market, grid, samples = setup
    leaks = perturbation_leaks(canary(kind), market, grid, samples[::2])
    assert "canary" in leaks, f"perturbation test failed to catch the {kind} leak"
    assert set(leaks) == {"canary"}


def test_causal_control_is_not_flagged(setup):
    market, grid, samples = setup
    assert truncation_leaks(canary("trailing_control"), market, grid, samples) == {}
    assert perturbation_leaks(canary("trailing_control"), market, grid, samples[::2]) == {}

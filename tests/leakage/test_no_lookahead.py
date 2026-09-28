"""Point-in-time guarantees of the feature builder (architecture section 10, rules 2-5).

Truncation test: the row at ``t`` computed from all data equals the row computed from only the data that
was available at ``t``. Perturbation test: replacing everything that became available after ``t`` with
garbage does not change the row at ``t``. Both are exact (bitwise, NaN == NaN) and run for **every**
registered feature.
"""

import numpy as np
import pytest
from leakage_harness import perturbation_leaks, sample_times, truncation_leaks
from synthetic_market import HOUR, hourly_grid, make_funding, make_market

from arven.core.features_config import load_features_config
from arven.core.series import MarketInputs
from arven.features.builder import build_features
from arven.features.registry import build_registry

CFG = load_features_config()
SPECS = build_registry(CFG)


def compute(inputs, t_ms):
    return build_features(inputs, t_ms, CFG).columns


def choose_samples(grid: np.ndarray) -> np.ndarray:
    ready = grid[4100:]  # past the longest warm-up (4h EMA200), so most features are finite
    early = grid[:200]
    boundaries = grid[(grid // HOUR) % 4 == 0][::37]
    picks = [sample_times(grid, 22, seed=7, tail=3), sample_times(ready, 10, seed=8), sample_times(early, 4, seed=9), boundaries[:6]]
    return np.unique(np.concatenate(picks))


@pytest.fixture(scope="module")
def market():
    return make_market(n_days=240, seed=1)


@pytest.fixture(scope="module")
def grid(market):
    return hourly_grid(market, first_hour=1)


@pytest.fixture(scope="module")
def samples(grid):
    return choose_samples(grid)


@pytest.fixture(scope="module")
def truncation(market, grid, samples):
    return truncation_leaks(compute, market, grid, samples)


@pytest.fixture(scope="module")
def perturbation(market, grid, samples):
    return perturbation_leaks(compute, market, grid[: len(grid)], samples[::2])


@pytest.mark.parametrize("name", [s.name for s in SPECS])
def test_truncation_no_lookahead(name, truncation):
    assert name not in truncation, f"{name} changes when future data is removed: t={truncation.get(name)}"


@pytest.mark.parametrize("name", [s.name for s in SPECS])
def test_perturbation_no_lookahead(name, perturbation):
    assert name not in perturbation, f"{name} changes when future data is replaced: t={perturbation.get(name)}"


@pytest.mark.parametrize("name", [s.name for s in SPECS if s.name not in ("funding_available", "oi_available")])
def test_leakage_samples_are_not_vacuous(name, market, samples):
    """Every feature is finite at several sampled decision times, so the equality checks above mean something."""
    col = build_features(market, samples, CFG).columns[name]
    assert np.isfinite(col).sum() >= 5, f"{name} is NaN at almost every sampled time"


def test_truncation_with_availability_delay_and_publication_jitter():
    """With a bar delay and funding published late, the row at t must still ignore anything not yet available."""
    delayed = make_market(n_days=120, seed=4, delay_ms=60_000)
    inputs = MarketInputs(bars=delayed.bars, funding=make_funding(120, seed=5, jitter_ms=45), open_interest=delayed.open_interest)
    grid = hourly_grid(inputs, first_hour=1)
    samples = np.unique(np.concatenate([sample_times(grid, 15, seed=3, tail=3), grid[(grid // HOUR) % 8 == 0][:6]]))
    assert truncation_leaks(compute, inputs, grid, samples) == {}
    assert perturbation_leaks(compute, inputs, grid, samples[::3]) == {}


def test_recomputing_from_a_later_start_changes_recursive_features_slightly():
    """Documents why builds always start at the first stored bar: EMAs are seeded there.

    (Not a leak: dropping early history is simply *not* equivalent for recursive indicators, so caches and
    live loops must not silently do it. The difference is small but non-zero.)
    """
    from arven.core.timeframes import Timeframe

    market = make_market(n_days=120, seed=6)
    h1 = market.bars[Timeframe.H1]
    cut, last = 400, 500  # trimmed series has exactly the 100 bars EMA20 needs (5 x 20) to emit at bar 500
    t = h1.close_time_ms[last : last + 1]
    full = build_features(market, t, CFG).columns["h1_ema_dist_20"][0]
    trimmed = h1.__class__(
        h1.timeframe, h1.delay_ms, h1.open_time_ms[cut:], h1.open[cut:], h1.high[cut:], h1.low[cut:], h1.close[cut:],
        h1.volume[cut:], h1.trade_count[cut:], h1.taker_buy_volume[cut:], h1.complete[cut:],
    )
    market2 = MarketInputs(bars={**market.bars, Timeframe.H1: trimmed}, funding=market.funding, open_interest=market.open_interest)
    other = build_features(market2, t, CFG).columns["h1_ema_dist_20"][0]
    assert np.isfinite(full) and np.isfinite(other)
    assert full != other
    assert abs(full - other) < 1e-3

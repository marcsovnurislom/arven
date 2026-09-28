"""Leakage and alignment spot checks on the real stored data.

Opt-in (they take minutes): ``ARVEN_REAL_DATA_TESTS=1 ARVEN_REAL_DATA_SAMPLES=200 pytest -m real_data``.

Only the **development period** is ever loaded (inputs end at ``splits.development.end``), so the sealed
test period is not touched. The database is opened read-only.
"""

import math
import os

import numpy as np
import pytest
from leakage_harness import perturbation_leaks, sample_times, truncation_leaks

from arven.core.config import load_config
from arven.core.features_config import load_features_config
from arven.core.time import to_ms, to_utc_datetime
from arven.core.timeframes import Timeframe
from arven.data.reader import load_feature_inputs, open_readonly
from arven.features.builder import build_features, decision_grid

pytestmark = pytest.mark.real_data

HOUR = 3_600_000
SAMPLES = int(os.environ.get("ARVEN_REAL_DATA_SAMPLES", "25"))


@pytest.fixture(scope="module")
def real():
    if os.environ.get("ARVEN_REAL_DATA_TESTS") != "1":
        pytest.skip("set ARVEN_REAL_DATA_TESTS=1 to run real-data checks")
    cfg = load_config()
    if not cfg.data.database_path.exists():
        pytest.skip("no local database")
    fcfg = load_features_config()
    dev_end = cfg.splits.development.end
    con = open_readonly(cfg.data.database_path)
    try:
        inputs = load_feature_inputs(con, cfg, end=dev_end)
    finally:
        con.close()
    grid = decision_grid(to_ms(cfg.data.history_start), to_ms(dev_end))
    return cfg, fcfg, inputs, grid


def compute_with(fcfg):
    return lambda inputs, t: build_features(inputs, t, fcfg).columns


def special_times(grid):
    wanted = ["2020-09-01T00:00:00", "2020-09-01T01:00:00", "2021-05-15T01:00:00", "2021-06-22T19:00:00",
              "2021-06-22T20:00:00", "2021-12-01T00:00:00", "2022-03-01T00:00:00"]
    times = [to_ms(to_utc_datetime(w + "+00:00")) for w in wanted]
    return np.array([t for t in times if t in set(grid.tolist())], dtype=np.int64)


def test_real_data_truncation_and_perturbation(real):
    cfg, fcfg, inputs, grid = real
    compute = compute_with(fcfg)
    ready = grid[int(np.searchsorted(grid, to_ms(to_utc_datetime("2020-07-01T00:00:00+00:00")))):]
    samples = np.unique(np.concatenate([
        sample_times(ready, SAMPLES, seed=21, tail=3),
        sample_times(grid[:4000], max(SAMPLES // 8, 3), seed=22),
        special_times(grid),
    ]))
    leaks = truncation_leaks(compute, inputs, grid, samples)
    assert leaks == {}, f"truncation leaks on real data: {leaks}"
    perturbed = perturbation_leaks(compute, inputs, grid, samples[:: max(len(samples) // 12, 1)])
    assert perturbed == {}, f"perturbation leaks on real data: {perturbed}"


def test_real_data_returns_match_an_independent_sql_computation(real):
    cfg, fcfg, inputs, grid = real
    table = build_features(inputs, grid, fcfg)
    rng = np.random.default_rng(3)
    con = open_readonly(cfg.data.database_path)
    try:
        for t in rng.choice(grid[5000:], 25, replace=False):
            for tf, name in ((Timeframe.H1, "h1_ret_1"), (Timeframe.H4, "h4_ret_1")):
                rows = con.execute(
                    "SELECT close FROM ohlcv WHERE symbol = ? AND timeframe = ? AND close_time_ms <= ? "
                    "ORDER BY close_time_ms DESC LIMIT 2",
                    [cfg.market.symbol, tf.value, int(t)],
                ).fetchall()
                expected = math.log(rows[0][0] / rows[1][0])
                got = table.columns[name][int(np.searchsorted(grid, t))]
                assert got == pytest.approx(expected, rel=1e-12), f"{name} at {t}"
    finally:
        con.close()


def test_real_data_invariants_and_no_inf(real):
    from arven.features.checks import invariant_violations

    _, fcfg, inputs, grid = real
    assert invariant_violations(build_features(inputs, grid, fcfg)) == []

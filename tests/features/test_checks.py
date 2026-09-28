import numpy as np

from arven.features.builder import FeatureTable
from arven.features.checks import invariant_violations


def table(**cols):
    n = len(next(iter(cols.values())))
    return FeatureTable("v1", np.arange(n, dtype=np.int64), {k: np.array(v, dtype=float) for k, v in cols.items()}, ())


def test_valid_values_and_nan_pass():
    assert invariant_violations(table(h1_rsi=[np.nan, 0.0, 100.0], h1_taker_buy_ratio=[0.2, 0.9, np.nan], time_hour_sin=[-1, 0, 1])) == []


def test_out_of_range_and_inf_are_reported():
    problems = invariant_violations(table(h1_rsi=[101.0], h4_taker_buy_ratio=[-0.1], h1_atr_pct=[np.inf], time_dow_cos=[1.5], feat_ready=[2.0]))
    joined = " ".join(problems)
    for name in ("h1_rsi", "h4_taker_buy_ratio", "h1_atr_pct", "time_dow_cos", "feat_ready"):
        assert name in joined

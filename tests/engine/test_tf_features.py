"""Phase 2: the generic per-timeframe feature table (``arven.engine.features``) - hand-computed cases."""

from __future__ import annotations

import math

import numpy as np
import pytest
from synthetic_market import START_MS, aggregate, make_5m

from arven.core.series import BarSeries
from arven.core.timeframes import Timeframe
from arven.engine.features import (
    DEFAULT_PARAMS,
    FEATURE_SET_VERSION,
    TFFeatureParams,
    TFFeatureTable,
    compute_tf_features,
    feature_names,
    qualified_name,
)
from arven.features import indicators as ind

HOUR = 3_600_000
NAN = float("nan")
# Small periods and warmup_factor 1 so warm-up boundaries can be checked by hand.
SMALL = TFFeatureParams(ema_fast=2, ema_slow=3, slope_bars=1, adx_period=2, atr_period=2, warmup_factor=1.0)


def bars(close, tf=Timeframe.H1, delay_ms=0, start_ms=START_MS, open_times=None, complete=None, spread=1.0):
    close = np.asarray(close, dtype=float)
    n = len(close)
    ot = np.asarray(open_times, dtype=np.int64) if open_times is not None else start_ms + np.arange(n) * tf.ms
    return BarSeries(
        tf, delay_ms, ot, close, close + spread, close - spread, close,
        np.ones(n), np.ones(n), np.ones(n) * 0.5, np.ones(n, dtype=bool) if complete is None else np.asarray(complete),
    )


def col(table, name):
    return table.column(name)


# --- names ------------------------------------------------------------------------------------------


def test_default_column_names_and_order():
    assert feature_names() == (
        "close", "atr_14", "atr_pct_14", "ema_dist_20", "ema_dist_50", "ema_slope_50", "adx_14",
    )


def test_names_follow_the_parameters():
    assert feature_names(SMALL) == ("close", "atr_2", "atr_pct_2", "ema_dist_2", "ema_dist_3", "ema_slope_3", "adx_2")


def test_qualified_names_cannot_collide_with_stage3_columns():
    from arven.core.features_config import load_features_config
    from arven.features.registry import build_registry

    stage3 = {s.name for s in build_registry(load_features_config())}
    ours = {qualified_name(tf, n) for tf in Timeframe for n in feature_names()}
    assert qualified_name(Timeframe.H4, "adx_14") == "4h.adx_14"
    assert all("." not in n for n in stage3)
    assert not stage3 & ours


# --- parameter validation ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [dict(ema_fast=50, ema_slow=20), dict(ema_fast=0), dict(slope_bars=0), dict(adx_period=1), dict(atr_period=1),
     dict(warmup_factor=0.5)],
)
def test_invalid_params_are_rejected(kwargs):
    with pytest.raises(ValueError):
        TFFeatureParams(**kwargs)


def test_warmup_rule_matches_stage3():
    assert DEFAULT_PARAMS.warmup(14) == 70
    assert TFFeatureParams(warmup_factor=1.0).warmup(14) == 14
    assert TFFeatureParams(warmup_factor=1.5).warmup(5) == 8


# --- hand-computed values ----------------------------------------------------------------------------


def test_constant_bars_hand_computed_values_and_warmup_boundaries():
    t = compute_tf_features(bars([100.0] * 8), SMALL)
    assert t.version == FEATURE_SET_VERSION
    np.testing.assert_array_equal(col(t, "close"), [100.0] * 8)
    # TR[0] is NaN (no previous close); TR = 2 from bar 1; Wilder RMA(2) needs 2 valid inputs -> first at bar 2.
    np.testing.assert_array_equal(col(t, "atr_2"), [NAN, NAN] + [2.0] * 6)
    np.testing.assert_array_equal(col(t, "atr_pct_2"), [NAN, NAN] + [0.02] * 6)
    # EMA2 emits from bar 1, EMA3 from bar 2; constant price -> distance 0.
    np.testing.assert_array_equal(col(t, "ema_dist_2"), [NAN] + [0.0] * 7)
    np.testing.assert_array_equal(col(t, "ema_dist_3"), [NAN, NAN] + [0.0] * 6)
    np.testing.assert_array_equal(col(t, "ema_slope_3"), [NAN, NAN, NAN] + [0.0] * 5)
    # No directional movement -> DX 0 -> ADX 0; DI valid from bar 2, ADX(2) needs 2 DX values -> first at bar 3.
    np.testing.assert_array_equal(col(t, "adx_2"), [NAN, NAN, NAN] + [0.0] * 5)


def test_ema_distance_and_slope_hand_computed_on_a_ramp():
    t = compute_tf_features(bars([1.0, 2.0, 3.0, 4.0], spread=0.5), SMALL)
    # EMA2: alpha 2/3 -> 1, 5/3, 23/9, ... ; EMA3: alpha 1/2 -> 1, 1.5, 2.25, 3.125 (emits from the 3rd bar)
    assert col(t, "ema_dist_2")[1] == pytest.approx(math.log(2.0 / (5.0 / 3.0)), abs=1e-15)
    assert col(t, "ema_dist_2")[2] == pytest.approx(math.log(3.0 / (23.0 / 9.0)), abs=1e-15)
    d3 = col(t, "ema_dist_3")
    assert math.isnan(d3[1])
    assert d3[2] == pytest.approx(math.log(3.0 / 2.25), abs=1e-15)
    assert d3[3] == pytest.approx(math.log(4.0 / 3.125), abs=1e-15)
    assert col(t, "ema_slope_3")[3] == pytest.approx(math.log(3.125 / 2.25), abs=1e-15)
    # TR on the ramp: bar1 = max(1, |2.5-1|, |1.5-1|) = 1.5 (and 1.5 thereafter); ATR(2) = 1.5 from bar 2.
    assert col(t, "atr_2")[2] == pytest.approx(1.5)
    assert col(t, "atr_pct_2")[3] == pytest.approx(1.5 / 4.0)
    # Pure up-moves: +DM > 0, -DM = 0 -> DX = 100 -> ADX 100 once warmed up.
    assert col(t, "adx_2")[3] == pytest.approx(100.0)


def test_matches_the_shared_indicator_primitives_on_synthetic_data():
    s = aggregate(make_5m(288 * 40, seed=3), Timeframe.H1)
    t = compute_tf_features(s)
    p = DEFAULT_PARAMS
    h, lo, c = s.high, s.low, s.close
    atr = ind.atr(h, lo, c, 14, 70)
    e50 = ind.ema(c, 50, 250)
    np.testing.assert_array_equal(col(t, "atr_14"), atr)
    np.testing.assert_array_equal(col(t, "atr_pct_14"), ind.safe_divide(atr, c))
    np.testing.assert_array_equal(col(t, "ema_dist_20"), ind.log_ratio(c, ind.ema(c, 20, 100)))
    np.testing.assert_array_equal(col(t, "ema_dist_50"), ind.log_ratio(c, e50))
    np.testing.assert_array_equal(col(t, "ema_slope_50"), ind.log_ratio(e50, ind.shift(e50, p.slope_bars)))
    np.testing.assert_array_equal(col(t, "adx_14"), ind.adx(h, lo, c, 14, 70))
    assert np.isfinite(t.values[300:]).all()  # past every warm-up, nothing is NaN on clean data


# --- grid, gaps, availability --------------------------------------------------------------------------


def test_rows_carry_open_close_and_available_at_including_the_delay():
    t = compute_tf_features(bars([100.0] * 3, tf=Timeframe.M15, delay_ms=5_000), SMALL)
    np.testing.assert_array_equal(t.open_ms, START_MS + np.arange(3) * Timeframe.M15.ms)
    np.testing.assert_array_equal(t.close_ms, t.open_ms + Timeframe.M15.ms)
    np.testing.assert_array_equal(t.available_at_ms, t.close_ms + 5_000)
    assert t.timeframe == Timeframe.M15


def test_missing_bar_becomes_a_nan_row_and_recursive_indicators_restart():
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0]
    ot = START_MS + np.array([0, 1, 2, 4, 5, 6, 7, 8]) * HOUR  # the bar at +3h is missing
    t = compute_tf_features(bars(closes, open_times=ot), SMALL)
    assert len(t) == 9
    np.testing.assert_array_equal(t.open_ms, START_MS + np.arange(9) * HOUR)
    assert not t.complete[3] and t.complete[[0, 1, 2, 4, 5, 6, 7, 8]].all()
    assert np.isnan(t.values[3]).all()
    # After the gap the EMA restarts: identical to a fresh series starting at the bar after the gap.
    fresh = compute_tf_features(bars(closes[3:], start_ms=START_MS + 4 * HOUR), SMALL)
    np.testing.assert_array_equal(col(t, "ema_dist_3")[4:], col(fresh, "ema_dist_3"))
    np.testing.assert_array_equal(col(t, "atr_2")[4:], col(fresh, "atr_2"))


def test_incomplete_bar_is_treated_exactly_like_a_missing_bar():
    closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    flagged = compute_tf_features(bars(closes, complete=[True, True, False, True, True]), SMALL)
    assert not flagged.complete[2]
    assert np.isnan(flagged.values[2]).all()
    assert np.isnan(col(flagged, "ema_dist_2")[3])  # restarted, still warming up


def test_the_same_function_serves_every_timeframe():
    closes = list(100.0 + np.sin(np.arange(60) / 3.0))
    a = compute_tf_features(bars(closes, tf=Timeframe.H1), SMALL)
    b = compute_tf_features(bars(closes, tf=Timeframe.M5), SMALL)
    np.testing.assert_array_equal(a.values, b.values)  # same bars -> same numbers, only the times differ
    assert a.timeframe == Timeframe.H1 and b.timeframe == Timeframe.M5
    assert (np.diff(a.open_ms) == HOUR).all() and (np.diff(b.open_ms) == Timeframe.M5.ms).all()


def test_empty_series_gives_an_empty_table():
    t = compute_tf_features(bars([]), SMALL)
    assert len(t) == 0 and t.values.shape == (0, len(t.names))


def test_computation_is_deterministic():
    s = aggregate(make_5m(288 * 20, seed=5), Timeframe.M15)
    assert compute_tf_features(s).content_sha256() == compute_tf_features(s).content_sha256()


def test_non_finite_results_become_nan():
    t = compute_tf_features(bars([0.0] * 5, spread=0.0), SMALL)  # close 0 -> log/division undefined
    assert not np.isinf(t.values).any()
    assert np.isnan(col(t, "atr_pct_2")).all() and np.isnan(col(t, "ema_dist_2")).all()


# --- table validation ----------------------------------------------------------------------------------


def _table(**over):
    base = dict(
        timeframe=Timeframe.H1, version="x", open_ms=np.array([0, HOUR]), close_ms=np.array([HOUR, 2 * HOUR]),
        available_at_ms=np.array([HOUR, 2 * HOUR]), complete=np.array([True, True]), names=("a",),
        values=np.zeros((2, 1)),
    )
    return TFFeatureTable(**(base | over))


def test_table_accepts_a_consistent_layout():
    assert len(_table()) == 2


@pytest.mark.parametrize(
    "over",
    [
        dict(values=np.zeros((2, 2))),
        dict(names=("a", "a"), values=np.zeros((2, 2))),
        dict(close_ms=np.array([HOUR])),
        dict(close_ms=np.array([HOUR, 3 * HOUR])),
        dict(available_at_ms=np.array([2 * HOUR, 2 * HOUR])),
        dict(available_at_ms=np.array([HOUR - 1, 2 * HOUR])),
    ],
)
def test_table_rejects_inconsistent_layouts(over):
    with pytest.raises(ValueError):
        _table(**over)

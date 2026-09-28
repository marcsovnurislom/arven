"""Bar features: declared warm-up matches reality, and multi-timeframe alignment is exactly as-of."""

import numpy as np
import pytest
from synthetic_market import HOUR, START_MS, make_market

from arven.core.features_config import load_features_config
from arven.core.timeframes import Timeframe
from arven.features.bars import bar_features, compute_bar_features
from arven.features.builder import build_features
from arven.features.registry import BAR_TIMEFRAMES

CFG = load_features_config()
MARKET = make_market(n_days=240, seed=1)


@pytest.mark.parametrize("tf", BAR_TIMEFRAMES, ids=lambda tf: tf.value)
def test_declared_warmup_matches_first_valid_value(tf):
    regular = MARKET.bars[tf].regularized()
    values = compute_bar_features(tf, regular, CFG)
    specs = [f.spec for f in bar_features(tf, CFG)]
    assert set(values) == {s.name for s in specs}
    for s in specs:
        col = values[s.name]
        first = s.warmup_bars - 1
        assert np.isnan(col[:first]).all(), f"{s.name} emits before its declared warm-up"
        assert np.isfinite(col[first:]).all(), f"{s.name} is not finite from index {first} on clean data"


def test_warmup_follows_configured_factor():
    slow = load_features_config()
    fast = slow.model_copy(update={"warmup_factor": 2.0})
    a = {s.name: s.warmup_bars for tf in BAR_TIMEFRAMES for s in (f.spec for f in bar_features(tf, slow))}
    b = {s.name: s.warmup_bars for tf in BAR_TIMEFRAMES for s in (f.spec for f in bar_features(tf, fast))}
    assert b["h4_ema_dist_200"] == 400 and a["h4_ema_dist_200"] == 1000
    assert b["h1_rsi"] < a["h1_rsi"]


def _t(hours_after_start: int) -> np.ndarray:
    return np.array([START_MS + hours_after_start * HOUR], dtype=np.int64)


def _value(table, name):
    return float(table.columns[name][0])


def test_1h_features_use_the_bar_closing_exactly_at_t():
    h1 = MARKET.bars[Timeframe.H1]
    m = 400
    table = build_features(MARKET, _t(m), CFG)
    expected = np.log(h1.close[m - 1] / h1.close[m - 2])  # bar m-1 opens at START+(m-1)h and closes at START+m*h
    assert _value(table, "h1_ret_1") == pytest.approx(expected, rel=1e-12)


def test_4h_features_join_on_close_time_not_open_time():
    h4 = MARKET.bars[Timeframe.H4]
    base = 4 * 100  # a 4h boundary, in hours after START
    for offset, last_closed in ((0, 99), (1, 99), (3, 99), (4, 100)):
        # At boundary + 3h the bar that opened at the boundary is still incomplete: it must not be visible.
        table = build_features(MARKET, _t(base + offset), CFG)
        expected = np.log(h4.close[last_closed] / h4.close[last_closed - 1])
        assert _value(table, "h4_ret_1") == pytest.approx(expected, rel=1e-12), f"offset {offset}h"


def test_15m_and_5m_features_are_as_of_the_hour():
    m15, m5 = MARKET.bars[Timeframe.M15], MARKET.bars[Timeframe.M5]
    m = 400
    table = build_features(MARKET, _t(m), CFG)
    j = m * 4 - 1  # last 15m bar closing at or before t
    assert _value(table, "m15_ret_1") == pytest.approx(np.log(m15.close[j] / m15.close[j - 1]), rel=1e-12)
    j5 = m * 12 - 1
    r = np.log(m5.close[j5 - 11 : j5 + 1] / m5.close[j5 - 12 : j5])
    assert _value(table, "m5_rv_1h") == pytest.approx(np.sqrt((r**2).sum()), rel=1e-12)


def test_availability_delay_hides_the_bar_that_closes_at_t():
    delayed = make_market(n_days=240, seed=1, delay_ms=60_000)
    h1 = delayed.bars[Timeframe.H1]
    m = 400
    table = build_features(delayed, _t(m), CFG)
    # Bar m-1 closes at t but is usable only at t + 60 s, so the latest usable bar is m-2.
    expected = np.log(h1.close[m - 2] / h1.close[m - 3])
    assert _value(table, "h1_ret_1") == pytest.approx(expected, rel=1e-12)
    # 4h: the 4h bar closing exactly at t is not usable yet either.
    h4 = delayed.bars[Timeframe.H4]
    table = build_features(delayed, _t(4 * 100), CFG)
    assert _value(table, "h4_ret_1") == pytest.approx(np.log(h4.close[98] / h4.close[97]), rel=1e-12)


def test_stale_bars_are_nan_not_carried_forward():
    last_close = MARKET.bars[Timeframe.H1].close_time_ms[-1]
    t = np.array([last_close, last_close + HOUR, last_close + 5 * HOUR], dtype=np.int64)
    table = build_features(MARKET, t, CFG)
    assert np.isfinite(table.columns["h1_ret_1"][0])
    assert np.isnan(table.columns["h1_ret_1"][1:]).all()  # no 1h bar closed after the data ended
    # The 4h bar that closed at the end of data may still be the latest 4h bar for up to 3h, never longer.
    assert np.isnan(table.columns["h4_ret_1"][2])


def test_missing_and_incomplete_bars_make_dependent_features_nan_then_recover():
    import dataclasses

    h1 = MARKET.bars[Timeframe.H1]
    complete = h1.complete.copy()
    complete[300] = False  # one incomplete 1h bar
    broken = dataclasses.replace(h1, complete=complete)
    market = type(MARKET)(bars={**MARKET.bars, Timeframe.H1: broken}, funding=MARKET.funding, open_interest=MARKET.open_interest)
    t = np.array([START_MS + (301 + k) * HOUR for k in (0, 1, 2)], dtype=np.int64)  # closes of bars 300, 301, 302
    table = build_features(market, t, CFG)
    assert np.isnan(table.columns["h1_ret_1"][0]) and np.isnan(table.columns["h1_ret_1"][1])  # bar 300 missing / prior missing
    assert np.isfinite(table.columns["h1_ret_1"][2])
    # 24-bar returns need bar 300 as a reference 24 bars later: NaN then, finite again 25 bars on.
    t2 = np.array([START_MS + (301 + 24) * HOUR, START_MS + (301 + 25) * HOUR], dtype=np.int64)
    r24 = build_features(market, t2, CFG).columns["h1_ret_24"]
    assert np.isnan(r24[0]) and np.isfinite(r24[1])
    # A recursive indicator restarts after the NaN and stays NaN until warmed up again (no silent carry-over):
    # 70 valid changes are needed after bar 301, so bar 340 is NaN and bar 500 is finite again.
    early = np.array([START_MS + 341 * HOUR], dtype=np.int64)  # close of bar 340
    late = np.array([START_MS + 501 * HOUR], dtype=np.int64)  # close of bar 500
    assert np.isnan(build_features(market, early, CFG).columns["h1_rsi"][0])
    assert np.isfinite(build_features(market, late, CFG).columns["h1_rsi"][0])


def test_zero_volume_bar_gives_nan_ratios_not_inf():
    import dataclasses

    h1 = MARKET.bars[Timeframe.H1]
    volume, taker = h1.volume.copy(), h1.taker_buy_volume.copy()
    volume[500], taker[500] = 0.0, 0.0
    market = type(MARKET)(
        bars={**MARKET.bars, Timeframe.H1: dataclasses.replace(h1, volume=volume, taker_buy_volume=taker)},
        funding=MARKET.funding,
        open_interest=MARKET.open_interest,
    )
    table = build_features(market, np.array([START_MS + 501 * HOUR], dtype=np.int64), CFG)
    assert np.isnan(table.columns["h1_taker_buy_ratio"][0])
    assert table.columns["h1_rel_volume"][0] == 0.0  # zero volume vs a positive trailing mean is a real 0
    for col in table.columns.values():
        assert not np.isinf(col).any()

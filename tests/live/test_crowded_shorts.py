"""Crowded Shorts rules (engine) and execution (backtest) - hand-computed cases, and a leakage check of the rules."""

from __future__ import annotations

import math

import numpy as np
import pytest
from bt_helpers import app_config

from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate
from arven.backtest.crowded_shorts_sim import resolve_block
from arven.backtest.marketdata import MarketData
from arven.engine.strategy_crowded_shorts import CrowdedShortsBlock, CrowdedShortsParams, blocks, holding, signal_mask

H = 3_600_000
MIN = 60_000
P = CrowdedShortsParams(hold_hours=3)


def test_signal_mask_needs_both_conditions_and_treats_missing_data_as_no_signal():
    fz = np.array([-2.0, -2.0, -1.0, np.nan, -1.5, -2.0])
    oz = np.array([1.5, 0.5, 2.0, 2.0, 1.0, np.nan])
    assert signal_mask(fz, oz, CrowdedShortsParams()).tolist() == [True, False, False, False, True, False]


def test_holding_counts_from_the_latest_signal():
    mask = np.array([1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0], dtype=bool)
    assert holding(mask, 3).tolist() == [1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 0, 0]


def test_blocks_start_end_and_last_signal():
    t = np.arange(12) * H
    mask = np.array([1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0], dtype=bool)
    assert blocks(t, mask, P) == [CrowdedShortsBlock(0, 3 * H, 0, 0), CrowdedShortsBlock(5 * H, 10 * H, 7 * H, 5)]
    # truncated while still holding: the block has no end yet
    assert blocks(t[:9], mask[:9], P)[-1] == CrowdedShortsBlock(5 * H, None, 7 * H, 5)


def test_blocks_on_truncated_data_equal_blocks_on_full_data_up_to_the_cut():
    rng = np.random.default_rng(3)
    t = np.arange(300) * H
    mask = rng.random(300) < 0.05
    full = blocks(t, mask, P)
    for cut in range(1, 300, 7):
        part = blocks(t[:cut], mask[:cut], P)
        for b in part:
            ref = next(x for x in full if x.start_ms == b.start_ms)
            if b.end_ms is not None:
                assert b == ref
            else:
                assert ref.end_ms is None or ref.end_ms >= cut * H


def _market(rows: list[tuple[float, float, float, float]], start: int = 0) -> MarketData:
    a = np.array(rows, dtype=float)
    t = start + np.arange(len(rows), dtype=np.int64) * MIN
    return MarketData(t, a[:, 0], a[:, 1], a[:, 2], a[:, 3], start, start + len(rows) * MIN, np.zeros(0, dtype=np.int64), np.zeros(0), 8 * H)


def _costs():
    return app_config().costs


def test_time_exit_hand_computed():
    costs = _costs()
    m = _market([(100, 101, 99.5, 100.5)] + [(101, 102, 100, 101)] * 4 + [(103, 104, 102, 103)])
    tr = resolve_block(CrowdedShortsBlock(0, 5 * MIN, 0, 0), m, costs, 0.03)
    entry = adverse_price(100.0, 1, slippage_fraction(100, 101, 99.5, costs, False))
    exit_ = adverse_price(103.0, -1, slippage_fraction(103, 104, 102, costs, False))
    fee = taker_fee_rate(costs)
    assert tr.closed and tr.reason == "TIME" and tr.exit_ms == 5 * MIN
    assert tr.entry == pytest.approx(entry) and tr.stop == pytest.approx(entry * 0.97)
    assert tr.r == pytest.approx((exit_ - entry - fee * (entry + exit_)) / (entry - entry * 0.97))


def test_stop_and_gap_through_the_stop_fill_at_the_open():
    costs = _costs()
    m = _market([(100, 100, 100, 100), (100, 100, 99, 99.5), (95, 96, 94, 95), (99, 99, 99, 99)])
    tr = resolve_block(CrowdedShortsBlock(0, 3 * MIN, 0, 0), m, costs, 0.03)
    assert tr.closed and tr.reason == "STOP" and tr.exit_ms == 2 * MIN
    assert tr.exit == pytest.approx(adverse_price(95.0, -1, slippage_fraction(95, 96, 94, costs, False)))
    assert tr.r < -1.0  # the gap made it worse than the planned 1 R


def test_open_block_and_missing_entry_bar():
    costs = _costs()
    m = _market([(100, 100.5, 99.8, 100)] * 3)
    open_ = resolve_block(CrowdedShortsBlock(0, None, 0, 0), m, costs, 0.03)
    assert not open_.closed and open_.r is None and math.isfinite(open_.stop)
    late = resolve_block(CrowdedShortsBlock(0, 10 * MIN, 0, 0), m, costs, 0.03)
    assert not late.closed  # the planned exit minute is not stored yet
    assert resolve_block(CrowdedShortsBlock(30 * MIN, None, 30 * MIN, 0), m, costs, 0.03) is None


def test_params_validation():
    with pytest.raises(ValueError):
        CrowdedShortsParams(hold_hours=0)
    with pytest.raises(ValueError):
        CrowdedShortsParams(stop_fraction=1.5)


def _research_blocks(t, fund_z, oi_z, hours):
    """Verbatim logic of scripts/research/cs_sealed_test.py ``trades_from_signals`` (with edge_lab.hold) - the code
    that produced the pre-registered and sealed-test numbers."""
    z = np.nan_to_num(fund_z, nan=0.0)
    oz = np.nan_to_num(oi_z, nan=-9.0)
    events = ((z <= -1.5) & (oz >= 1.0)).astype(float)
    pos = np.zeros(len(events))
    last, left = 0.0, 0
    for i, e in enumerate(events):
        if e != 0:
            last, left = e, hours
        if left > 0:
            pos[i] = last
            left -= 1
    starts = np.flatnonzero((pos != 0) & (np.concatenate([[0.0], pos[:-1]]) == 0))
    out = []
    for s in starts:
        e = s
        while e < len(pos) and pos[e] != 0:
            e += 1
        out.append((int(t[s]), int(t[e]) if e < len(t) else None))
    return out


def test_blocks_match_the_research_script_exactly():
    rng = np.random.default_rng(11)
    t = np.arange(5000) * H
    fz = rng.normal(0, 1, 5000) - 0.4
    oz = rng.normal(0, 1, 5000) + 0.3
    fz[rng.random(5000) < 0.02] = np.nan
    oz[rng.random(5000) < 0.02] = np.nan
    mine = [(b.start_ms, b.end_ms) for b in blocks(t, signal_mask(fz, oz, CrowdedShortsParams()), CrowdedShortsParams())]
    assert mine == _research_blocks(t, fz, oz, 24) and len(mine) > 20

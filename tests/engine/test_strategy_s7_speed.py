"""The S7 detector's speed-ups (2026-10-16) change no result: each fast path equals the original formulation.

On the real 15m history 2020 -> 2026-10-16 the optimised detector returned the same 590 setups (live configuration)
and 1567 setups (defaults) as before, compared field by field (docs/current_state.md); these tests pin the
equivalences on synthetic data."""

from __future__ import annotations

import numpy as np
import pytest

from arven.engine.strategy_s7 import (
    SWING_K,
    S7Params,
    _confluence,
    _known_swings,
    detect_setups,
    swing_highs,
    swing_lows,
)


def _walk(n: int, seed: int) -> tuple[np.ndarray, ...]:
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 1, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.exponential(0.6, n)
    lo = np.minimum(o, c) - rng.exponential(0.6, n)
    v = rng.exponential(100, n)
    return o, h, lo, c, v


@pytest.mark.parametrize("seed", range(5))
def test_known_swings_equals_the_boolean_mask(seed):
    rng = np.random.default_rng(seed)
    swings = np.unique(rng.integers(0, 5000, 400))
    for _ in range(300):
        t, first = int(rng.integers(0, 5200)), int(rng.integers(-50, 5200))
        mask = swings[(swings + SWING_K <= t) & (swings >= first)]
        assert np.array_equal(_known_swings(swings, t, first), mask)


@pytest.mark.parametrize("seed", range(3))
def test_full_series_swings_equal_the_prefix_swings_once_confirmed(seed):
    _, h, lo, _, _ = _walk(3000, seed)
    full_h, full_l = swing_highs(h), swing_lows(lo)
    for t in (50, 777, 1500, 2999):
        pre_h, pre_l = swing_highs(h[: t + 1]), swing_lows(lo[: t + 1])
        assert np.array_equal(full_h[full_h + SWING_K <= t], pre_h[pre_h + SWING_K <= t])
        assert np.array_equal(full_l[full_l + SWING_K <= t], pre_l[pre_l + SWING_K <= t])


@pytest.mark.parametrize("seed", range(4))
def test_confluence_with_precomputed_swings_equals_the_prefix_computation(seed):
    o, h, lo, c, v = _walk(6000, seed)
    p = S7Params(min_touches=2)
    setups = [s for s in detect_setups(o, h, lo, c, p, volume=v) if s.side == 1]
    assert setups, "the synthetic walk should arm a few long setups"
    from arven.engine.strategy_s7 import atr

    a_tr = atr(h, lo, c)
    sh, sl = swing_highs(h), swing_lows(lo)
    for s in setups:
        slow = _confluence(s, s.arm_index, o, h, lo, c, a_tr, p)  # default path: swings of the prefix [: t + 1]
        fast = _confluence(s, s.arm_index, o, h, lo, c, a_tr, p, sh, sl)
        assert fast == slow == s.confluence


def test_detector_is_still_causal_and_deterministic():
    o, h, lo, c, v = _walk(5000, 11)
    p = S7Params(min_touches=2)
    full = detect_setups(o, h, lo, c, p, volume=v)
    assert full == detect_setups(o, h, lo, c, p, volume=v)
    cut = 3500
    early = [s for s in full if s.arm_index < cut]
    assert detect_setups(o[:cut], h[:cut], lo[:cut], c[:cut], p, volume=v[:cut])[: len(early)] == early

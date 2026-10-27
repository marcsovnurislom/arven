"""Live config, registry and the strategy adapters' pure parts (S7 params / outcome mapping)."""

from __future__ import annotations

import pytest

from arven.backtest.paper_tracker import TrackedUpdate
from arven.backtest.strategy_s7_sim import S7Fill, S7Leg, S7Outcome
from arven.core.live_config import LiveConfig, LiveStrategyConfig, load_live_config
from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel
from arven.engine.signal_events import SignalUpdateKind
from arven.live.registry import KINDS, build_strategies, needs_features
from arven.live.strategies import natural_key, s7_outcome, s7_params


def test_repo_live_config_is_valid_and_every_kind_is_registered():
    live = load_live_config()
    assert [s.id for s in live.strategies] == ["s4_impulse_retest", "s5_squeeze_breakout", "s6_trend_pullback", "s7_trend_break_fib", "s7_smc",
                                               "s7_1h", "s7_4h", "s7_30m", "s7_1d", "s7_fit_a", "crowded_shorts"]
    assert all(s.kind in KINDS for s in live.strategies)
    # the 30m / 1d variants are the live S7 with only tf changed (YAML merge key), so the 15m strategy stays the reference
    base = dict(live.strategies[3].params)
    for sid, tf in (("s7_30m", "30m"), ("s7_1d", "1d")):
        assert dict(next(s for s in live.strategies if s.id == sid).params) == base | {"tf": tf}
    # every market added on 2026-10-27 runs gold's list unchanged
    gold = [s.id for s in live.markets[0].strategies]
    assert len(live.markets) == 12 - 1 and all([s.id for s in m.strategies] == gold for m in live.markets)
    for m in live.markets:
        build_strategies(live.for_market(m))
    strategies = build_strategies(live)
    assert [s.strategy_id for s in strategies] == [s.id for s in live.enabled()]
    assert needs_features(live)


def test_repo_s7_params_are_the_development_selection():
    s7 = next(s for s in load_live_config().strategies if s.kind == "s7")
    tf, p, tp = s7_params(s7.params)
    assert (tf, p.min_touches, p.impulse_fvg, p.freeze_pullback, p.shallow_zone, tp.entry, tp.stop, tp.management) == ("15m", 3, True, 0.382, True, "E3", "S1", "V0")


def test_config_rejects_duplicates_unknown_kinds_and_bad_params():
    with pytest.raises(ValueError):
        LiveConfig(strategies=(LiveStrategyConfig(id="a", kind="s7"), LiveStrategyConfig(id="a", kind="crowded_shorts")))
    with pytest.raises(ValueError):
        build_strategies(LiveConfig(strategies=(LiveStrategyConfig(id="a", kind="nope"),)))
    with pytest.raises(ValueError):
        s7_params({"tf": "15m", "typo_key": 1})
    with pytest.raises(ValueError):
        build_strategies(LiveConfig(strategies=(LiveStrategyConfig(id="s6", kind="s6_trend_pullback", params={"x": 1}),)))
    with pytest.raises(TypeError):
        build_strategies(LiveConfig(strategies=(LiveStrategyConfig(id="cs", kind="crowded_shorts", params={"hold": 3}),)))
    off = LiveConfig(strategies=(LiveStrategyConfig(id="cs", kind="crowded_shorts", enabled=False),))
    assert build_strategies(off) == [] and not needs_features(off)


def test_params_hash_changes_with_params_and_version():
    a = LiveStrategyConfig(id="cs", kind="crowded_shorts", params={"hold_hours": 24})
    assert a.params_hash() != LiveStrategyConfig(id="cs", kind="crowded_shorts", params={"hold_hours": 12}).params_hash()
    assert a.params_hash() != LiveStrategyConfig(id="cs", kind="crowded_shorts", version="v2", params={"hold_hours": 24}).params_hash()


def _signal(**over) -> EngineSignal:
    base = dict(symbol="BTCUSDT", side=1, strategy_id="s7_trend_break_fib", strategy_version="v1", grade=Grade.EXPERIMENTAL,
                event_time_ms=1_000_000, entry_reference=100.0, stop=98.0, tp_ladder=(TPLevel(1.0, 0.5, 102.0), TPLevel(2.0, 0.5, 104.0)),
                risk_fraction=0.01, confidence=0.5, regime="n/a", reasons=("x",), risk_checks=(),
                versions=SignalVersions("v1", "h", "c1"), entry_type="limit", valid_until_ms=9_000_000)
    return EngineSignal(**(base | over))


def test_natural_key_ignores_the_code_version():
    assert natural_key(_signal()) == natural_key(_signal(versions=SignalVersions("v1", "h", "c2")))
    assert _signal().signal_id != _signal(versions=SignalVersions("v1", "h", "c2")).signal_id


def test_s7_outcome_mapping():
    sig = _signal()
    events = (TrackedUpdate(2_000_000, SignalUpdateKind.TP_HIT, "level=TP1;fraction=0.5"), TrackedUpdate(3_000_000, SignalUpdateKind.CLOSED, "reason=STOP_TRAIL"))
    fill = S7Fill(1.0, 1_500_000, 100.0, 98.0, (102.0, 104.0), (0.5, 0.5), events, True)
    leg = S7Leg(1.0, 1_500_000, 100.0, 98.0, 0.42, 3_000_000, 2_000_000, ("TP1", "STOP_TRAIL"), (1.0, 2.0))
    done = s7_outcome(sig, S7Outcome(0, "trade", (leg,), 1_500_000, fills=(fill,)))
    assert done.state == "closed" and done.net_r == pytest.approx(0.42)
    assert [u.kind for u in done.updates] == [SignalUpdateKind.FILLED, SignalUpdateKind.TP_HIT, SignalUpdateKind.CLOSED]
    assert done.updates[0].detail == "price=100.00000000;weight=1"

    open_fill = S7Fill(1.0, 1_500_000, 100.0, 98.0, (102.0, 104.0), (0.5, 0.5), events[:1], False)
    running = s7_outcome(sig, S7Outcome(0, "unresolved", entry_time_ms=1_500_000, fills=(open_fill,)))
    assert running.state == "open" and running.net_r is None and len(running.updates) == 2

    assert s7_outcome(sig, S7Outcome(0, "end_of_data")) .state == "pending"
    cancelled = s7_outcome(sig, S7Outcome(0, "cancelled:level1_moved", status_time_ms=4_000_000))
    assert cancelled.state == "cancelled"
    assert [(u.kind, u.time_ms, u.detail) for u in cancelled.updates] == [(SignalUpdateKind.CANCELLED, 4_000_000, "reason=level1_moved")]
    assert s7_outcome(sig, S7Outcome(0, "expired", status_time_ms=9_000_000)).updates[0].detail == "reason=expired"


def test_two_legs_are_tagged():
    sig = _signal()
    f1 = S7Fill(0.5, 1_500_000, 100.0, 98.0, (102.0,), (1.0,), (), False)
    f2 = S7Fill(0.5, 1_600_000, 99.0, 98.0, (102.0,), (1.0,), (), False)
    out = s7_outcome(sig, S7Outcome(0, "unresolved", entry_time_ms=1_500_000, fills=(f1, f2)))
    assert [u.detail for u in out.updates] == ["price=100.00000000;weight=0.5;leg=1", "price=99.00000000;weight=0.5;leg=2"]


def test_s7_overlay_is_the_setup_geometry_at_bar_close_times():
    """The picture's S7 drawing (docs/FEATURES_PLAN.md H5) comes straight from the setup: the trend line from its first
    anchor to the break, the touches on the highs (long) / lows (short), fib 0 / 0.5 / 1 and the entry zone from fib 1 on."""
    from types import SimpleNamespace

    import numpy as np

    from arven.core.live_config import LiveStrategyConfig
    from arven.core.timeframes import Timeframe
    from arven.live.strategies import S7Strategy

    s7 = next(s for s in load_live_config().strategies if s.kind == "s7")
    strat = S7Strategy(LiveStrategyConfig(id="s7x", kind="s7", params=s7.params))
    t0, m15 = 1_782_864_000_000, 15 * 60_000
    n = 40
    bars = SimpleNamespace(open_time_ms=t0 + np.arange(n) * m15, high=100.0 + np.arange(n), low=50.0 + np.arange(n))
    for side, touch_prices in ((1, bars.high), (-1, bars.low)):
        line = SimpleNamespace(a_index=5, a_price=120.0, at=lambda i: 120.0 - 0.5 * (i - 5))
        fibs = {0.0: 90.0, 0.5: 95.0, 1.0: 100.0}
        setup = SimpleNamespace(side=side, line=line, cross_index=20, touches=(5, 11, 17), fib=fibs.__getitem__,
                                zone_low=94.0, zone_high=96.0, level0_index=8, level1_index=24)
        sig = _signal(side=side, entry_reference=95.0, stop=90.0 if side == 1 else 101.0,
                      tp_ladder=(TPLevel(1.0, 1.0, 100.0 if side == 1 else 89.0),))
        ctx = SimpleNamespace(bars={Timeframe.M15: bars}, cache={f"s7:{strat.strategy_id}": {"by_key": {natural_key(sig): setup}}})
        ov = strat.overlay(ctx, sig)
        close = lambda i: t0 + (i + 1) * m15  # noqa: E731
        assert ov.lines == ((close(5), 120.0, close(20), 112.5, "trend line"),)
        assert ov.points == tuple((close(i), float(touch_prices[i])) for i in (5, 11, 17))
        assert ov.levels == ((90.0, "fib 0"), (95.0, "fib 0.5"), (100.0, "fib 1"))
        assert ov.zone == (94.0, 96.0, "entry zone") and ov.zone_from_ms == close(24) and ov.start_ms == close(5)
    other = _signal(event_time_ms=1)
    assert strat.overlay(ctx, other) is None  # a signal whose setup is not in this tick's data


def test_s7_smc_is_the_frozen_pre_registered_rule_on_every_market():
    """s7_smc = the live S7 with exactly two changes - no FVG impulse and at least two different SMC zone types - the
    rule of scripts/research/s7_smc_btc.py (committed 8be9268 before its one BTC run). Any other change needs a new id."""
    live = load_live_config()
    for strategies in (live.strategies, *(m.strategies for m in live.markets)):
        by_id = {s.id: s for s in strategies}
        base, smc = dict(by_id["s7_trend_break_fib"].params), dict(by_id["s7_smc"].params)
        assert smc.pop("min_smc_types") == 2 and smc.pop("impulse") == "none" and base.pop("impulse") == "fvg"
        assert smc == base and by_id["s7_smc"].version == "v1" and by_id["s7_smc"].enabled


def test_smc_types_counts_distinct_smc_zones_but_not_levels():
    from types import SimpleNamespace

    from arven.live.strategies import smc_types

    z = lambda k: SimpleNamespace(kind=k)  # noqa: E731
    assert smc_types(SimpleNamespace(confluence=(z("level"), z("level")))) == 0
    assert smc_types(SimpleNamespace(confluence=(z("fvg"), z("fvg"), z("level")))) == 1
    assert smc_types(SimpleNamespace(confluence=(z("fvg"), z("ifvg"), z("level")))) == 2
    assert smc_types(SimpleNamespace(confluence=(z("fvg"), z("ifvg"), z("order_block")))) == 3


def test_min_smc_types_is_validated():
    s7 = dict(next(s for s in load_live_config().strategies if s.kind == "s7").params)
    s7_params(s7 | {"min_smc_types": 2})
    for bad in (4, -1, "2"):
        with pytest.raises(ValueError, match="min_smc_types"):
            s7_params(s7 | {"min_smc_types": bad})


def test_s7_runs_on_30m_and_1d_with_a_finer_lower_and_a_coarser_higher_frame():
    """2026-10-27: S7 on 30m (lower 5m, higher 4h) and 1d (lower 4h, no higher); every lower frame divides its frame and
    every higher frame is a multiple of it, as for 15m / 1h / 4h."""
    from arven.live.strategies import S7_HIGHER, S7_LOWER, S7_TFS

    base = dict(next(s for s in load_live_config().strategies if s.id == "s7_trend_break_fib").params)
    for tf in ("15m", "30m", "1h", "4h", "1d"):
        assert s7_params(base | {"tf": tf})[0] == tf
        main, lower, higher = S7_TFS[tf], S7_LOWER[tf], S7_HIGHER[tf]
        assert main.ms % lower.ms == 0 and main.ms > lower.ms
        assert higher is None or (higher.ms % main.ms == 0 and higher.ms > main.ms)
    with pytest.raises(ValueError):
        s7_params(base | {"tf": "1m"})  # no S7 on 1m: costs vs the 1m bar range (docs/ANALIZ_VSEH_STRATEGIY.md)


def test_s7_detection_on_the_warmup_tail_finds_exactly_the_full_history_setups():
    """The live S7 gives its detector only S7_WARMUP_BARS bars before the forward window (2026-10-27, speed): on a long
    random walk the setups armed after the cut are identical to those found on the whole history."""
    import numpy as np

    from arven.engine.strategy_s7 import detect_setups
    from arven.live.strategies import S7_WARMUP_BARS

    rng = np.random.default_rng(3)
    n = S7_WARMUP_BARS + 6000
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n)))
    vol = rng.uniform(1, 3, n)
    _, p, _ = s7_params(dict(next(s for s in load_live_config().strategies if s.id == "s7_smc").params))
    fwd = n - 3000  # the "forward window" starts here
    i0 = fwd - S7_WARMUP_BARS
    key = lambda s, off: (s.arm_index + off, s.side, s.level0, s.level1, s.zone_low, s.zone_high)  # noqa: E731
    full = [key(s, 0) for s in detect_setups(open_, high, low, close, p, volume=vol) if s.arm_index >= fwd]
    tail = [key(s, i0) for s in detect_setups(open_[i0:], high[i0:], low[i0:], close[i0:], p, volume=vol[i0:]) if s.arm_index + i0 >= fwd]
    assert full and tail == full


def test_s7_fit_a_is_configured_as_fitted_and_rejects_missing_fit_params():
    """S7-Fit A (2026-10-28): 1h S7 setups, E1 entry, 4h-trend and ADX filters, stop 1.5 ATR, one target 0.9 ATR, 3 days
    at most - on BTC and on every further market (gold's list)."""
    from arven.live.strategies import S7FitStrategy

    live = load_live_config()
    cfg = next(s for s in live.strategies if s.id == "s7_fit_a")
    st = S7FitStrategy(cfg)
    assert (st.tf, st.stop_atr, st.tp_atr, st.hold, st.trend_ema, st.adx_min) == ("1h", 1.5, 0.9, 4320, 50, 25.0)
    assert not st.p.impulse_fvg and st.tp.entry == "E1"
    assert all(any(s.id == "s7_fit_a" for s in m.strategies) for m in live.markets)
    with pytest.raises(ValueError):
        S7FitStrategy(LiveStrategyConfig(id="x", kind="s7_fit", params={"tf": "1h", "stop_atr": 1.5}))

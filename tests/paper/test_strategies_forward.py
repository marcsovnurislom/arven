"""Pure core of the forward S4/S5/S6 evaluation (arven.paper.strategies_forward): event times, event processing,
outcome resolution on 1m bars, and the agreement split. I/O composition (REST, DB, Telegram) is exercised on real data."""

from __future__ import annotations

import numpy as np
import pytest

from arven.backtest.marketdata import MarketData
from arven.backtest.strategy_s6_provider import TrendPullbackProvider
from arven.core.config import CostsConfig
from arven.core.series import BarSeries
from arven.core.timeframes import Timeframe
from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, tp_ladder_from_r_multiples
from arven.paper.strategies_forward import (
    MIN15,
    SignalOutcome,
    agreement_summary,
    event_times,
    process_events,
    resolve_signal,
    strategy_summary,
)

HOUR = 3_600_000
J = 5400
N_SETUP, N_CTX, N_TRIG = 1410, 412, 5640

ZERO_COSTS = CostsConfig.model_validate({
    "fees": {"maker_fee_bps": 0.0, "taker_fee_bps": 0.0, "entry_order_type": "taker", "exit_order_type": "taker", "stop_order_type": "taker"},
    "slippage": {"model": "fixed_plus_volatility", "fixed_bps": 0.0, "volatility_multiplier": 0.0, "stress_multiplier": 1.0},
    "funding": {"source": "historical", "missing_policy": "error", "assumed_rate_bps": 0.0, "default_interval_hours": 8},
})


def _series(tf: Timeframe, n: int, price: np.ndarray, half_range: float) -> BarSeries:
    t = np.arange(n) * tf.ms
    ones = np.ones(n)
    return BarSeries(tf, 0, t, price.copy(), price + half_range, price - half_range, price.copy(), ones, ones, ones, np.ones(n, dtype=bool))


def s6_provider() -> tuple[TrendPullbackProvider, int]:
    p1h = np.full(N_SETUP, 100.0)
    p1h[1347:1350] = 100.4
    p15 = np.full(N_TRIG, 100.0)
    p15[J] = 100.5
    context = _series(Timeframe.H4, N_CTX, 100.0 + np.arange(N_CTX) * 0.05, 0.01)
    return TrendPullbackProvider(_series(Timeframe.H1, N_SETUP, p1h, 0.5), _series(Timeframe.M15, N_TRIG, p15, 0.01), context), (J + 1) * MIN15


def test_event_times_are_the_15m_closes_strictly_after_the_cursor():
    assert list(event_times(0, 3 * MIN15)) == [MIN15, 2 * MIN15, 3 * MIN15]
    assert list(event_times(MIN15, 3 * MIN15)) == [2 * MIN15, 3 * MIN15]
    assert list(event_times(MIN15 + 5, 2 * MIN15)) == [2 * MIN15]
    assert list(event_times(3 * MIN15, 3 * MIN15)) == []


def test_process_events_finds_the_signal_once_and_resuming_from_the_cursor_does_not_repeat_it():
    provider, now_ms = s6_provider()
    kw = dict(feature_version="v1", config_hash="h", commit=None)
    first = process_events(provider, list(event_times(now_ms - 5 * MIN15 - 1, now_ms)), **kw)
    assert [s.event_time_ms for s in first] == [now_ms] and first[0].strategy_id == "s6_trend_pullback" and first[0].side == 1
    resumed, _ = s6_provider()
    assert process_events(resumed, list(event_times(now_ms, now_ms + 3 * MIN15)), **kw) == []  # nothing after the cursor


def test_s6_cooldown_restored_from_stored_signals_blocks_a_repeat():
    provider, now_ms = s6_provider()
    provider._last_signal_ms = now_ms - 2 * HOUR  # as restored from the signal store after a restart
    assert process_events(provider, [now_ms], feature_version="v1", config_hash="h", commit=None) == []


def _signal(strategy_id: str, side: int, t: int, entry: float = 100.0, stop: float | None = None) -> EngineSignal:
    stop = stop if stop is not None else (99.0 if side == 1 else 101.0)
    ladder = tp_ladder_from_r_multiples(((1.0, 0.5), (2.0, 0.5)), entry=entry, stop=stop, side=side)
    return EngineSignal(
        symbol="BTCUSDT", side=side, strategy_id=strategy_id, strategy_version="v1", grade=Grade.EXPERIMENTAL, event_time_ms=t,
        entry_reference=entry, stop=stop, tp_ladder=ladder, risk_fraction=0.01, confidence=0.5, regime="x", reasons=("x",), risk_checks=(),
        versions=SignalVersions("v1", "h", None),
    )


def _market(prices: list[tuple[float, float, float, float]], start_ms: int = 0) -> MarketData:
    n = len(prices)
    t = start_ms + np.arange(n) * 60_000
    o, h, lo, c = (np.array(col, dtype=float) for col in zip(*prices, strict=True))
    return MarketData(t, o, h, lo, c, int(t[0]), int(t[-1]) + 60_000, np.array([], dtype=np.int64), np.array([]), 8 * HOUR)


def test_resolve_signal_ladder_hand_computed_and_open_signal_has_no_result_yet():
    # long 100, stop 99 (1R). minute 1 reaches 101 (TP1 closes 50 %), minute 2 reaches 102 (TP2 closes the rest): 0.5*1 + 0.5*2 = 1.5 R
    market = _market([(100, 100, 100, 100), (100, 101.2, 100, 101), (101, 102.2, 101, 102), (102, 102, 102, 102)])
    out = resolve_signal(_signal("s6_trend_pullback", 1, 0), market, ZERO_COSTS)
    assert out is not None and out.closed and out.net_r == pytest.approx(1.5)
    assert [u.kind.value for u in out.updates] == ["TP_HIT", "TP_HIT"]
    open_market = _market([(100, 100, 100, 100), (100, 100.5, 99.5, 100)])
    still_open = resolve_signal(_signal("s6_trend_pullback", 1, 0), open_market, ZERO_COSTS)
    assert still_open is not None and not still_open.closed and still_open.net_r is None and still_open.updates == ()


def test_resolve_signal_stop_and_missing_bar():
    market = _market([(100, 100, 100, 100), (100, 100, 98.5, 99)])
    out = resolve_signal(_signal("s6_trend_pullback", 1, 0), market, ZERO_COSTS)
    assert out is not None and out.closed and out.net_r == pytest.approx(-1.0)
    assert resolve_signal(_signal("s6_trend_pullback", 1, 10 * 60_000), market, ZERO_COSTS) is None  # that minute is not in the data


def _closed(sid: str, side: int, t: int, r: float) -> SignalOutcome:
    return SignalOutcome(_signal(sid, side, t), True, r, ())


def test_agreement_summary_splits_by_another_strategy_on_the_same_side_within_four_hours():
    outcomes = [
        _closed("s4_impulse_retest", 1, 0, 2.0),
        _closed("s6_trend_pullback", 1, 2 * HOUR, 1.0),  # agrees with s4 (same side, 2 h apart)
        _closed("s5_squeeze_breakout", -1, 3 * HOUR, -1.0),  # opposite side: not agreement
        _closed("s6_trend_pullback", 1, 20 * HOUR, -1.0),  # alone
    ]
    s = agreement_summary(outcomes)
    assert s["agreed_by_another_strategy"]["n"] == 2 and s["agreed_by_another_strategy"]["mean_r"] == pytest.approx(1.5)
    assert s["alone"]["n"] == 2 and s["alone"]["mean_r"] == pytest.approx(-1.0)


def test_strategy_summary_counts():
    outs = [_closed("s6_trend_pullback", 1, 0, 2.0), _closed("s6_trend_pullback", 1, HOUR, -1.0), SignalOutcome(_signal("s6_trend_pullback", 1, 2 * HOUR), False, None, ())]
    s = strategy_summary(outs, weeks=1.0)
    assert (s["signals"], s["closed"], s["open"]) == (3, 2, 1)
    assert s["total_r"] == pytest.approx(1.0) and s["win_rate"] == pytest.approx(0.5) and s["signals_per_week"] == pytest.approx(3.0)

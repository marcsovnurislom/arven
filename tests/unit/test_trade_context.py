"""Learning from mistakes (arven.trade_context): circumstances known at the entry only, labels by hand, and a report
that flags a circumstance only with enough trades and a corrected interval - never noise."""

from __future__ import annotations

from datetime import datetime

import numpy as np

from arven.core.macro_config import MacroEvent
from arven.core.time import UTC, to_ms
from arven.trade_context import HOUR_MS, MIN_TRADES, TfBars, context_at, report

T0 = to_ms(datetime(2024, 1, 1, tzinfo=UTC))


def bars(n: int, tf_ms: int, step: float = 0.001, seed: int | None = None) -> TfBars:
    t = T0 + tf_ms * np.arange(n, dtype=np.int64)
    if seed is None:
        c = 100.0 * (1 + step) ** np.arange(n)
    else:
        c = 100.0 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0, 0.004, n)))
    return TfBars(tf_ms, t, c * 1.002, c * 0.998, c)


def truncate(b: TfBars, t_ms: int) -> TfBars:
    k = b.closed_by(t_ms)
    return TfBars(b.tf_ms, b.open_time_ms[:k], b.high[:k], b.low[:k], b.close[:k])


def test_a_long_in_a_steady_rise_is_with_both_trends_and_a_short_against():
    h1, h4 = bars(2000, HOUR_MS), bars(500, 4 * HOUR_MS)
    t = int(h1.open_time_ms[1500]) + HOUR_MS
    long = context_at(t, 1, 100.0, 99.0, h1, h4, [])
    short = context_at(t, -1, 100.0, 101.0, h1, h4, [])
    assert long["trend_1h"] == long["trend_4h"] == "with the trade"
    assert short["trend_1h"] == short["trend_4h"] == "against the trade"
    assert long["move_24h"].startswith("chasing") and short["move_24h"].startswith("after a drop")
    assert context_at(int(h1.open_time_ms[10]), 1, 1.0, 0.9, h1, h4, [])["volatility"] == "unknown"  # too little history


def test_the_circumstances_use_only_bars_closed_by_the_entry():
    h1, h4 = bars(3000, HOUR_MS, seed=1), bars(800, 4 * HOUR_MS, seed=2)
    for k in (900, 1777, 2500):
        t = int(h1.open_time_ms[k]) + HOUR_MS // 2  # inside a forming bar
        full = context_at(t, 1, float(h1.close[k - 1]), float(h1.close[k - 1]) * 0.99, h1, h4, [])
        cut = context_at(t, 1, float(h1.close[k - 1]), float(h1.close[k - 1]) * 0.99, truncate(h1, t), truncate(h4, t), [])
        assert full == cut


def test_session_weekday_and_news_labels():
    t = to_ms(datetime(2024, 3, 20, 17, 0, tzinfo=UTC))  # a Wednesday, US hours; FOMC at 18:00
    h1, h4 = bars(10, HOUR_MS), bars(10, 4 * HOUR_MS)
    c = context_at(t, 1, 1.0, 0.9, h1, h4, [MacroEvent(t + HOUR_MS, "FOMC", "")])
    assert c["session"] == "13-21 US" and c["weekday"] == "Wed" and c["news"] == "within 2 h before a release"
    assert context_at(t, 1, 1.0, 0.9, h1, h4, [MacroEvent(t - HOUR_MS, "CPI", "")])["news"] == "within 2 h after a release"
    assert context_at(t, 1, 1.0, 0.9, h1, h4, [MacroEvent(t + 3 * HOUR_MS, "NFP", "")])["news"] == "no release near"


def rows(spec):
    """spec: list of (weekday, n, net_r values generator)."""
    out = []
    for day, values in spec:
        for v in values:
            out.append({"net_r": v, "weekday": day})
    return out


def test_a_clearly_losing_circumstance_is_flagged_and_a_small_one_is_not():
    rng = np.random.default_rng(3)
    data = rows([("Mon", rng.normal(-0.8, 0.5, 60)), ("Tue", rng.normal(0.3, 0.5, 80)), ("Wed", rng.normal(-2.0, 0.1, 10))])
    rep = report(data, features=("weekday",))
    cells = rep["features"]["weekday"]
    assert cells["Mon"]["flag"] == "worse" and cells["Tue"]["flag"] == "better"
    assert cells["Wed"]["trades"] < MIN_TRADES and cells["Wed"]["flag"] is None and cells["Wed"]["diff_low"] is None
    assert rep["tested"] == 2 and rep["level"] == 0.025


def test_noise_is_not_flagged():
    rng = np.random.default_rng(11)
    days = ("Mon", "Tue", "Wed", "Thu", "Fri")
    data = rows([(d, rng.normal(0.0, 1.0, 60)) for d in days])
    cells = report(data, features=("weekday",))["features"]["weekday"]
    assert all(c["flag"] is None for c in cells.values())
    assert report(data, features=("weekday",)) == report(data, features=("weekday",))  # seeded: the same every time

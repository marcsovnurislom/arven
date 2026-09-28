"""Development / validation / sealed-test boundaries and the read-only loaders that honour them."""

import json

import numpy as np
import pytest

from arven.core.config import load_config
from arven.core.splitguard import (
    AllowedWindow,
    BacktestPeriod,
    SealedAccessError,
    SplitGuard,
    SplitViolation,
)
from arven.core.time import to_ms, to_utc_datetime
from arven.data.reader import load_1m_bars, load_funding_window
from arven.data.storage.db import connect
from bt_helpers import bulk_insert_1m, bulk_insert_funding

APP = load_config()
HOUR = 3_600_000
DEV_START, DEV_END = to_ms(APP.splits.development.start), to_ms(APP.splits.development.end)
VAL_START, VAL_END = to_ms(APP.splits.validation.start), to_ms(APP.splits.validation.end)
TEST_START, TEST_END = to_ms(APP.splits.test.start), to_ms(APP.splits.test.end)


def guard(tmp_path, with_log=True):
    return SplitGuard(APP.splits, tmp_path / "sealed.jsonl" if with_log else None)


def test_default_windows_are_the_configured_periods(tmp_path):
    g = guard(tmp_path)
    w = g.resolve(BacktestPeriod.DEVELOPMENT)
    assert (w.start_ms, w.end_ms, w.sealed) == (DEV_START, DEV_END, False)
    v = g.resolve(BacktestPeriod.VALIDATION)
    assert (v.start_ms, v.end_ms) == (VAL_START, VAL_END) and not v.sealed
    assert DEV_END == VAL_START  # contiguous, so a development run can never need validation data


def test_sub_ranges_inside_a_period_are_allowed(tmp_path):
    w = guard(tmp_path).resolve(BacktestPeriod.DEVELOPMENT, DEV_START + 24 * HOUR, DEV_START + 48 * HOUR)
    assert w.n_hours == 24


@pytest.mark.parametrize(
    "period,start,end",
    [
        (BacktestPeriod.DEVELOPMENT, DEV_START, DEV_END + HOUR),  # runs one hour into validation
        (BacktestPeriod.DEVELOPMENT, DEV_START - HOUR, DEV_END),
        (BacktestPeriod.VALIDATION, VAL_START - HOUR, VAL_END),
        (BacktestPeriod.VALIDATION, VAL_START, TEST_START + HOUR),  # would leak into the sealed period
        (BacktestPeriod.DEVELOPMENT, DEV_START + HOUR, DEV_START + HOUR),  # empty
        (BacktestPeriod.DEVELOPMENT, DEV_START + 1, DEV_START + 2 * HOUR),  # not whole hours
    ],
)
def test_ranges_crossing_boundaries_or_malformed_are_refused(tmp_path, period, start, end):
    with pytest.raises(SplitViolation):
        guard(tmp_path).resolve(period, start, end)
    assert not (tmp_path / "sealed.jsonl").exists()  # nothing logged for refused non-sealed requests


def test_sealed_period_needs_acknowledgement_and_reason(tmp_path):
    g = guard(tmp_path)
    with pytest.raises(SealedAccessError):
        g.resolve(BacktestPeriod.TEST)
    with pytest.raises(SealedAccessError):
        g.resolve(BacktestPeriod.TEST, allow_sealed=True)
    with pytest.raises(SealedAccessError):
        g.resolve(BacktestPeriod.TEST, allow_sealed=True, reason="   ")
    assert not (tmp_path / "sealed.jsonl").exists()


def test_sealed_access_is_logged_before_the_window_is_returned(tmp_path):
    g = guard(tmp_path)
    w = g.resolve(BacktestPeriod.TEST, allow_sealed=True, reason="final evaluation of frozen configuration X", context={"provider": "no_trade"})
    assert w.sealed and w.sealed_reason == "final evaluation of frozen configuration X"
    g.resolve(BacktestPeriod.TEST, TEST_START, TEST_START + 24 * HOUR, allow_sealed=True, reason="second look")
    lines = [json.loads(x) for x in (tmp_path / "sealed.jsonl").read_text().splitlines()]
    assert len(lines) == 2 and lines[0]["reason"].startswith("final") and lines[0]["provider"] == "no_trade"
    assert lines[0]["window_start_ms"] == TEST_START and lines[0]["window_end_ms"] == TEST_END and lines[1]["window_end_ms"] == TEST_START + 24 * HOUR
    assert "accessed_at" in lines[0]


def test_sealed_access_without_a_configured_log_is_refused(tmp_path):
    with pytest.raises(SealedAccessError, match="log"):
        guard(tmp_path, with_log=False).resolve(BacktestPeriod.TEST, allow_sealed=True, reason="x")


def test_allowed_window_cannot_be_forged():
    with pytest.raises(SplitViolation):
        AllowedWindow(BacktestPeriod.TEST, TEST_START, TEST_END, False)
    with pytest.raises(SplitViolation):
        AllowedWindow(BacktestPeriod.DEVELOPMENT, DEV_START, DEV_END + HOUR, False, _token=object())


def test_assert_inside(tmp_path):
    w = guard(tmp_path).resolve(BacktestPeriod.DEVELOPMENT, DEV_START, DEV_START + HOUR)
    w.assert_inside(DEV_START, DEV_START + HOUR - 1, "x")
    with pytest.raises(SplitViolation):
        w.assert_inside(DEV_START, DEV_START + HOUR, "x")


# --- loaders only ever read the window ------------------------------------------------------------


def fill_db(con):
    """1m rows and funding rows spanning the development / validation / test boundaries."""
    bar_rows, fund_rows = [], []
    for boundary in (DEV_END, TEST_START):
        for k in range(-3, 3):
            t = boundary + k * 60_000
            bar_rows.append(("BTCUSDT", t, t + 60_000, 1, 2, 0.5, 1.5, 1, 1, 1, 0.5, 0.5, "x", 0))
    for k in range(-2, 3):
        t = DEV_END + k * 8 * HOUR
        fund_rows.append(("BTCUSDT", t, t, 0.0001, 8, t, "x", 0))
    # the first hour of the development period, so the window has rows
    for k in range(3):
        t = DEV_START + k * 60_000
        bar_rows.append(("BTCUSDT", t, t + 60_000, 1, 2, 0.5, 1.5, 1, 1, 1, 0.5, 0.5, "x", 0))
    bulk_insert_1m(con, bar_rows)
    bulk_insert_funding(con, fund_rows)


def test_loaders_return_only_rows_inside_the_window_and_log_the_ranges(tmp_path):
    con = connect(":memory:")
    fill_db(con)
    log: list = []
    dev = guard(tmp_path).resolve(BacktestPeriod.DEVELOPMENT)
    bars = load_1m_bars(con, "BTCUSDT", dev, log)
    assert bars["time_ms"].max() == DEV_END - 60_000 and bars["time_ms"].min() == DEV_START
    assert len(bars["time_ms"]) == 3 + 3  # 3 at the start, 3 just before the end; nothing at/after DEV_END
    t, r = load_funding_window(con, "BTCUSDT", dev, log)
    assert t.max() < DEV_END and len(t) == 2
    assert log == [
        {"dataset": "ohlcv_1m", "start_ms": DEV_START, "end_ms": DEV_END},
        {"dataset": "funding_rates", "start_ms": DEV_START, "end_ms": DEV_END},
    ]
    assert max(x["end_ms"] for x in log) <= DEV_END  # nothing from validation or test was requested

    val = guard(tmp_path).resolve(BacktestPeriod.VALIDATION)
    vbars = load_1m_bars(con, "BTCUSDT", val)
    assert vbars["time_ms"].min() == DEV_END and vbars["time_ms"].max() < TEST_START
    assert not np.isin(vbars["time_ms"], bars["time_ms"]).any()


def test_a_forward_period_does_not_exist_as_a_backtest_period():
    assert {p.value for p in BacktestPeriod} == {"development", "validation", "test"}
    assert to_ms(to_utc_datetime(APP.splits.forward_start)) == TEST_END

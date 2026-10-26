import functools
import operator
from datetime import datetime

import pytest

from arven.core.time import UTC, to_ms
from arven.core.timeframes import Timeframe
from arven.data.resample import resample
from arven.data.storage.db import connect

T0 = datetime(2024, 1, 1, tzinfo=UTC)
T0_MS = to_ms(T0)
MIN = 60_000


@pytest.fixture
def con():
    c = connect(":memory:")
    yield c
    c.close()


def insert_1m(con, minutes, price=lambda i: 100.0 + i, volume=lambda i: 0.1):
    for i in minutes:
        p = price(i)
        con.execute(
            "INSERT INTO ohlcv_1m VALUES ('BTCUSDT', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'test', 0)",
            [T0_MS + i * MIN, T0_MS + (i + 1) * MIN, p, p + 5, p - 5, p + 1, volume(i), volume(i) * p, 10,
             volume(i) / 2, volume(i) * p / 2],
        )


def bars(con, tf):
    return con.execute(
        "SELECT open_time_ms, close_time_ms, open, high, low, close, volume, trade_count, bar_count, is_complete "
        "FROM ohlcv WHERE timeframe = ? ORDER BY open_time_ms", [tf.value]
    ).fetchall()


def test_5m_aggregation_values(con):
    insert_1m(con, range(10))
    resample(con, "BTCUSDT", T0, datetime(2024, 1, 1, 0, 10, tzinfo=UTC), (Timeframe.M5,))
    b = bars(con, Timeframe.M5)
    assert len(b) == 2
    open_ms, close_ms, o, h, lo, c, v, trades, n, complete = b[0]
    assert (open_ms, close_ms) == (T0_MS, T0_MS + 5 * MIN)
    assert o == 100.0          # first 1m open
    assert c == 105.0          # last 1m close (104 + 1)
    assert h == 109.0          # max high (104 + 5)
    assert lo == 95.0          # min low (100 - 5)
    assert v == 0.5            # exact decimal sum of 5 x 0.1
    assert trades == 50 and n == 5 and complete is True


def test_decimal_sum_is_exact_where_float_sum_is_not(con):
    insert_1m(con, range(60), volume=lambda i: 0.1)
    resample(con, "BTCUSDT", T0, datetime(2024, 1, 1, 1, tzinfo=UTC), (Timeframe.H1,))
    assert functools.reduce(operator.add, [0.1] * 60) != 6.0  # naive float accumulation drifts
    assert bars(con, Timeframe.H1)[0][6] == 6.0


def test_missing_minute_marks_bar_incomplete(con):
    insert_1m(con, [0, 1, 2, 4])  # minute 3 missing
    resample(con, "BTCUSDT", T0, datetime(2024, 1, 1, 0, 5, tzinfo=UTC), (Timeframe.M5,))
    (_, _, _, _, _, close, _, _, n, complete), = bars(con, Timeframe.M5)
    assert n == 4 and complete is False
    assert close == 105.0  # still the last available minute's close


def test_empty_bucket_is_absent_not_fabricated(con):
    insert_1m(con, list(range(5)) + list(range(10, 15)))  # 00:05-00:10 has no data
    resample(con, "BTCUSDT", T0, datetime(2024, 1, 1, 0, 15, tzinfo=UTC), (Timeframe.M5,))
    assert [b[0] for b in bars(con, Timeframe.M5)] == [T0_MS, T0_MS + 10 * MIN]


def test_4h_buckets_align_to_utc_midnight(con):
    insert_1m(con, range(0, 8 * 60, 7))
    resample(con, "BTCUSDT", T0, datetime(2024, 1, 1, 8, tzinfo=UTC), (Timeframe.H4,))
    assert [b[0] for b in bars(con, Timeframe.H4)] == [T0_MS, T0_MS + 4 * 60 * MIN]


def test_resample_is_idempotent_and_reflects_corrected_1m(con):
    insert_1m(con, range(15))
    end = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
    resample(con, "BTCUSDT", T0, end, (Timeframe.M5, Timeframe.M15))
    first = bars(con, Timeframe.M5) + bars(con, Timeframe.M15)
    resample(con, "BTCUSDT", T0, end, (Timeframe.M5, Timeframe.M15))
    assert bars(con, Timeframe.M5) + bars(con, Timeframe.M15) == first
    assert con.execute("SELECT count(*) FROM ohlcv").fetchone()[0] == 4

    con.execute("DELETE FROM ohlcv_1m WHERE open_time_ms >= ?", [T0_MS + 10 * MIN])
    resample(con, "BTCUSDT", T0, end, (Timeframe.M5,))
    assert len(bars(con, Timeframe.M5)) == 2  # stale 00:10 bar removed


def test_resample_rejects_1m(con):
    with pytest.raises(ValueError):
        resample(con, "BTCUSDT", T0, datetime(2024, 1, 2, tzinfo=UTC), (Timeframe.M1,))


def test_30m_and_1d_bars_added_2026_10_27(con):
    """30m buckets on the half hour, 1d buckets at 00:00 UTC; a day with every minute is complete, a partial one is not."""
    insert_1m(con, range(1440 + 60))  # one full day and the first hour of the next
    resample(con, "BTCUSDT", T0, datetime(2024, 1, 2, 1, 0, tzinfo=UTC), (Timeframe.M30, Timeframe.D1))
    m30 = bars(con, Timeframe.M30)
    assert len(m30) == 48 + 2 and m30[1][0] == T0_MS + 30 * MIN and m30[0][1] == T0_MS + 30 * MIN
    assert m30[0][2] == 100.0 and m30[0][5] == 100.0 + 29 + 1 and m30[0][8] == 30 and m30[0][9]
    d1 = bars(con, Timeframe.D1)
    assert [(b[0], b[8], b[9]) for b in d1] == [(T0_MS, 1440, True), (T0_MS + 1440 * MIN, 60, False)]
    assert d1[0][3] == 100.0 + 1439 + 5 and d1[0][4] == 100.0 - 5  # high / low over the whole day
    assert Timeframe.D1.ms == 86_400_000 and Timeframe.M30.ms == 1_800_000

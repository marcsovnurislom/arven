"""arven.live.refresh: every market's new closed minutes fetched in parallel, written in one connection, derived bars
rebuilt; the forming minute is never fetched; a failing market is reported, not raised - offline (fake opener)."""

from __future__ import annotations

from datetime import UTC, datetime

from bt_helpers import bulk_insert_1m
from rest_helpers import FakeBinanceRestOpener

from arven.core.time import from_ms
from arven.data.download import Downloader, RetryPolicy
from arven.data.storage.db import connect
from arven.live.refresh import refresh_markets

MIN = 60_000
T0 = int(datetime(2026, 1, 5, tzinfo=UTC).timestamp() * 1000)  # a Monday 00:00 UTC


def test_refresh_appends_new_closed_minutes_and_rebuilds_derived_bars(make_config):
    cfg = make_config(default__download__rest_base_url="http://fake")
    con = connect(cfg.data.database_path)
    bulk_insert_1m(con, [("BTCUSDT", T0 + k * MIN, T0 + (k + 1) * MIN, 100, 101, 99, 100.5, 1.0, 100.0, 10, 0.5, 50.0, "bulk/x", 0) for k in range(3)])
    con.close()
    opener = FakeBinanceRestOpener([T0 + k * MIN for k in range(12)], [])
    dl = Downloader(RetryPolicy.from_config(cfg.download), opener=opener, sleep=lambda s: None)
    now = from_ms(T0 + 10 * MIN + 30_000)  # 00:10:30 - the 00:10 minute is still forming
    assert refresh_markets([("BTC", cfg)], cfg.data.database_path, now, dl) == {}
    con = connect(cfg.data.database_path)
    opens = [r[0] for r in con.execute("SELECT open_time_ms FROM ohlcv_1m ORDER BY 1").fetchall()]
    assert opens == [T0 + k * MIN for k in range(10)]  # 00:00 ... 00:09, nothing forming
    assert "startTime=" + str(T0 + 3 * MIN) in opener.calls[0]  # resumes right after the stored minute
    m5 = con.execute("SELECT open_time_ms, bar_count, is_complete FROM ohlcv WHERE timeframe = '5m' ORDER BY 1").fetchall()
    assert m5 == [(T0, 5, True), (T0 + 5 * MIN, 5, True)]
    con.close()
    assert refresh_markets([("BTC", cfg)], cfg.data.database_path, now, dl) == {}  # nothing new: nothing written


def test_a_failing_market_is_reported_and_the_others_still_update(make_config):
    cfg = make_config(default__download__rest_base_url="http://fake")
    con = connect(cfg.data.database_path)
    bulk_insert_1m(con, [("BTCUSDT", T0, T0 + MIN, 100, 101, 99, 100.5, 1.0, 100.0, 10, 0.5, 50.0, "bulk/x", 0)])
    con.close()
    fx = cfg.model_copy(update={"market": cfg.market.model_copy(update={"symbol": "USDJPY", "exchange": "dukascopy", "session": "fx"})})
    opener = FakeBinanceRestOpener([T0 + k * MIN for k in range(4)], [])
    dl = Downloader(RetryPolicy.from_config(cfg.download), opener=opener, sleep=lambda s: None)
    errors = refresh_markets([("BTC", cfg), ("JPY", fx)], cfg.data.database_path, from_ms(T0 + 4 * MIN), dl)
    assert list(errors) == ["JPY"] and "no live pair" in errors["JPY"]
    con = connect(cfg.data.database_path)
    assert con.execute("SELECT count(*) FROM ohlcv_1m WHERE symbol = 'BTCUSDT'").fetchone()[0] == 4
    con.close()

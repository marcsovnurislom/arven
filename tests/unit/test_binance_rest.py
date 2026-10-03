"""binance_rest: REST response parsing and range filtering, offline (fake opener, no sockets)."""

from __future__ import annotations

import random

from rest_helpers import FakeBinanceRestOpener

from arven.data.adapters.binance_rest import fetch_funding_rate, fetch_klines
from arven.data.download import Downloader, RetryPolicy

POLICY = RetryPolicy(max_attempts=2, timeout_seconds=5, backoff_initial_seconds=0.0, backoff_multiplier=1.0, backoff_max_seconds=0.0)
HOUR = 3_600_000
MIN = 60_000


def make(opener) -> Downloader:
    return Downloader(POLICY, opener=opener, sleep=lambda s: None, rng=random.Random(0))


def test_fetch_klines_parses_fields_in_order():
    opener = FakeBinanceRestOpener(kline_opens=[0, MIN, 2 * MIN], funding_times=[])
    rows = fetch_klines(make(opener), "http://x", "BTCUSDT", "1m", 0, 3 * MIN)
    assert [r.open_time_ms for r in rows] == [0, MIN, 2 * MIN]
    assert rows[0].close_time_ms == MIN - 1
    assert rows[0].open == 100.0 and rows[0].trade_count == 42


def test_fetch_klines_excludes_rows_at_or_after_end_ms():
    opener = FakeBinanceRestOpener(kline_opens=[0, MIN, 2 * MIN], funding_times=[])
    rows = fetch_klines(make(opener), "http://x", "BTCUSDT", "1m", 0, 2 * MIN)  # end_ms is EXCLUSIVE here
    assert [r.open_time_ms for r in rows] == [0, MIN]


def test_fetch_klines_respects_the_page_limit():
    opens = [i * MIN for i in range(10)]
    opener = FakeBinanceRestOpener(kline_opens=opens, funding_times=[])
    rows = fetch_klines(make(opener), "http://x", "BTCUSDT", "1m", 0, 10 * MIN, limit=3)
    assert [r.open_time_ms for r in rows] == opens[:3]


def test_fetch_funding_rate_parses_fields():
    opener = FakeBinanceRestOpener(kline_opens=[], funding_times=[0, 8 * HOUR, 16 * HOUR])
    rows = fetch_funding_rate(make(opener), "http://x", "BTCUSDT", 0, 24 * HOUR)
    assert [r.funding_time_ms for r in rows] == [0, 8 * HOUR, 16 * HOUR]
    assert all(abs(r.funding_rate - 0.0001) < 1e-12 for r in rows)


def test_fetch_funding_rate_excludes_rows_at_or_after_end_ms():
    opener = FakeBinanceRestOpener(kline_opens=[], funding_times=[0, 8 * HOUR])
    rows = fetch_funding_rate(make(opener), "http://x", "BTCUSDT", 0, 8 * HOUR)
    assert [r.funding_time_ms for r in rows] == [0]


def test_empty_range_returns_no_rows():
    opener = FakeBinanceRestOpener(kline_opens=[], funding_times=[])
    assert fetch_klines(make(opener), "http://x", "BTCUSDT", "1m", 0, MIN) == []
    assert fetch_funding_rate(make(opener), "http://x", "BTCUSDT", 0, HOUR) == []

"""arven.data.kraken_live: Kraken OHLC parsing, the closed / in-session / new-only minute rule, and the tail into
ohlcv_1m - offline (fake opener, no sockets)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from rest_helpers import FakeResponse

from arven.data.download import Downloader, RetryPolicy
from arven.data.kraken_live import parse_ohlc, select_new
from arven.data.kraken_live import kraken_tail
from arven.data.storage.db import connect

MIN = 60_000
FRI = int(datetime(2026, 10, 23, 20, 57, tzinfo=UTC).timestamp() * 1000)  # 16:57 New York: 3 minutes before the FX week ends


def _payload(opens_ms, pair="EURUSD"):
    rows = [[t // 1000, "1.1000", "1.1010", "1.0990", "1.1005", "1.1003", "12.5", 7] for t in opens_ms]
    return {"error": [], "result": {pair: rows, "last": opens_ms[-1] // 1000 if opens_ms else 0}}


class _Opener:
    def __init__(self, body: dict):
        self.body, self.calls = json.dumps(body).encode(), []

    def __call__(self, request, timeout=None):
        self.calls.append(getattr(request, "full_url", request))
        return FakeResponse(self.body)


def _fx_cfg(make_config):
    cfg = make_config()
    return cfg.model_copy(update={"market": cfg.market.model_copy(update={"symbol": "EURUSD", "session": "fx"})})


def test_parse_ohlc_reads_rows_and_rejects_api_errors():
    rows = parse_ohlc(_payload([FRI, FRI + MIN]))
    assert rows == [(FRI, 1.1, 1.101, 1.099, 1.1005, 12.5, 7), (FRI + MIN, 1.1, 1.101, 1.099, 1.1005, 12.5, 7)]
    with pytest.raises(ValueError):
        parse_ohlc({"error": ["EGeneral:Invalid arguments"], "result": {}})
    with pytest.raises(ValueError):
        parse_ohlc(_payload([FRI + 30_000]))  # not on a minute


def test_select_new_keeps_only_closed_new_open_minutes():
    rows = [(FRI + k * MIN, 1, 1, 1, 1, 1, 1) for k in range(6)]  # 20:57 ... 21:02 UTC; the FX week closes at 21:00
    now = FRI + 5 * MIN + 30_000  # 21:02:30: the 21:02 minute is still forming
    is_open = lambda t: t < FRI + 3 * MIN  # noqa: E731
    assert [r[0] for r in select_new(rows, FRI, now, is_open)] == [FRI + MIN, FRI + 2 * MIN]  # 20:57 already stored
    assert [r[0] for r in select_new(rows, None, now, lambda t: True)] == [FRI + k * MIN for k in range(5)]


def test_kraken_tail_appends_only_new_in_session_minutes(make_config):
    cfg = _fx_cfg(make_config)
    opener = _Opener(_payload([FRI + k * MIN for k in range(6)]))
    downloader = Downloader(RetryPolicy.from_config(cfg.download), opener=opener, sleep=lambda s: None)
    con = connect(cfg.data.database_path)
    s = kraken_tail(cfg, con, FRI + 6 * MIN, downloader)
    stored = [r[0] for r in con.execute("SELECT open_time_ms FROM ohlcv_1m WHERE symbol = 'EURUSD' ORDER BY 1").fetchall()]
    assert stored == [FRI, FRI + MIN, FRI + 2 * MIN]  # the weekend minutes from 21:00 UTC are not stored
    assert (s.klines_fetched, s.klines_written, s.errors) == (6, 3, [])
    assert "pair=EURUSD" in str(opener.calls[0])
    again = kraken_tail(cfg, con, FRI + 6 * MIN, downloader)  # nothing new: never rewrites what is stored
    assert again.klines_written == 0
    con.close()


def test_kraken_tail_reports_an_unknown_symbol_and_a_failed_request(make_config):
    cfg = make_config()  # BTCUSDT: not a Kraken FX pair
    con = connect(cfg.data.database_path)
    assert kraken_tail(cfg, con, FRI).errors == ["kraken: no live pair for BTCUSDT"]
    fx = _fx_cfg(make_config)
    bad = _Opener({"error": ["EService:Unavailable"], "result": {}})
    s = kraken_tail(fx, con, FRI, Downloader(RetryPolicy.from_config(fx.download), opener=bad, sleep=lambda s: None))
    assert s.klines_written == 0 and s.errors and "EService" in s.errors[0]
    con.close()

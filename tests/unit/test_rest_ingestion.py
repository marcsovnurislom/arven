"""RestIngestor: REST-tail upserts into the real schema, idempotency, and the same normalisation contract
the bulk loader enforces (alignment, funding drift) - offline (fake opener, no sockets).

``RestIngestor`` only ever *continues* from an existing last-stored row (real usage: the bulk backfill
already covers history up to the configured ``history_end``) - it is not a full historical backfill tool,
so every test here seeds one prior row (as ``arven ingest`` would have) before exercising the REST tail.
"""

from __future__ import annotations

from bt_helpers import bulk_insert_1m, bulk_insert_funding
from rest_helpers import FakeBinanceRestOpener

from arven.data.download import Downloader, RetryPolicy
from arven.data.rest_ingestion import RestIngestor
from arven.data.storage.db import connect

HOUR = 3_600_000
MIN = 60_000
SYMBOL = "BTCUSDT"


def _cfg(make_config, kline_opens, funding_times):
    cfg = make_config(default__download__rest_base_url="http://fake")
    opener = FakeBinanceRestOpener(kline_opens, funding_times)
    downloader = Downloader(RetryPolicy.from_config(cfg.download), opener=opener, sleep=lambda s: None)
    return cfg, downloader, opener


def _seed_kline(con, open_time_ms=-MIN):
    bulk_insert_1m(con, [(SYMBOL, open_time_ms, open_time_ms + MIN, 100, 101, 99, 100.5, 1.0, 100.0, 10, 0.5, 50.0, "bulk/x", 0)])


def _seed_funding(con, t_ms=-HOUR):
    bulk_insert_funding(con, [(SYMBOL, t_ms, t_ms, 0.0001, 8, t_ms, "bulk/x", 0)])


def test_tail_with_no_prior_history_fetches_nothing(make_config):
    """With zero stored rows there is nothing to "tail" from - a full REST backfill of history is
    `arven ingest`'s job (the bulk pipeline), not this module's."""
    cfg, downloader, opener = _cfg(make_config, [0, MIN], [0])
    con = connect(cfg.data.database_path)
    summary = RestIngestor(cfg, con, downloader).tail(2 * MIN)
    assert (summary.klines_fetched, summary.klines_written, summary.funding_fetched, summary.funding_written) == (0, 0, 0, 0)
    assert opener.calls == []
    con.close()


def test_tail_continues_from_the_last_stored_1m_bar(make_config):
    cfg, downloader, opener = _cfg(make_config, [0, MIN, 2 * MIN], [])
    con = connect(cfg.data.database_path)
    _seed_kline(con)
    summary = RestIngestor(cfg, con, downloader).tail(3 * MIN)
    assert summary.klines_fetched == 3 and summary.klines_written == 3
    rows = con.execute("SELECT open_time_ms FROM ohlcv_1m ORDER BY open_time_ms").fetchall()
    assert [r[0] for r in rows] == [-MIN, 0, MIN, 2 * MIN]  # the seeded bulk row + the 3 REST-fetched ones
    assert "startTime=0" in opener.calls[0]  # resumes right after the seeded bar, not from scratch
    con.close()


def test_tail_is_idempotent_a_second_identical_tail_changes_nothing(make_config):
    cfg, downloader, _ = _cfg(make_config, [0, MIN, 2 * MIN], [0])
    con = connect(cfg.data.database_path)
    _seed_kline(con)
    _seed_funding(con)
    s1 = RestIngestor(cfg, con, downloader).tail(3 * MIN)
    rows_after_1 = con.execute("SELECT * FROM ohlcv_1m ORDER BY open_time_ms").fetchall()
    funding_after_1 = con.execute("SELECT * FROM funding_rates ORDER BY funding_time_ms").fetchall()
    opener2 = FakeBinanceRestOpener([0, MIN, 2 * MIN], [0])
    downloader2 = Downloader(RetryPolicy.from_config(cfg.download), opener=opener2, sleep=lambda s: None)
    s2 = RestIngestor(cfg, con, downloader2).tail(3 * MIN)
    rows_after_2 = con.execute("SELECT * FROM ohlcv_1m ORDER BY open_time_ms").fetchall()
    funding_after_2 = con.execute("SELECT * FROM funding_rates ORDER BY funding_time_ms").fetchall()
    assert s1.klines_written == 3 and s2.klines_written == 0  # second tail starts where the first left off
    assert s1.funding_written == 1 and s2.funding_written == 0
    assert rows_after_1 == rows_after_2
    assert funding_after_1 == funding_after_2
    con.close()


def test_tail_writes_funding_with_the_configured_default_interval(make_config):
    cfg, downloader, _ = _cfg(make_config, [], [0, 8 * HOUR])
    con = connect(cfg.data.database_path)
    _seed_funding(con)
    summary = RestIngestor(cfg, con, downloader).tail(16 * HOUR)
    assert summary.funding_written == 2
    rows = con.execute(
        "SELECT funding_time_ms, funding_rate, funding_interval_hours FROM funding_rates ORDER BY funding_time_ms"
    ).fetchall()
    assert [r[0] for r in rows] == [-HOUR, 0, 8 * HOUR]
    assert all(r[2] == cfg.costs.funding.default_interval_hours for r in rows[1:])
    con.close()


def test_a_misaligned_1m_open_time_is_rejected_not_silently_stored(make_config):
    cfg, downloader, _ = _cfg(make_config, [MIN + 1], [])  # not aligned to the 1m grid
    con = connect(cfg.data.database_path)
    _seed_kline(con)
    summary = RestIngestor(cfg, con, downloader).tail(2 * MIN)
    assert not summary.ok
    assert "not aligned" in summary.errors[0]
    assert con.execute("SELECT count(*) FROM ohlcv_1m WHERE open_time_ms >= 0").fetchone()[0] == 0
    con.close()


def test_excess_funding_drift_is_rejected_not_silently_rounded(make_config):
    cfg, downloader, _ = _cfg(make_config, [], [2_000])  # 2s from the t=0 grid point, over the 1000ms limit
    con = connect(cfg.data.database_path)
    _seed_funding(con)
    summary = RestIngestor(cfg, con, downloader).tail(HOUR)
    assert not summary.ok
    assert "drift" in summary.errors[0]
    assert con.execute("SELECT count(*) FROM funding_rates WHERE funding_time_ms >= 0").fetchone()[0] == 0
    con.close()


def test_small_funding_jitter_is_normalised_to_the_hour_grid(make_config):
    cfg, downloader, _ = _cfg(make_config, [], [1])  # 1ms jitter, well inside the 1000ms limit
    con = connect(cfg.data.database_path)
    _seed_funding(con)
    summary = RestIngestor(cfg, con, downloader).tail(HOUR)
    assert summary.ok and summary.funding_written == 1
    row = con.execute("SELECT funding_time_ms, raw_funding_time_ms, available_at_ms FROM funding_rates WHERE funding_time_ms >= 0").fetchone()
    assert row == (0, 1, 1)  # normalised to 0, raw kept, available_at = max(raw, normalised)
    con.close()


# --- open interest (live signal loop) ----------------------------------------------------------------------------

M5 = 300_000


def _seed_oi(con, ts_ms, source_key="data/futures/um/daily/metrics/x.zip"):
    from bt_helpers import _copy_insert

    cols = ["symbol", "ts_ms", "available_at_ms", "sum_open_interest", "sum_open_interest_value", "count_toptrader_long_short_ratio",
            "sum_toptrader_long_short_ratio", "count_long_short_ratio", "sum_taker_long_short_vol_ratio", "source_key", "ingested_at_ms"]
    _copy_insert(con, "open_interest", cols, [(SYMBOL, ts_ms, ts_ms + M5, 1.0, 2.0, 1.123456, 1.234567, 1.345678, 1.456789, source_key, 0)])


def test_open_interest_is_tailed_only_on_request_and_stored_under_the_bulk_timestamp(make_config):
    from rest_helpers import oi_value

    t0 = 100 * HOUR
    cfg, downloader, opener = _cfg(make_config, [], [])
    opener.oi_times = [t0 + k * M5 for k in range(1, 7)]
    con = connect(cfg.data.database_path)
    _seed_oi(con, t0)
    assert RestIngestor(cfg, con, downloader).tail(t0 + HOUR).oi_written == 0  # default: klines + funding only
    assert not any("/futures/data/" in c for c in opener.calls)
    summary = RestIngestor(cfg, con, downloader).tail(t0 + HOUR, include_open_interest=True)
    assert summary.ok and summary.oi_written == 6
    rows = con.execute("SELECT ts_ms, available_at_ms, sum_open_interest, sum_toptrader_long_short_ratio, sum_taker_long_short_vol_ratio, "
                       "count_toptrader_long_short_ratio, count_long_short_ratio FROM open_interest ORDER BY ts_ms").fetchall()
    assert rows[0] == (t0, t0 + M5, 1.0, 1.234567, 1.456789, 1.123456, 1.345678)  # the bulk row is untouched
    for k, r in enumerate(rows[1:], start=1):
        t = t0 + k * M5
        assert r == (t, t + cfg.data.open_interest_availability_delay_seconds * 1000, oi_value(t), 1.6, 0.9, 1.5, 1.4)
    con.close()


def test_open_interest_missing_ratio_is_null_and_rest_rows_are_refetched_but_bulk_rows_are_not(make_config):
    t0 = 100 * HOUR
    cfg, downloader, opener = _cfg(make_config, [], [])
    opener.oi_times = [t0 + k * M5 for k in range(1, 4)]
    opener.taker_missing = frozenset({t0 + 3 * M5})
    con = connect(cfg.data.database_path)
    _seed_oi(con, t0)
    RestIngestor(cfg, con, downloader).tail(t0 + HOUR, include_open_interest=True)
    assert con.execute("SELECT sum_taker_long_short_vol_ratio FROM open_interest WHERE ts_ms = ?", [t0 + 3 * M5]).fetchone()[0] is None
    opener.taker_missing = frozenset()  # published late
    opener.calls.clear()
    RestIngestor(cfg, con, downloader).tail(t0 + HOUR, include_open_interest=True)
    assert con.execute("SELECT sum_taker_long_short_vol_ratio FROM open_interest WHERE ts_ms = ?", [t0 + 3 * M5]).fetchone()[0] == 0.9
    assert f"startTime={t0 + M5 + M5}" in opener.calls[0]  # resumes right after the last bulk row (shifted by 5 min), not before it
    assert con.execute("SELECT sum_open_interest FROM open_interest WHERE ts_ms = ?", [t0]).fetchone()[0] == 1.0
    con.close()


def test_open_interest_tail_never_asks_for_more_than_binance_keeps(make_config):
    t0 = 100 * 86_400_000
    cfg, downloader, opener = _cfg(make_config, [], [])
    con = connect(cfg.data.database_path)
    _seed_oi(con, t0)
    end = t0 + 60 * 86_400_000
    summary = RestIngestor(cfg, con, downloader).tail(end, include_open_interest=True)
    assert summary.ok and summary.oi_written == 0
    first = min(int(c.split("startTime=")[1].split("&")[0]) for c in opener.calls if "openInterestHist" in c)
    assert first >= end - 29 * 86_400_000
    con.close()

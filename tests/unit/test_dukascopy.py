"""Dukascopy adapter and ingestion, offline: synthetic ``.bi5`` files in the exact feed format (LZMA, 24-byte
big-endian records, zero-based month in the URL), a fake opener for the download step, a real DuckDB for ingest."""

from __future__ import annotations

import io
import lzma
import shutil
import struct
import urllib.error
from datetime import date, datetime

import numpy as np
import pytest
import yaml

from arven.core.config import DEFAULT_CONFIG_DIR, load_config
from arven.core.time import UTC, to_ms
from arven.data.adapters.dukascopy import (
    DukaDayFile,
    DukascopyFormatError,
    decode_m1,
    mid_candles,
    plan_days,
    plan_files,
)
from arven.data.download import Downloader, RetryPolicy
from arven.data.dukascopy_ingestion import DATASET, DukascopyIngestor, zero_volume_runs
from arven.data.quality import QualityChecker
from arven.data.storage.db import connect

POINT = 1000
DAY = date(2024, 7, 12)  # a Friday in New York summer time: open until 21:00 UTC, then the weekend


def encode(day: date, rows: list[tuple[int, float, float, float, float, float]]) -> bytes:
    """rows: (minute of day, open, high, low, close, volume) -> .bi5 bytes (field order O, C, L, H)."""
    body = b"".join(
        struct.pack(">5If", m * 60, round(o * POINT), round(c * POINT), round(lo * POINT), round(h * POINT), v)
        for m, o, h, lo, c, v in rows
    )
    return lzma.compress(body, format=lzma.FORMAT_ALONE)


def full_day(base: float, closed_from: int | None = None, spread: float = 0.3) -> tuple[bytes, bytes]:
    """1440 BID and ASK candles; minutes >= ``closed_from`` are flat with zero volume (a closed market)."""
    bid, ask = [], []
    for m in range(1440):
        closed = closed_from is not None and m >= closed_from
        p = base if closed else base + m * 0.01
        vol = 0.0 if closed else 1.0 + m % 7
        hi, lo = (p, p) if closed else (p + 0.2, p - 0.2)
        bid.append((m, p, hi, lo, p + (0 if closed else 0.05), vol))
        ask.append((m, p + spread, hi + spread, lo + spread, p + spread + (0 if closed else 0.05), vol * 1.1))
    return encode(DAY, bid), encode(DAY, ask)


# --- adapter ------------------------------------------------------------------------------------


def test_url_uses_zero_based_month_and_key_layout():
    f = DukaDayFile("XAUUSD", date(2024, 3, 5), "BID")
    assert f.url("https://datafeed.dukascopy.com/datafeed/") == (
        "https://datafeed.dukascopy.com/datafeed/XAUUSD/2024/02/05/BID_candles_min_1.bi5")
    assert f.key == "dukascopy/XAUUSD/m1/BID/2024/2024-03-05.bi5"
    assert f.end_ms - f.start_ms == 86_400_000 and f.start_ms == to_ms(datetime(2024, 3, 5, tzinfo=UTC))


def test_plan_covers_overlapping_days_both_sides():
    days = plan_days("XAUUSD", datetime(2024, 3, 5, tzinfo=UTC), datetime(2024, 3, 7, 0, 1, tzinfo=UTC))
    assert days == [date(2024, 3, 5), date(2024, 3, 6), date(2024, 3, 7)]
    files = plan_files("XAUUSD", datetime(2024, 3, 5, tzinfo=UTC), datetime(2024, 3, 6, tzinfo=UTC))
    assert [(f.day, f.side) for f in files] == [(date(2024, 3, 5), "BID"), (date(2024, 3, 5), "ASK")]


def test_decode_reads_open_close_low_high_order():
    raw = encode(DAY, [(0, 2114.455, 2114.975, 2114.165, 2114.865, 0.00705)])
    c = decode_m1(raw, DAY, POINT)
    assert len(c) == 1 and c.time_ms[0] == to_ms(datetime(2024, 7, 12, tzinfo=UTC))
    assert (c.open[0], c.high[0], c.low[0], c.close[0]) == (2114.455, 2114.975, 2114.165, 2114.865)
    assert c.volume[0] == pytest.approx(0.00705)
    assert len(decode_m1(b"", DAY, POINT)) == 0


@pytest.mark.parametrize(
    "raw",
    [
        b"not lzma at all",
        lzma.compress(b"x" * 25, format=lzma.FORMAT_ALONE),  # not whole records
        encode(DAY, [(5, 1, 2, 0.5, 1.5, 1), (4, 1, 2, 0.5, 1.5, 1)]),  # times not increasing
        encode(DAY, [(0, 1, 2, 1.2, 1.5, 1)]),  # low above open
        encode(DAY, [(0, 1, 1.4, 0.5, 1.5, 1)]),  # high below close
    ],
)
def test_decode_rejects_malformed_files(raw):
    with pytest.raises(DukascopyFormatError):
        decode_m1(raw, DAY, POINT)


def test_mid_is_fieldwise_average_and_needs_matching_minutes():
    bid = decode_m1(encode(DAY, [(0, 100, 101, 99, 100.5, 2.0)]), DAY, POINT)
    ask = decode_m1(encode(DAY, [(0, 100.4, 101.4, 99.4, 100.9, 3.0)]), DAY, POINT)
    m = mid_candles(bid, ask)
    assert (m.open[0], m.high[0], m.low[0], m.close[0], m.volume[0]) == (100.2, 101.2, 99.2, 100.7, 2.0)
    other = decode_m1(encode(DAY, [(1, 100.4, 101.4, 99.4, 100.9, 3.0)]), DAY, POINT)
    with pytest.raises(DukascopyFormatError):
        mid_candles(bid, other)


def test_zero_volume_runs():
    bid, _ = full_day(2000.0, closed_from=1260)
    c = decode_m1(bid, DAY, POINT)
    runs = zero_volume_runs(c, 30)
    assert runs == [(to_ms(datetime(2024, 7, 12, 21, tzinfo=UTC)), to_ms(datetime(2024, 7, 13, tzinfo=UTC)))]


# --- download + ingest ------------------------------------------------------------------------------


@pytest.fixture
def gold(tmp_path):
    d = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, d)
    default = yaml.safe_load((d / "default.yaml").read_text(encoding="utf-8"))
    default["data"]["data_dir"] = str(tmp_path / "data")
    (d / "default.yaml").write_text(yaml.safe_dump(default), encoding="utf-8")
    return load_config(d, instrument="XAUUSD"), d


class FakeFeed:
    """Serves .bi5 bodies by URL; unknown URLs answer 404; ``fail`` URLs answer 503 every time."""

    def __init__(self, files: dict[str, bytes], fail: frozenset[str] = frozenset()):
        self.files, self.fail, self.calls = files, fail, []

    def __call__(self, request, timeout):
        url = request.full_url
        self.calls.append(url)
        if url in self.fail:
            raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)
        if url not in self.files:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        body = self.files[url]
        resp = io.BytesIO(body)
        resp.headers = {"Content-Length": str(len(body))}
        return resp


def _ingestor(cfg, feed, sleeps=None):
    dl = Downloader(RetryPolicy(2, 1.0, 0.0, 1.0, 0.0), opener=feed, sleep=lambda s: None)
    return DukascopyIngestor(cfg, dl, sleep=(sleeps.append if sleeps is not None else lambda s: None),
                             today=lambda: date(2024, 7, 20))


def _url(cfg, day, side):
    return DukaDayFile("XAUUSD", day, side).url(cfg.dukascopy.base_url)


def test_download_fetches_validates_remembers_404_and_skips_present(gold):
    cfg, _ = gold
    bid, ask = full_day(2000.0, closed_from=1260)
    sat = date(2024, 7, 13)
    feed = FakeFeed({_url(cfg, DAY, "BID"): bid, _url(cfg, DAY, "ASK"): ask, _url(cfg, sat, "BID"): bid},
                    fail=frozenset({_url(cfg, sat, "ASK")}))
    sleeps: list[float] = []
    ing = _ingestor(cfg, feed, sleeps)
    s = ing.download(datetime(2024, 7, 12, tzinfo=UTC), datetime(2024, 7, 15, tzinfo=UTC))
    # 3 days x 2 sides: Fri both ok, Sat BID ok + ASK 503, Sun both 404
    assert (s.planned, s.downloaded, s.failed, s.not_available, s.present) == (6, 3, 1, 2, 0)
    assert sleeps and all(x == cfg.dukascopy.request_interval_seconds for x in sleeps)
    sun = DukaDayFile("XAUUSD", date(2024, 7, 14), "BID")
    assert (cfg.data.raw_dir / (sun.key + ".404")).exists()
    feed2 = FakeFeed({})
    s2 = _ingestor(cfg, feed2).download(datetime(2024, 7, 12, tzinfo=UTC), datetime(2024, 7, 15, tzinfo=UTC))
    # only the failed file is asked for again (this feed now answers 404 for it); the remembered 404s are not
    assert (s2.present, s2.not_available, s2.downloaded) == (3, 3, 0)
    assert feed2.calls == [_url(cfg, sat, "ASK")]


def test_download_never_requests_unfinished_days(gold):
    cfg, _ = gold
    feed = FakeFeed({})
    s = _ingestor(cfg, feed).download(datetime(2024, 7, 20, tzinfo=UTC), datetime(2024, 7, 22, tzinfo=UTC))
    assert feed.calls == [] and s.not_available == 4


def _write_raw(cfg, day, bid, ask):
    for side, body in (("BID", bid), ("ASK", ask)):
        p = cfg.data.raw_dir / DukaDayFile("XAUUSD", day, side).key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)


def test_ingest_stores_mid_prices_of_open_minutes_only(gold):
    cfg, _ = gold
    bid, ask = full_day(2000.0, closed_from=1260)
    _write_raw(cfg, DAY, bid, ask)
    con = connect(cfg.data.database_path)
    s = _ingestor(cfg, FakeFeed({})).ingest(con, datetime(2024, 7, 12, tzinfo=UTC), datetime(2024, 7, 13, tzinfo=UTC))
    assert (s.ingested, s.rows_written, s.out_of_session_dropped) == (1, 1260, 180)  # 00:00-21:00 open on a summer Friday
    t, o, h, lo, c, v, tc, tbv = con.execute(
        "SELECT open_time_ms, open, high, low, close, volume, trade_count, taker_buy_volume FROM ohlcv_1m "
        "WHERE symbol = 'XAUUSD' ORDER BY open_time_ms LIMIT 1").fetchone()
    assert t == to_ms(datetime(2024, 7, 12, tzinfo=UTC))
    assert (o, h, lo, c) == pytest.approx((2000.15, 2000.35, 1999.95, 2000.2))
    assert v == 1.0 and tc == 0 and tbv == 0.0
    last = con.execute("SELECT max(open_time_ms) FROM ohlcv_1m WHERE symbol = 'XAUUSD'").fetchone()[0]
    assert last == to_ms(datetime(2024, 7, 12, 20, 59, tzinfo=UTC))
    rec = con.execute("SELECT dataset, status, row_count, symbol FROM source_files WHERE dataset = ?", [DATASET]).fetchone()
    assert rec == (DATASET, "ingested", 1260, "XAUUSD")
    con.close()


def test_ingest_is_idempotent_and_reacts_to_changed_closures(gold):
    cfg, d = gold
    bid, ask = full_day(2000.0, closed_from=1260)
    _write_raw(cfg, DAY, bid, ask)
    con = connect(cfg.data.database_path)
    rng = (datetime(2024, 7, 12, tzinfo=UTC), datetime(2024, 7, 13, tzinfo=UTC))
    _ingestor(cfg, FakeFeed({})).ingest(con, *rng)
    rows1 = con.execute("SELECT * EXCLUDE (ingested_at_ms) FROM ohlcv_1m ORDER BY open_time_ms").fetchall()
    s2 = _ingestor(cfg, FakeFeed({})).ingest(con, *rng)
    assert (s2.skipped, s2.ingested) == (1, 0)
    csv = d / "sessions" / "cme_metals_closures.csv"
    csv.write_text(csv.read_text(encoding="utf-8") + "2024-07-12T17:00:00Z,2024-07-12T21:00:00Z,early close,test\n",
                   encoding="utf-8")
    cfg2 = load_config(d, instrument="XAUUSD")
    s3 = _ingestor(cfg2, FakeFeed({})).ingest(con, *rng)
    assert (s3.ingested, s3.rows_written) == (1, 17 * 60)
    rows3 = con.execute("SELECT * EXCLUDE (ingested_at_ms) FROM ohlcv_1m ORDER BY open_time_ms").fetchall()
    assert rows3 == rows1[: 17 * 60]
    con.close()


def test_ingest_counts_missing_and_404_days(gold):
    cfg, _ = gold
    bid, _ = full_day(2000.0)
    p = cfg.data.raw_dir / DukaDayFile("XAUUSD", DAY, "BID").key
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(bid)  # ASK missing
    sun = DukaDayFile("XAUUSD", date(2024, 7, 14), "BID")
    m = cfg.data.raw_dir / (sun.key + ".404")
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_bytes(b"")
    con = connect(cfg.data.database_path)
    s = _ingestor(cfg, FakeFeed({})).ingest(con, datetime(2024, 7, 12, tzinfo=UTC), datetime(2024, 7, 15, tzinfo=UTC))
    assert (s.missing_raw, s.not_available, s.ingested) == (2, 1, 0)
    con.close()


def test_quality_passes_on_clean_session_data_and_catches_tampering(gold):
    from arven.data.resample import resample

    cfg, _ = gold
    _write_raw(cfg, date(2024, 7, 11), *full_day(2000.0))  # Thursday: the 21:00-22:00 halt is dropped on ingest
    _write_raw(cfg, DAY, *full_day(2000.0, closed_from=1260))  # Friday: closed from 21:00 UTC
    con = connect(cfg.data.database_path)
    lo, hi = datetime(2024, 7, 11, tzinfo=UTC), datetime(2024, 7, 13, tzinfo=UTC)
    _ingestor(cfg, FakeFeed({})).ingest(con, lo, hi)
    resample(con, "XAUUSD", lo, hi, calendar=cfg.session_calendar())
    results = {r.check_id: r for r in QualityChecker(cfg, con).run(lo, hi)}
    assert results["ohlcv_1m.row_count"].passed and results["ohlcv_1m.gaps"].passed
    assert results["ohlcv_1m.out_of_session"].passed
    assert results["source_files.consistency"].passed
    assert results["ohlcv_4h.row_count"].passed  # 4h buckets around the halt and the Friday close are complete
    assert results["funding_rates.not_applicable"].passed and "open_interest.gaps" not in results
    # tamper: a stored price differs from the raw file, and a bar inside the halt appears
    con.execute("UPDATE ohlcv_1m SET close = close + 1 WHERE open_time_ms = ?", [to_ms(datetime(2024, 7, 11, 3, tzinfo=UTC))])
    con.execute("INSERT INTO ohlcv_1m SELECT * REPLACE (open_time_ms + 3600000 AS open_time_ms, close_time_ms + 3600000 AS close_time_ms) "
                "FROM ohlcv_1m WHERE open_time_ms = ?", [to_ms(datetime(2024, 7, 11, 20, 30, tzinfo=UTC))])
    results = {r.check_id: r for r in QualityChecker(cfg, con).run(lo, hi)}
    assert not results["source_files.consistency"].passed
    assert not results["ohlcv_1m.out_of_session"].passed
    con.close()


def test_quality_reports_missing_open_minutes_as_gaps(gold):
    cfg, _ = gold
    bid, ask = full_day(2000.0, closed_from=1260)
    _write_raw(cfg, DAY, bid, ask)
    con = connect(cfg.data.database_path)
    lo, hi = datetime(2024, 7, 12, tzinfo=UTC), datetime(2024, 7, 13, tzinfo=UTC)
    _ingestor(cfg, FakeFeed({})).ingest(con, lo, hi)
    t = to_ms(datetime(2024, 7, 12, 10, tzinfo=UTC))
    con.execute("DELETE FROM ohlcv_1m WHERE open_time_ms >= ? AND open_time_ms < ?", [t, t + 5 * 60_000])
    results = {r.check_id: r for r in QualityChecker(cfg, con).run(lo, hi)}
    g = results["ohlcv_1m.gaps"]
    assert not g.passed and g.details["gaps"] == [{"start": "2024-07-12T10:00:00Z", "end": "2024-07-12T10:05:00Z", "missing": 5}]
    assert results["ohlcv_1m.row_count"].observed == "1255 rows, expected 1260"
    con.close()

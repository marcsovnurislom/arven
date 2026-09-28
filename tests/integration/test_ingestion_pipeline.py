"""End-to-end ingestion against a local HTTP server that mimics data.binance.vision (offline)."""

import hashlib
import http.server
import io
import socket
import threading
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from arven.core.time import UTC, to_ms
from arven.core.timeframes import Timeframe
from arven.data.adapters.binance_bulk import Dataset, Granularity, SourceFile, plan_files
from arven.data.download import Downloader, RetryPolicy
from arven.data.ingestion import Ingestor
from arven.data.quality import QualityChecker
from arven.data.resample import resample
from arven.data.storage.db import connect

START = datetime(2024, 2, 27, tzinfo=UTC)
END = datetime(2024, 3, 1, tzinfo=UTC)
SYMBOL = "BTCUSDT"
KLINE_HEADER = ("open_time,open,high,low,close,volume,close_time,quote_volume,count,"
                "taker_buy_volume,taker_buy_quote_volume,ignore")
METRICS_HEADER = ("create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
                  "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio")


# --- fake bucket content ------------------------------------------------------------------------


def kline_csv(day: datetime, header: bool) -> str:
    lines = [KLINE_HEADER] if header else []
    base = to_ms(day)
    for i in range(1440):
        o = 50000 + (i % 97) * 1.5
        c = o + 0.7
        lines.append(f"{base + i * 60000},{o:.2f},{c + 2:.2f},{o - 2:.2f},{c:.2f},{1.234 + i % 5:.3f},"
                     f"{base + i * 60000 + 59999},{61234.56789:.5f},{100 + i % 7},0.617,30617.28394,0")
    return "\n".join(lines) + "\n"


def funding_csv(month: datetime) -> str:
    lines = ["calc_time,funding_interval_hours,last_funding_rate"]
    t = month
    nxt = datetime(month.year + month.month // 12, month.month % 12 + 1, 1, tzinfo=UTC)
    i = 0
    while t < nxt:
        jitter = 1 if i % 5 == 4 else 0  # Binance-style +1 ms jitter on some rows
        lines.append(f"{to_ms(t) + jitter},8,{0.0001 * (1 + i % 3):.8f}")
        t += timedelta(hours=8)
        i += 1
    return "\n".join(lines) + "\n"


def metrics_csv(day: datetime, duplicate_rows: bool) -> str:
    lines = [METRICS_HEADER]
    for i in range(288):
        ts = (day + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M:%S")
        row = f"{ts},{SYMBOL},{80000 + i:.8f},{4.0e9 + i:.8f},1.7,1.5,1.6,{0.9 + (i % 3) / 10:.8f}"
        lines += [row, row] if duplicate_rows else [row]
    return "\n".join(lines) + "\n"


def zip_bytes(name: str, content: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name.replace(".zip", ".csv"), content)
    return buf.getvalue()


def put(bucket: Path, sf: SourceFile, content: str, checksum_override: str | None = None) -> None:
    data = zip_bytes(sf.filename, content)
    path = bucket / sf.key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    digest = checksum_override or hashlib.sha256(data).hexdigest()
    (bucket / sf.checksum_key).write_text(f"{digest}  {sf.filename}\n")


def build_bucket(bucket: Path) -> None:
    for i, sf in enumerate(plan_files(Dataset.KLINES, SYMBOL, START, END, Timeframe.M1)):
        put(bucket, sf, kline_csv(sf.period_start, header=i > 0))  # first file: old headerless format
    for sf in plan_files(Dataset.FUNDING_RATE, SYMBOL, START, END):
        put(bucket, sf, funding_csv(sf.period_start))
    for i, sf in enumerate(plan_files(Dataset.METRICS, SYMBOL, START, END)):
        put(bucket, sf, metrics_csv(sf.period_start, duplicate_rows=i == 0))


# --- fake server --------------------------------------------------------------------------------


class FakeBinance:
    def __init__(self, root: Path):
        self.root = root
        self.requests: list[str] = []
        self.reset_first: set[str] = set()  # paths whose first request gets its connection reset
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                path = self.path.lstrip("/")
                fake.requests.append(path)
                if path in fake.reset_first:
                    fake.reset_first.discard(path)
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                file = fake.root / path
                if not file.is_file():
                    self.send_error(404)
                    return
                body = file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def env(tmp_path, make_config):
    bucket = tmp_path / "bucket"
    build_bucket(bucket)
    server = FakeBinance(bucket)
    cfg = make_config(default__download__base_url=server.url)
    con = connect(cfg.data.database_path)
    downloader = Downloader(RetryPolicy.from_config(cfg.download), sleep=lambda s: None)
    ingestor = Ingestor(cfg, con, downloader)
    yield cfg, con, ingestor, server, bucket
    con.close()
    server.close()


def counts(con) -> dict[str, int]:
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("ohlcv_1m", "funding_rates", "open_interest", "source_files")}


# --- tests --------------------------------------------------------------------------------------


def test_ingest_normalises_all_datasets(env):
    cfg, con, ingestor, server, _ = env
    summary = ingestor.ingest(START, END)
    assert summary.ok, summary.errors
    assert summary.planned == 3 + 1 + 3 and summary.ingested == 7
    assert summary.duplicate_rows_dropped == 288
    assert counts(con) == {"ohlcv_1m": 3 * 1440, "funding_rates": 29 * 3, "open_interest": 3 * 288,
                           "source_files": 7}

    # klines: both header formats, close_time normalised to open + 1m
    lo, hi, bad = con.execute(
        "SELECT min(open_time_ms), max(open_time_ms), count(*) FILTER (close_time_ms <> open_time_ms + 60000) FROM ohlcv_1m"
    ).fetchone()
    assert (lo, hi, bad) == (to_ms(START), to_ms(END) - 60000, 0)

    # funding: jitter removed from the key, preserved in raw column, availability not earlier than raw time
    jittered, off_grid, early = con.execute(
        """SELECT count(*) FILTER (raw_funding_time_ms <> funding_time_ms),
                  count(*) FILTER (funding_time_ms % 28800000 <> 0),
                  count(*) FILTER (available_at_ms < raw_funding_time_ms)
           FROM funding_rates"""
    ).fetchone()
    assert jittered > 0 and off_grid == 0 and early == 0

    # OI: UTC parse and configured availability delay
    first_ts, first_avail = con.execute("SELECT ts_ms, available_at_ms FROM open_interest ORDER BY ts_ms LIMIT 1").fetchone()
    assert first_ts == to_ms(START)
    assert first_avail - first_ts == cfg.data.open_interest_availability_delay_seconds * 1000

    # provenance
    rows = con.execute(
        "SELECT status, expected_sha256 = actual_sha256, downloaded_at_ms IS NOT NULL, row_count, url FROM source_files"
    ).fetchall()
    assert all(r[0] == "ingested" and r[1] and r[2] and r[3] > 0 and r[4].startswith(server.url) for r in rows)
    run = con.execute("SELECT status, config_hash FROM ingestion_runs").fetchone()
    assert run == ("succeeded", cfg.config_hash())


def test_second_run_is_a_noop_without_network(env):
    _, con, ingestor, server, _ = env
    ingestor.ingest(START, END)
    before, n_requests = counts(con), len(server.requests)
    snapshot = con.execute("SELECT * FROM ohlcv_1m ORDER BY open_time_ms").fetchall()

    summary = ingestor.ingest(START, END)
    assert summary.skipped == 7 and summary.ingested == 0 and summary.downloaded == 0
    assert len(server.requests) == n_requests  # nothing fetched
    assert counts(con) == before
    assert con.execute("SELECT * FROM ohlcv_1m ORDER BY open_time_ms").fetchall() == snapshot


def test_refresh_reingests_without_duplicating(env):
    _, con, ingestor, _, _ = env
    ingestor.ingest(START, END)
    before = counts(con)
    summary = ingestor.ingest(START, END, refresh=True)
    assert summary.ingested == 7 and summary.downloaded == 0 and summary.reused_local == 7
    assert counts(con) == before


def test_connection_resets_are_retried(env):
    _, con, ingestor, server, _ = env
    sf = plan_files(Dataset.KLINES, SYMBOL, START, END, Timeframe.M1)[0]
    server.reset_first |= {sf.key, sf.checksum_key}
    summary = ingestor.ingest(START, END, datasets=(Dataset.KLINES,))
    assert summary.ok and summary.ingested == 3
    assert server.requests.count(sf.key) == 2 and server.requests.count(sf.checksum_key) == 2


def test_missing_file_is_recorded_not_available(env):
    _, con, ingestor, server, bucket = env
    sf = plan_files(Dataset.METRICS, SYMBOL, START, END)[1]
    (bucket / sf.key).unlink()
    (bucket / sf.checksum_key).unlink()
    summary = ingestor.ingest(START, END, datasets=(Dataset.METRICS,))
    assert summary.not_available == 1 and summary.ingested == 2 and summary.ok
    assert con.execute("SELECT status FROM source_files WHERE source_key = ?", [sf.key]).fetchone()[0] == "not_available"
    n_requests = len(server.requests)
    assert ingestor.ingest(START, END, datasets=(Dataset.METRICS,)).not_available == 1
    assert len(server.requests) == n_requests  # absence is remembered; not re-requested


def test_checksum_mismatch_stores_nothing(env):
    cfg, con, ingestor, _, bucket = env
    sf = plan_files(Dataset.KLINES, SYMBOL, START, END, Timeframe.M1)[1]
    put(bucket, sf, kline_csv(sf.period_start, header=True), checksum_override="0" * 64)
    summary = ingestor.ingest(START, END, datasets=(Dataset.KLINES,))
    assert summary.failed == 1 and summary.ingested == 2
    assert con.execute("SELECT status FROM source_files WHERE source_key = ?", [sf.key]).fetchone()[0] == "checksum_mismatch"
    assert con.execute("SELECT count(*) FROM ohlcv_1m WHERE source_key = ?", [sf.key]).fetchone()[0] == 0
    assert not (cfg.data.raw_dir / sf.key).exists()
    assert con.execute("SELECT status FROM ingestion_runs").fetchone()[0] == "completed_with_errors"


def test_contract_violation_rolls_back_whole_file(env):
    _, con, ingestor, _, bucket = env
    sf = plan_files(Dataset.KLINES, SYMBOL, START, END, Timeframe.M1)[2]
    lines = kline_csv(sf.period_start, header=True).splitlines()
    fields = lines[500].split(",")
    fields[4] = "12345.00"  # same open_time, different close -> conflicting duplicate
    put(bucket, sf, "\n".join(lines + [",".join(fields)]) + "\n")
    summary = ingestor.ingest(START, END, datasets=(Dataset.KLINES,))
    assert summary.failed == 1
    status, error = con.execute("SELECT status, error FROM source_files WHERE source_key = ?", [sf.key]).fetchone()
    assert status == "failed" and "conflicting" in error
    assert con.execute("SELECT count(*) FROM ohlcv_1m WHERE source_key = ?", [sf.key]).fetchone()[0] == 0


def test_bad_close_time_convention_is_rejected(env):
    _, con, ingestor, _, bucket = env
    sf = plan_files(Dataset.KLINES, SYMBOL, START, END, Timeframe.M1)[0]
    put(bucket, sf, kline_csv(sf.period_start, header=True).replace("59999,", "60000,"))
    summary = ingestor.ingest(START, END, datasets=(Dataset.KLINES,))
    assert summary.failed == 1
    assert "close_time" in con.execute("SELECT error FROM source_files WHERE source_key = ?", [sf.key]).fetchone()[0]


def test_quality_checks_pass_on_clean_data(env):
    cfg, con, ingestor, _, _ = env
    ingestor.ingest(START, END)
    resample(con, SYMBOL, START, END)
    results = {r.check_id: r for r in QualityChecker(cfg, con).run(START, END)}
    failed = {k: r.observed for k, r in results.items() if not r.passed}
    assert failed == {}
    assert results["source_files.consistency"].observed.startswith("7 files re-read")
    assert con.execute("SELECT count(*) FROM quality_results").fetchone()[0] == len(results)


def test_quality_flags_injected_problems(env):
    cfg, con, ingestor, _, _ = env
    ingestor.ingest(START, END)
    con.execute("DELETE FROM ohlcv_1m WHERE open_time_ms BETWEEN ? AND ?", [to_ms(START) + 600_000, to_ms(START) + 780_000])
    con.execute("UPDATE ohlcv_1m SET low = high + 1 WHERE open_time_ms = ?", [to_ms(START) + 60_000 * 100])
    resample(con, SYMBOL, START, END)
    results = {r.check_id: r for r in QualityChecker(cfg, con).run(START, END)}
    assert not results["ohlcv_1m.gaps"].passed
    assert results["ohlcv_1m.gaps"].observed.startswith("1 gaps, 4 missing")
    assert not results["ohlcv_1m.ohlc_validity"].passed
    assert not results["ohlcv_5m.row_count"].passed  # an incomplete 5m bar
    assert not results["source_files.consistency"].passed
    assert con.execute("SELECT missing_count FROM data_gaps WHERE dataset = 'ohlcv_1m'").fetchall() == [(4,)]


def test_native_klines_go_to_crosscheck_table(env):
    _, con, ingestor, _, bucket = env
    for sf in plan_files(Dataset.KLINES, SYMBOL, START, END, Timeframe.H1):
        lines = [KLINE_HEADER]
        base = to_ms(sf.period_start)
        for h in range(24):
            lines.append(f"{base + h * 3600000},1,2,0.5,1.5,10.000,{base + (h + 1) * 3600000 - 1},15.0,5,5.000,7.5,0")
        put(bucket, sf, "\n".join(lines) + "\n")
    summary = ingestor.ingest(START, END, datasets=(Dataset.KLINES,), kline_intervals=(Timeframe.H1,))
    assert summary.ok and summary.ingested == 3
    assert con.execute("SELECT count(*), min(timeframe) FROM ohlcv_native").fetchone() == (72, "1h")
    assert con.execute("SELECT count(*) FROM ohlcv_1m").fetchone()[0] == 0

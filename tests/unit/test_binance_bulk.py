from datetime import datetime

import pytest

from arven.core.time import UTC
from arven.core.timeframes import Timeframe
from arven.data.adapters.binance_bulk import (
    Dataset,
    Granularity,
    SourceFile,
    has_header,
    parse_checksum,
    plan_files,
)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_monthly_kline_key_matches_binance_layout():
    sf = SourceFile(Dataset.KLINES, Granularity.MONTHLY, "BTCUSDT", utc(2024, 3, 1), Timeframe.M1)
    assert sf.key == "data/futures/um/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2024-03.zip"
    assert sf.url("https://data.binance.vision/") == "https://data.binance.vision/" + sf.key
    assert sf.checksum_key == sf.key + ".CHECKSUM"
    assert sf.period_end == utc(2024, 4, 1)


def test_daily_metrics_and_monthly_funding_keys():
    metrics = SourceFile(Dataset.METRICS, Granularity.DAILY, "BTCUSDT", utc(2024, 3, 15))
    assert metrics.key == "data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2024-03-15.zip"
    assert metrics.period_end == utc(2024, 3, 16)
    funding = SourceFile(Dataset.FUNDING_RATE, Granularity.MONTHLY, "BTCUSDT", utc(2024, 12, 1))
    assert funding.key == "data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2024-12.zip"
    assert funding.period_end == utc(2025, 1, 1)


def test_source_file_validation():
    with pytest.raises(ValueError, match="interval"):
        SourceFile(Dataset.KLINES, Granularity.MONTHLY, "BTCUSDT", utc(2024, 3, 1))
    with pytest.raises(ValueError, match="interval"):
        SourceFile(Dataset.METRICS, Granularity.DAILY, "BTCUSDT", utc(2024, 3, 1), Timeframe.M1)
    with pytest.raises(ValueError, match="first day"):
        SourceFile(Dataset.FUNDING_RATE, Granularity.MONTHLY, "BTCUSDT", utc(2024, 3, 2))
    with pytest.raises(ValueError, match="midnight"):
        SourceFile(Dataset.METRICS, Granularity.DAILY, "BTCUSDT", utc(2024, 3, 2, 1))


def test_plan_klines_uses_monthly_for_full_months_and_daily_for_edges():
    files = plan_files(Dataset.KLINES, "BTCUSDT", utc(2024, 1, 30), utc(2024, 4, 2), Timeframe.M1)
    tags = [(f.granularity.value, f.period_tag) for f in files]
    assert tags == [
        ("daily", "2024-01-30"),
        ("daily", "2024-01-31"),
        ("monthly", "2024-02"),
        ("monthly", "2024-03"),
        ("daily", "2024-04-01"),
    ]


def test_plan_test_slice():
    files = plan_files(Dataset.KLINES, "BTCUSDT", utc(2024, 1, 1), utc(2024, 3, 1), Timeframe.M1)
    assert [f.filename for f in files] == ["BTCUSDT-1m-2024-01.zip", "BTCUSDT-1m-2024-02.zip"]
    assert len(plan_files(Dataset.METRICS, "BTCUSDT", utc(2024, 1, 1), utc(2024, 3, 1))) == 31 + 29


def test_plan_funding_is_monthly_only_and_covers_partial_months():
    files = plan_files(Dataset.FUNDING_RATE, "BTCUSDT", utc(2024, 1, 15), utc(2024, 3, 2))
    assert [f.period_tag for f in files] == ["2024-01", "2024-02", "2024-03"]
    assert all(f.granularity is Granularity.MONTHLY for f in files)


def test_plan_files_contiguous_and_non_overlapping():
    files = plan_files(Dataset.KLINES, "BTCUSDT", utc(2023, 11, 17), utc(2024, 2, 3), Timeframe.M1)
    for a, b in zip(files, files[1:]):
        assert a.period_end == b.period_start
    assert files[0].period_start == utc(2023, 11, 17)
    assert files[-1].period_end == utc(2024, 2, 3)


def test_plan_rejects_non_midnight_bounds_and_handles_empty():
    with pytest.raises(ValueError, match="midnight"):
        plan_files(Dataset.METRICS, "BTCUSDT", utc(2024, 1, 1, 5), utc(2024, 1, 2))
    assert plan_files(Dataset.METRICS, "BTCUSDT", utc(2024, 1, 2), utc(2024, 1, 2)) == []


def test_parse_checksum():
    digest = "040b8e448e4243072b88b0d9908dfebed91bba943b75f4e831fa5337a2e1dab9"
    assert parse_checksum(f"{digest}  BTCUSDT-1m-2024-03.zip\n", "BTCUSDT-1m-2024-03.zip") == digest
    assert parse_checksum(f"{digest.upper()} *BTCUSDT-1m-2024-03.zip", "BTCUSDT-1m-2024-03.zip") == digest
    with pytest.raises(ValueError, match="refers to"):
        parse_checksum(f"{digest}  other.zip", "BTCUSDT-1m-2024-03.zip")
    with pytest.raises(ValueError):
        parse_checksum("nothex  BTCUSDT-1m-2024-03.zip", "BTCUSDT-1m-2024-03.zip")
    with pytest.raises(ValueError):
        parse_checksum("", "x.zip")


def test_header_detection_old_and_new_kline_formats():
    assert has_header("open_time,open,high,low,close,volume,close_time,...\n", Dataset.KLINES)
    assert not has_header("1577836800000,7189.43,7190.52,7177,7182.44,246.092,1577836859999,...\n", Dataset.KLINES)
    assert has_header("﻿calc_time,funding_interval_hours,last_funding_rate", Dataset.FUNDING_RATE)
    assert not has_header("2020-09-01 00:00:00,BTCUSDT,39080.231", Dataset.METRICS)

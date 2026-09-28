from datetime import date, datetime, timedelta, timezone

import pytest

from arven.core.time import UTC, ensure_utc, from_ms, to_ms, to_utc_datetime


def test_ensure_utc_rejects_naive_datetime():
    with pytest.raises(ValueError, match="naive"):
        ensure_utc(datetime(2024, 1, 1, 12, 0))


def test_ensure_utc_converts_other_offsets_to_utc():
    tashkent = timezone(timedelta(hours=5))
    result = ensure_utc(datetime(2024, 1, 1, 17, 0, tzinfo=tashkent))
    assert result == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    assert result.utcoffset() == timedelta(0)


def test_ms_roundtrip_known_value():
    # 2024-01-01T00:00:00Z == 1704067200000 ms (Binance kline open_time)
    dt = datetime(2024, 1, 1, tzinfo=UTC)
    assert to_ms(dt) == 1_704_067_200_000
    assert from_ms(1_704_067_200_000) == dt


def test_ms_roundtrip_is_exact_for_many_values():
    base = 1_577_836_800_000  # 2020-01-01
    for offset in (0, 1, 999, 59_999, 3_600_000, 123_456_789_012):
        assert to_ms(from_ms(base + offset)) == base + offset


def test_to_ms_truncates_sub_millisecond():
    dt = datetime(2024, 1, 1, 0, 0, 0, 999, tzinfo=UTC)  # 999 microseconds
    assert to_ms(dt) == 1_704_067_200_000


def test_from_ms_rejects_non_int():
    with pytest.raises(TypeError):
        from_ms(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        from_ms(True)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    ["2020-01-01", date(2020, 1, 1), "2020-01-01T00:00:00Z", "2020-01-01T05:00:00+05:00"],
)
def test_to_utc_datetime_accepts_config_formats(value):
    assert to_utc_datetime(value) == datetime(2020, 1, 1, tzinfo=UTC)


def test_to_utc_datetime_rejects_naive_iso_string():
    with pytest.raises(ValueError, match="naive"):
        to_utc_datetime("2020-01-01T00:00:00")

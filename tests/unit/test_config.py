import copy
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from arven.core.config import CONFIG_FILES, DEFAULT_CONFIG_DIR, PROJECT_ROOT, load_config
from arven.core.time import UTC
from arven.core.timeframes import Timeframe


def _repo_yaml() -> dict[str, dict]:
    return {
        name: yaml.safe_load((DEFAULT_CONFIG_DIR / name).read_text(encoding="utf-8"))
        for name in CONFIG_FILES
    }


def _write(tmp_path: Path, docs: dict[str, dict]) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name, content in docs.items():
        (config_dir / name).write_text(yaml.safe_dump(content), encoding="utf-8")
    return config_dir


@pytest.fixture
def docs() -> dict[str, dict]:
    return copy.deepcopy(_repo_yaml())


def test_repository_config_loads():
    cfg = load_config()
    assert cfg.market.symbol == "BTCUSDT"
    assert cfg.market.decision_timeframe is Timeframe.H1
    assert cfg.market.context_timeframe is Timeframe.H4
    assert cfg.market.feature_timeframes == (Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4)
    assert cfg.splits.test.sealed is True


def test_dates_are_utc_aware():
    cfg = load_config()
    assert cfg.data.history_start == datetime(2020, 1, 1, tzinfo=UTC)
    for period in (cfg.splits.development, cfg.splits.validation, cfg.splits.test):
        assert period.start.tzinfo is not None and period.start.utcoffset() == timedelta(0)


def test_relative_data_dir_resolves_against_project_root():
    cfg = load_config()
    assert cfg.data.data_dir == (PROJECT_ROOT / "data").resolve()
    assert cfg.data.database_path.name == "arven.duckdb"


def test_costs_are_read_from_config_not_hardcoded(tmp_path, docs):
    docs["costs.yaml"]["fees"]["taker_fee_bps"] = 4.5
    docs["costs.yaml"]["fees"]["maker_fee_bps"] = -0.5
    cfg = load_config(_write(tmp_path, docs))
    assert cfg.costs.fees.fee_bps("taker") == 4.5
    assert cfg.costs.fees.fee_bps("maker") == -0.5


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("fees", "taker_fee_bps", -1.0),       # negative taker fee
        ("fees", "taker_fee_bps", 500.0),      # absurd: probably a unit mistake
        ("slippage", "fixed_bps", -0.1),
        ("slippage", "stress_multiplier", 0.5),
        ("funding", "missing_policy", "ignore"),
    ],
)
def test_invalid_costs_rejected(tmp_path, docs, section, key, value):
    docs["costs.yaml"][section][key] = value
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, docs))


def test_unknown_keys_rejected(tmp_path, docs):
    docs["costs.yaml"]["fees"]["taker_fee"] = 0.001  # typo'd key must not be silently ignored
    with pytest.raises(ValidationError, match="taker_fee"):
        load_config(_write(tmp_path, docs))


def test_overlapping_splits_rejected(tmp_path, docs):
    docs["splits.yaml"]["validation"]["start"] = "2023-01-01"  # before development ends
    with pytest.raises(ValidationError, match="development must end"):
        load_config(_write(tmp_path, docs))


def test_test_period_overlapping_forward_rejected(tmp_path, docs):
    docs["splits.yaml"]["forward_start"] = "2026-01-01"
    with pytest.raises(ValidationError, match="test must end"):
        load_config(_write(tmp_path, docs))


def test_period_with_start_after_end_rejected(tmp_path, docs):
    docs["splits.yaml"]["test"]["end"] = "2024-06-01"
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, docs))


def test_naive_datetime_in_config_rejected(tmp_path, docs):
    docs["splits.yaml"]["forward_start"] = "2026-07-01T00:00:00"  # no offset
    with pytest.raises(ValidationError, match="naive"):
        load_config(_write(tmp_path, docs))


def test_decision_timeframe_must_be_a_feature_timeframe(tmp_path, docs):
    docs["default.yaml"]["market"]["feature_timeframes"] = ["5m", "15m", "4h"]
    with pytest.raises(ValidationError, match="decision_timeframe"):
        load_config(_write(tmp_path, docs))


def test_context_must_be_longer_than_decision(tmp_path, docs):
    docs["default.yaml"]["market"]["context_timeframe"] = "15m"
    with pytest.raises(ValidationError, match="longer"):
        load_config(_write(tmp_path, docs))


def test_config_is_immutable():
    cfg = load_config()
    with pytest.raises(ValidationError):
        cfg.costs.fees.taker_fee_bps = 0.0  # type: ignore[misc]


def test_config_hash_is_stable_and_sensitive(tmp_path, docs):
    base = load_config()
    assert base.config_hash() == load_config().config_hash()

    docs["costs.yaml"]["fees"]["taker_fee_bps"] = 4.0
    changed = load_config(_write(tmp_path, docs))
    assert changed.config_hash() != base.config_hash()


def test_config_hash_ignores_machine_specific_data_dir(tmp_path, docs):
    docs["default.yaml"]["data"]["data_dir"] = str(tmp_path / "elsewhere")
    moved = load_config(_write(tmp_path, docs))
    assert moved.config_hash() == load_config().config_hash()

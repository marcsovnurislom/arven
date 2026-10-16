"""Backups of the forward signal record and runtime state (``arven backup``)."""

import zipfile
from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from arven.live.backup import make_backup


def _tree(tmp_path):
    data, config = tmp_path / "data", tmp_path / "config"
    (data / "signals" / "s6").mkdir(parents=True)
    (data / "signals" / "s6" / "signals.jsonl").write_bytes(b'{"id": 1}\n')
    (data / "live").mkdir()
    (data / "live" / "state.json").write_text("{}", encoding="utf-8")
    (data / "live" / "live.lock").write_text("123", encoding="utf-8")
    (data / "paper" / "20261016T000000Z-abc").mkdir(parents=True)
    (data / "paper" / "20261016T000000Z-abc" / "decisions.jsonl").write_text("x", encoding="utf-8")
    (data / "paper" / "strategies_cursor.json").write_text("{}", encoding="utf-8")
    (data / "raw").mkdir()
    (data / "raw" / "big.zip").write_bytes(b"0" * 100)
    config.mkdir()
    (config / "live.yaml").write_text("strategies: []\n", encoding="utf-8")
    return data, config


def test_backup_holds_state_and_config_but_not_locks_runs_or_raw_data(tmp_path):
    data, config = _tree(tmp_path)
    res = make_backup(data, config, datetime(2026, 10, 16, 9, 0, tzinfo=UTC))
    assert res.path.name == "arven-20261016T090000Z.zip"
    names = set(zipfile.ZipFile(res.path).namelist())
    assert names == {
        "data/signals/s6/signals.jsonl", "data/live/state.json", "data/paper/strategies_cursor.json", "config/live.yaml",
    }
    assert res.files == 4 and not res.database_included
    assert zipfile.ZipFile(res.path).read("data/signals/s6/signals.jsonl") == b'{"id": 1}\n'
    assert not list((data / "backups").glob("*.part"))


def test_only_the_newest_archives_are_kept(tmp_path):
    data, config = _tree(tmp_path)
    t0 = datetime(2026, 10, 16, tzinfo=UTC)
    for i in range(4):
        res = make_backup(data, config, t0 + timedelta(hours=i), keep=2)
    kept = sorted(p.name for p in (data / "backups").glob("arven-*.zip"))
    assert kept == ["arven-20261016T020000Z.zip", "arven-20261016T030000Z.zip"]
    assert [p.name for p in res.removed] == ["arven-20261016T010000Z.zip"]
    with pytest.raises(ValueError):
        make_backup(data, config, t0, keep=0)


def test_database_copy_is_readable(tmp_path):
    data, config = _tree(tmp_path)
    db = data / "arven.duckdb"
    con = duckdb.connect(str(db))
    con.execute("create table t as select 42 as x")
    con.close()
    res = make_backup(data, config, datetime(2026, 10, 16, tzinfo=UTC), database_path=db)
    assert res.database_included
    out = tmp_path / "restore"
    zipfile.ZipFile(res.path).extract("data/arven.duckdb", out)
    con = duckdb.connect(str(out / "data" / "arven.duckdb"), read_only=True)
    assert con.execute("select x from t").fetchone() == (42,)
    con.close()
    assert not (data / "backups" / "arven.duckdb.copy").exists()

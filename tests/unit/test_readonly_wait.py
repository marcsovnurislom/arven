"""open_readonly: fails at once by default (the web API answers 503), retries while ARVEN_DB_WAIT_SECONDS allows."""

from __future__ import annotations

import duckdb
import pytest

import arven.data.reader as reader


def _flaky(fails: int):
    calls = {"n": 0}

    def connect(path, read_only=False):
        calls["n"] += 1
        if calls["n"] <= fails:
            raise duckdb.IOException("Could not set lock on file")
        return "con"

    return connect, calls


def test_default_fails_immediately(monkeypatch):
    connect, calls = _flaky(1)
    monkeypatch.setattr(reader.duckdb, "connect", connect)
    monkeypatch.delenv("ARVEN_DB_WAIT_SECONDS", raising=False)
    with pytest.raises(duckdb.IOException):
        reader.open_readonly("x.duckdb")
    assert calls["n"] == 1


def test_waits_for_the_writer_when_asked(monkeypatch):
    connect, calls = _flaky(2)
    monkeypatch.setattr(reader.duckdb, "connect", connect)
    monkeypatch.setattr(reader.time, "sleep", lambda s: None)
    monkeypatch.setenv("ARVEN_DB_WAIT_SECONDS", "60")
    assert reader.open_readonly("x.duckdb") == "con" and calls["n"] == 3


def test_writer_connect_waits_for_readers_when_asked(monkeypatch, tmp_path):
    """arven.data.storage.db.connect(wait_seconds=...): the live loop's writes wait for the web app's reads (2026-10-27)."""
    import arven.data.storage.db as db

    real = duckdb.connect
    calls = {"n": 0}

    def flaky(path, *a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise duckdb.IOException("Could not set lock on file")
        return real(path, *a, **k)

    monkeypatch.setattr(db.duckdb, "connect", flaky)
    monkeypatch.setattr(db.time, "sleep", lambda s: None)
    with pytest.raises(duckdb.IOException):
        db.connect(tmp_path / "a.duckdb")  # default: no wait
    calls["n"] = 0
    con = db.connect(tmp_path / "b.duckdb", wait_seconds=60)
    assert calls["n"] == 3
    con.close()

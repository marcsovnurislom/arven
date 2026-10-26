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

"""Append-only persistence for :class:`~arven.engine.signal.EngineSignal` and
:class:`~arven.engine.signal_events.SignalUpdate` - the same JSONL-index idiom already used throughout
this project (``arven.paper.runs``'s ``runs.jsonl``/``decisions.jsonl``, ``arven.news``'s tables) rather
than a new DuckDB schema: this is a simple, append-only, human-readable log, not a queryable dataset.

Layout under ``root`` (typically ``<data_dir>/signals``): ``<strategy_id>/signals.jsonl`` (one
:class:`EngineSignal` per line, in the order it was announced) and ``<strategy_id>/updates.jsonl`` (one
:class:`SignalUpdate` per line). Nothing here computes a signal or a grade - this module only writes down
and reads back what was already decided.
"""

from __future__ import annotations

import json
from pathlib import Path

from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind


def strategy_dir(root: Path, strategy_id: str) -> Path:
    return root / strategy_id


def append_signal(root: Path, signal: EngineSignal) -> None:
    path = strategy_dir(root, signal.strategy_id) / "signals.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(signal.to_dict(), sort_keys=True) + "\n")


def append_update(root: Path, strategy_id: str, update: SignalUpdate) -> None:
    path = strategy_dir(root, strategy_id) / "updates.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(update.to_dict(), sort_keys=True) + "\n")


def _signal_from_dict(d: dict) -> EngineSignal:
    v = d["versions"]
    sig = EngineSignal(
        symbol=d["symbol"],
        side=d["side"],
        strategy_id=d["strategy_id"],
        strategy_version=d["strategy_version"],
        grade=Grade(d["grade"]),
        event_time_ms=d["event_time_ms"],
        entry_reference=d["entry_reference"],
        stop=d["stop"],
        tp_ladder=tuple(TPLevel(r, f, p) for r, f, p in d["tp_ladder"]),
        risk_fraction=d["risk_fraction"],
        confidence=d["confidence"],
        regime=d["regime"],
        reasons=tuple(d["reasons"]),
        risk_checks=tuple(d["risk_checks"]),
        versions=SignalVersions(v["feature_version"], v["config_hash"], v["git_commit"], v.get("data_fingerprint")),
        max_holding_minutes=d["max_holding_minutes"],
        entry_type=d.get("entry_type", "market"),
        valid_until_ms=d.get("valid_until_ms"),
    )
    if sig.signal_id != d["signal_id"]:
        raise ValueError(f"stored signal_id {d['signal_id']} does not match its own recomputed content hash {sig.signal_id}")
    return sig


def read_signals(root: Path, strategy_id: str) -> list[EngineSignal]:
    path = strategy_dir(root, strategy_id) / "signals.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return [_signal_from_dict(json.loads(line)) for line in lines] if lines else []


def read_updates(root: Path, strategy_id: str) -> list[SignalUpdate]:
    path = strategy_dir(root, strategy_id) / "updates.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return [
        SignalUpdate(d["signal_id"], d["time_ms"], SignalUpdateKind(d["kind"]), d["detail"])
        for d in (json.loads(line) for line in lines)
    ] if lines else []

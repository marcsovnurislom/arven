"""Pure data-loading helpers for the dashboard (no ``streamlit`` import here, so these stay unit-testable
without a display). Every function only reads what an earlier stage's own run already wrote to disk -
nothing here recomputes a metric, a trade, or a decision (CLAUDE.md rule 9).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def list_runs(index_path: Path) -> list[dict[str, Any]]:
    """``runs.jsonl`` entries, newest first (the file is append-only, oldest-first on disk)."""
    if not index_path.exists():
        return []
    lines = index_path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in reversed(lines)] if lines else []


def run_dir_for(root: Path, entry: dict[str, Any]) -> Path:
    """Backtest index entries carry their own ``dir`` (baseline runs nest under ``baselines-<id>/...``);
    paper index entries don't, since a paper run's directory is always just its ``run_id`` under ``root``."""
    rel = entry.get("dir") or entry["run_id"]
    return root / rel


def load_manifest(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "run.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_csv(run_dir: Path, name: str) -> pd.DataFrame:
    path = run_dir / name
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def load_decisions(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "decisions.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines] if lines else []

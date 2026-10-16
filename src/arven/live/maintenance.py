"""Daily housekeeping of the always-on process: a backup and a retention rule for the hourly paper-run directories.

Every hourly Stage 8 ``paper run`` writes a full replay of the forward period to ``data/paper/<run_id>/`` (1.6 MB in
October 2026 and growing with the period), so the folder grows by tens of MB a day. Those directories are
re-computable artifacts (the run is deterministic from the database and the code), and ``data/paper/runs.jsonl``
keeps every run's id, window, ``result_hash`` and git commit for good. :func:`prune_paper_runs` therefore keeps the
newest ``keep_recent`` run directories plus the last run of every UTC day and removes the rest. The index, the
signal store and everything else in ``data/paper`` are never touched.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

RUN_DIR = re.compile(r"^(\d{8})T\d{6}Z-[0-9a-f]+$")  # e.g. 20261016T082924Z-b5abd36a


@dataclass(frozen=True)
class PruneResult:
    kept: tuple[str, ...]
    removed: tuple[str, ...]
    bytes_freed: int


def _size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def plan_prune(names: list[str], keep_recent: int) -> tuple[list[str], list[str]]:
    """``(kept, removed)`` among run-directory names (only names matching the run-id pattern are considered)."""
    if keep_recent < 1:
        raise ValueError("keep_recent must be >= 1")
    runs = sorted(n for n in names if RUN_DIR.match(n))  # the run id starts with its UTC creation time: sorts by time
    keep = set(runs[-keep_recent:])
    last_of_day: dict[str, str] = {}
    for n in runs:
        last_of_day[RUN_DIR.match(n).group(1)] = n  # type: ignore[union-attr]  # later runs overwrite earlier ones
    keep |= set(last_of_day.values())
    return [n for n in runs if n in keep], [n for n in runs if n not in keep]


def prune_paper_runs(root: Path, keep_recent: int = 48, *, apply: bool = True) -> PruneResult:
    """Remove old hourly run directories under ``root`` (``data/paper``); ``apply=False`` only reports."""
    if not root.is_dir():
        return PruneResult((), (), 0)
    kept, removed = plan_prune([p.name for p in root.iterdir() if p.is_dir()], keep_recent)
    freed = 0
    for name in removed:
        path = root / name
        freed += _size(path)
        if apply:
            shutil.rmtree(path)
    return PruneResult(tuple(kept), tuple(removed), freed)


__all__ = ["PruneResult", "plan_prune", "prune_paper_runs"]

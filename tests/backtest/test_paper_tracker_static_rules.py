"""Module boundary of the Phase 4 paper tracker (``src/arven/backtest/paper_tracker.py``), mirroring
``tests/backtest/test_event_engine_static_rules.py``'s Phase 3 pattern: it lives in ``arven.backtest`` and
imports *from* ``arven.engine`` (never the reverse), and never touches the decision/risk/strategies/regime
stack."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "arven"
TRACKER = SRC / "backtest" / "paper_tracker.py"


def _import_nodes(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, None
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                yield node.module, a.name


def test_tracker_exists():
    assert TRACKER.is_file()


def test_tracker_only_uses_the_ladder_and_signal_vocabulary_of_the_engine():
    used = {m for m, _ in _import_nodes(TRACKER) if m == "arven.engine" or m.startswith("arven.engine.")}
    assert used and used <= {"arven.engine.ladder", "arven.engine.signal", "arven.engine.signal_events"}, used


def test_tracker_never_imports_the_decision_stack():
    forbidden = ("arven.decision", "arven.risk", "arven.strategies", "arven.regime", "arven.ml")
    bad = [m for m, _ in _import_nodes(TRACKER) if m.startswith(forbidden)]
    assert not bad, bad


def test_engine_still_never_imports_arven_backtest():
    """Re-asserted here (belt and suspenders): adding the tracker to ``arven.backtest`` must not have
    created a reverse dependency - ``tests/engine/test_engine_static_rules.py`` is the primary guard."""
    for path in (SRC / "engine").rglob("*.py"):
        bad = [m for m, _ in _import_nodes(path) if m.startswith("arven.backtest")]
        assert not bad, f"{path}: {bad}"


def test_no_later_stage_package_imports_the_tracker():
    for package in ("strategies", "risk", "regime", "decision", "ml", "features", "data", "core", "engine"):
        for path in (SRC / package).rglob("*.py"):
            bad = [m for m, _ in _import_nodes(path) if m.startswith("arven.backtest.paper_tracker")]
            assert not bad, f"{path}: {bad}"

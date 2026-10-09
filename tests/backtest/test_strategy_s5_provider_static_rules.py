"""Module boundary of the Strategy S5 S5 provider (`src/arven/backtest/strategy_s5_provider.py`), mirroring
`test_paper_tracker_static_rules.py`'s Phase 4 pattern: it lives in `arven.backtest` and imports *from*
`arven.engine` (never the reverse), and never touches the decision/risk/strategies/regime stack."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "arven"
PROVIDER = SRC / "backtest" / "strategy_s5_provider.py"


def _import_nodes(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, None
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                yield node.module, a.name


def test_provider_exists():
    assert PROVIDER.is_file()


def test_provider_only_uses_the_engine_vocabulary_it_needs():
    used = {m for m, _ in _import_nodes(PROVIDER) if m == "arven.engine" or m.startswith("arven.engine.")}
    allowed = {"arven.engine.errors", "arven.engine.features", "arven.engine.grading", "arven.engine.multitf", "arven.engine.signal", "arven.engine.spec", "arven.engine.strategy_s5"}
    assert used and used <= allowed, used


def test_provider_never_imports_the_decision_stack():
    forbidden = ("arven.decision", "arven.risk", "arven.strategies", "arven.regime", "arven.ml")
    bad = [m for m, _ in _import_nodes(PROVIDER) if m.startswith(forbidden)]
    assert not bad, bad


def test_engine_still_never_imports_arven_backtest():
    for path in (SRC / "engine").rglob("*.py"):
        bad = [m for m, _ in _import_nodes(path) if m.startswith("arven.backtest")]
        assert not bad, f"{path}: {bad}"


def test_no_later_stage_package_imports_the_provider():
    for package in ("strategies", "risk", "regime", "decision", "ml", "features", "data", "core", "engine"):
        for path in (SRC / package).rglob("*.py"):
            bad = [m for m, _ in _import_nodes(path) if m.startswith("arven.backtest.strategy_s5_provider")]
            assert not bad, f"{path}: {bad}"

"""Module boundaries of S7's plan (`arven.engine.strategy_s7_plan`) and simulator (`arven.backtest.strategy_s7_sim`),
the same pattern as the S4-S6 provider rules: ``backtest -> engine`` only, never the decision/risk stack."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "arven"
SIM = SRC / "backtest" / "strategy_s7_sim.py"
PLAN = SRC / "engine" / "strategy_s7_plan.py"
FORBIDDEN = ("arven.decision", "arven.risk", "arven.strategies", "arven.regime", "arven.ml", "arven.news", "arven.llm")


def _modules(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_plan_is_pure_engine_code():
    arven = {m for m in _modules(PLAN) if m.startswith("arven")}
    assert arven == {"arven.engine.strategy_s7"}, arven


def test_simulator_uses_only_the_engine_vocabulary_it_needs():
    used = {m for m in _modules(SIM) if m.startswith("arven.engine")}
    allowed = {"arven.engine.grading", "arven.engine.ladder", "arven.engine.signal", "arven.engine.signal_events", "arven.engine.strategy_s7", "arven.engine.strategy_s7_plan"}
    assert used and used <= allowed, used
    assert not [m for m in _modules(SIM) if m.startswith(FORBIDDEN)]


def test_nothing_below_the_backtest_imports_the_simulator():
    for package in ("strategies", "risk", "regime", "decision", "ml", "features", "data", "core", "engine"):
        for path in (SRC / package).rglob("*.py"):
            assert not [m for m in _modules(path) if m.startswith("arven.backtest.strategy_s7_sim")], path

"""Module-boundary check for the new engine (ARVEN_MASTER_PROMPT.md phase 1): it must not depend on the
legacy decision/risk/strategies/regime/backtest stack, so it can be built and tested in isolation without
any risk of silently coupling to - or breaking - the golden Stage 5 result."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "arven"


def _imports(tree: ast.AST) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
    return out


def test_engine_never_imports_the_legacy_decision_stack():
    forbidden = ("arven.decision", "arven.risk", "arven.strategies", "arven.regime", "arven.backtest")
    for path in (SRC / "engine").rglob("*.py"):
        bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith(forbidden)]
        assert not bad, f"{path}: {bad}"

"""Module-boundary check for the new engine (ARVEN_MASTER_PROMPT.md phase 1): it must not depend on the
legacy decision/risk/strategies/regime/backtest stack, so it can be built and tested in isolation without
any risk of silently coupling to - or breaking - the golden Stage 5 result.

Phase 3 note (kept unchanged on purpose): the event-driven backtest loop must reuse the Stage 4 execution
layer (``arven.backtest.execution.Simulator`` and friends), which would collide with this rule if the loop
lived here. It therefore lives in ``arven.backtest.event_engine`` and imports *from* ``arven.engine`` (clock
and events only) - the dependency points ``backtest -> engine``, never the reverse, so this blanket rule still
holds verbatim. The loop's own precise boundary is pinned in ``tests/backtest/test_event_engine_static_rules.py``."""

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

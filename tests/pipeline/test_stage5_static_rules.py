"""Import boundaries for the Stage 5 packages (regime, strategies, decision, risk).

Mirrors the Stage 3/4 static-rule tests: each package may depend only on what the architecture allows, so
"strategies do not know about risk", "risk does not know which strategy fired" and "regime detection is
separate from strategy logic" (CLAUDE.md rule 7, and the user's explicit Stage 5 separation rules) are
enforced mechanically, not just by convention. Nothing here bypasses the Stage 4 execution engine: only
``arven.backtest.margin`` (a pure function) may be imported outside ``arven.backtest.provider``/``types``.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "arven"

PACKAGE_RULES: dict[str, tuple[str, ...]] = {
    # package -> prefixes it must NOT import
    "regime": ("arven.strategies", "arven.decision", "arven.risk", "arven.backtest.engine", "arven.backtest.execution", "arven.backtest.accounting", "arven.data", "arven.features", "duckdb"),
    "strategies": ("arven.risk", "arven.decision", "arven.regime", "arven.backtest.engine", "arven.backtest.execution", "arven.backtest.accounting", "arven.backtest.margin", "arven.data", "arven.features", "duckdb"),
    "risk": ("arven.strategies", "arven.backtest.engine", "arven.backtest.execution", "arven.backtest.accounting", "arven.data", "arven.features", "duckdb"),
    "decision": ("arven.backtest.engine", "arven.backtest.execution", "arven.backtest.accounting", "arven.backtest.margin", "arven.data", "arven.features", "duckdb"),
}


def _imports(tree: ast.AST) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
            if node.module == "arven":
                out += [f"arven.{a.name}" for a in node.names]
    return out


@pytest.mark.parametrize("package,forbidden", PACKAGE_RULES.items())
def test_package_import_boundaries(package, forbidden):
    problems = []
    for path in (SRC / package).rglob("*.py"):
        bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith(forbidden)]
        if bad:
            problems.append(f"{path.relative_to(SRC)}: {bad}")
    assert not problems, "\n".join(problems)


def test_risk_engine_imports_only_the_pure_margin_function_not_the_engine():
    tree = ast.parse((SRC / "risk" / "engine.py").read_text(encoding="utf-8"))
    backtest_imports = [m for m in _imports(tree) if m.startswith("arven.backtest")]
    assert set(backtest_imports) <= {"arven.backtest.margin", "arven.backtest.provider", "arven.core.backtest_config"}


def test_strategies_never_import_the_backtester_or_risk_or_decision():
    for path in (SRC / "strategies").rglob("*.py"):
        bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith(("arven.backtest.engine", "arven.backtest.execution", "arven.risk", "arven.decision"))]
        assert not bad, f"{path}: {bad}"


def test_decision_engine_never_sees_the_portfolio_type():
    """DecisionEngine.decide must not accept a PortfolioSnapshot: the decision layer is portfolio-blind by
    design (architecture: decision -> risk, never decision -> portfolio)."""
    import inspect

    from arven.decision.engine import DecisionEngine

    sig = inspect.signature(DecisionEngine.decide)
    assert "portfolio" not in sig.parameters and "PortfolioSnapshot" not in str(sig)


def test_lower_layers_never_import_stage5_packages():
    for package in ("features", "data", "core", "backtest"):
        for path in (SRC / package).rglob("*.py"):
            bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith(("arven.regime", "arven.strategies", "arven.decision", "arven.risk"))]
            assert not bad, f"{path}: {bad}"


def test_the_live_decision_path_never_imports_the_post_hoc_reports_module():
    """arven.reports depends on arven.decision (and arven.backtest.engine) for post-hoc analysis; the
    dependency must be one-directional, or a report could accidentally influence a live decision."""
    for package in ("regime", "strategies", "decision", "risk"):
        for path in (SRC / package).rglob("*.py"):
            bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith("arven.reports")]
            assert not bad, f"{path}: {bad}"

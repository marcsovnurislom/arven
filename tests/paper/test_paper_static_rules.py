"""Module-boundary and reuse-not-duplication checks for Stage 8."""

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
            if node.module == "arven":
                out += [f"arven.{a.name}" for a in node.names]
    return out


def test_no_stage_3_to_7_package_imports_arven_paper():
    """One-directional dependency: paper depends on regime/strategies/decision/risk/ml/wfo/backtest, never
    the reverse."""
    packages = ("regime", "strategies", "risk", "decision", "features", "ml")
    single_files = ("wfo.py", "wfo_runs.py", "runs.py", "ml_runs.py")
    paths = [p for pkg in packages for p in (SRC / pkg).rglob("*.py")] + [SRC / f for f in single_files]
    for path in paths:
        assert path.exists(), path
        imports = _imports(ast.parse(path.read_text(encoding="utf-8")))
        bad = [m for m in imports if m.startswith("arven.paper")]
        assert not bad, f"{path}: {bad}"


def test_paper_never_reimplements_the_backtester_simulator_or_pipeline():
    """paper/runs.py drives the real Backtester only indirectly, through runs.execute_run (which itself
    owns the Backtester/Simulator call) - it defines none of these classes itself."""
    text = (SRC / "paper" / "runs.py").read_text(encoding="utf-8")
    assert "class Backtester" not in text
    assert "class Simulator" not in text
    assert "class Stage5Pipeline" not in text
    assert "def enter(" not in text and "def exit_position(" not in text  # arven.backtest.accounting's job


def test_paper_never_imports_the_accounting_or_execution_internals_directly():
    """paper/runs.py drives everything through the real Backtester (which itself owns Simulator/accounting);
    it never reaches into arven.backtest.execution/accounting on its own."""
    for name in ("runs.py",):
        imports = _imports(ast.parse((SRC / "paper" / name).read_text(encoding="utf-8")))
        bad = [m for m in imports if m.startswith(("arven.backtest.execution", "arven.backtest.accounting"))]
        assert not bad, f"{name}: {bad}"


def test_paper_reuses_the_real_runs_module_for_execute_run_and_make_guard():
    text = (SRC / "paper" / "runs.py").read_text(encoding="utf-8")
    assert "from arven.runs import" in text
    for name in ("execute_run", "make_guard", "LoadedInputs"):
        assert name in text


def test_rest_ingestion_never_imports_private_or_order_endpoints():
    """CLAUDE.md rule 12: no real order execution code. A cheap, durable guard: the REST modules never
    mention an API key header or any Binance order/account endpoint path."""
    for name in ("binance_rest.py",):
        text = (SRC / "data" / "adapters" / name).read_text(encoding="utf-8")
        for forbidden in ("X-MBX-APIKEY", "/fapi/v1/order", "/fapi/v1/account", "/fapi/v2/account", "signature="):
            assert forbidden not in text, f"{name} must never reference {forbidden!r}"
    text = (SRC / "data" / "rest_ingestion.py").read_text(encoding="utf-8")
    for forbidden in ("X-MBX-APIKEY", "/fapi/v1/order", "signature="):
        assert forbidden not in text

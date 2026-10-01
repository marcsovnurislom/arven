"""Module-boundary and reuse-not-duplication checks for Stage 7."""

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


def test_no_stage_3_to_6_package_imports_arven_wfo():
    """One-directional dependency: wfo depends on regime/strategies/decision/risk/ml/backtest, never the
    reverse - mirrors the existing rule that regime/strategies/risk never import arven.ml."""
    for package in ("regime", "strategies", "risk", "decision", "features", "ml"):
        for path in (SRC / package).rglob("*.py"):
            imports = _imports(ast.parse(path.read_text(encoding="utf-8")))
            bad = [m for m in imports if m.startswith("arven.wfo")]
            assert not bad, f"{path}: {bad}"


def test_wfo_never_reimplements_generate_folds_or_purge_embargo():
    """Stage 7 must import these from arven.ml.splits, never define a local equivalent (spec: reuse, don't
    duplicate)."""
    text = (SRC / "wfo.py").read_text(encoding="utf-8") + (SRC / "wfo_runs.py").read_text(encoding="utf-8")
    assert "from arven.ml.splits import" in text
    assert "generate_folds" in text
    assert "def generate_folds(" not in text
    assert "def purge_and_embargo_train_mask(" not in text
    assert "def validation_mask(" not in text
    assert "def select_threshold(" not in text
    assert "def fit_isotonic(" not in text


def test_wfo_never_imports_the_execution_engine_or_duckdb_directly():
    for name in ("wfo.py", "wfo_runs.py"):
        imports = _imports(ast.parse((SRC / name).read_text(encoding="utf-8")))
        bad = [m for m in imports if m.startswith(("arven.backtest.execution", "arven.backtest.accounting")) or m == "duckdb"]
        assert not bad, f"{name}: {bad}"


def test_wfo_reuses_the_real_stage5_pipeline_not_a_copy():
    text = (SRC / "wfo_runs.py").read_text(encoding="utf-8")
    assert "from arven.decision.pipeline import Stage5Pipeline" in text
    assert "class Stage5Pipeline" not in text

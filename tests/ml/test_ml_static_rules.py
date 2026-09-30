"""Import boundaries for arven.ml: reuses SplitGuard/FeatureView rather than a parallel leakage-prevention
system, never bypasses Stage 4 execution, and keeps the Stage 6 dependency (lightgbm) contained (constraint
#12)."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "arven"
ML_FILES = sorted((SRC / "ml").glob("*.py"))

# ml/ may reuse pure Stage 4 functions (costs, margin, marketdata, provider types) and Stage 5's regime/
# strategies/decision types (it operates *on* their output) - but never the execution/accounting engine
# itself, and never risk.engine directly (labels.py computes its own barrier resolution; the one place
# arven.risk is legitimately used is dataset.py, which replays the real RiskEngine, not a copy of it).
FORBIDDEN_EVERYWHERE = ("arven.backtest.engine", "arven.backtest.execution", "arven.backtest.accounting", "duckdb")


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


@pytest.mark.parametrize("path", ML_FILES, ids=lambda p: p.name)
def test_ml_never_imports_the_execution_engine_or_duckdb_directly(path):
    bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith(FORBIDDEN_EVERYWHERE)]
    assert not bad, f"{path.name}: {bad}"


def test_only_labels_and_model_import_lightgbm_the_ml_dependency_is_contained():
    """Constraint #12: the Stage 6 dependency boundary must be clean - the `import lightgbm` statement
    itself appears only in arven.ml.model (artifact.py imports it too, for the version string recorded in
    every manifest, and train.py needs the family name "lightgbm" as a string/dict key, not the package)."""
    allowed = {"model.py", "artifact.py"}
    for path in ML_FILES:
        imports = _imports(ast.parse(path.read_text(encoding="utf-8")))
        if "lightgbm" in imports and path.name not in allowed:
            assert False, f"{path.name} imports the lightgbm package directly; only {allowed} should"


def test_regime_strategies_risk_never_import_lightgbm_or_arven_ml():
    for package in ("regime", "strategies", "risk", "decision"):
        for path in (SRC / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = _imports(tree)
            assert "lightgbm" not in imports, f"{path}: imports lightgbm"
            bad = [m for m in imports if m.startswith("arven.ml")]
            assert not bad, f"{path}: {bad}"


def test_labels_module_is_never_imported_by_features():
    """Architecture rule 6, extended: ml/labels.py (forward-looking) is not reachable from features/."""
    for path in (SRC / "features").rglob("*.py"):
        bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith("arven.ml")]
        assert not bad, f"{path}: {bad}"


def test_dataset_module_reuses_the_real_risk_engine_not_a_copy():
    """Constraint #11: dataset.py must import the real arven.risk.engine.RiskEngine, not reimplement rules."""
    text = (SRC / "ml" / "dataset.py").read_text(encoding="utf-8")
    assert "from arven.risk.engine import RiskEngine" in text
    assert "def apply(" not in text  # no locally-defined risk-rule method shadowing the real one


def test_splits_module_is_date_agnostic_taking_only_plain_ms_boundaries():
    """splits.py must not import SplitGuard/AllowedWindow or the app config: it takes plain integer ms
    boundaries and returns folds, nothing more - the actual development/validation/test dates live only in
    config/splits.yaml, resolved through SplitGuard by the caller (arven.ml_runs), not by this module."""
    import inspect

    from arven.ml.splits import generate_folds

    tree = ast.parse((SRC / "ml" / "splits.py").read_text(encoding="utf-8"))
    imports = _imports(tree)
    assert not any(m.startswith(("arven.core.splitguard", "arven.core.config")) for m in imports)
    sig = inspect.signature(generate_folds)
    assert list(sig.parameters) == ["window_start_ms", "window_end_ms", "min_train_months", "retrain_interval_months"]

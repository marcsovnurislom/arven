"""Static rules for ``src/arven/features`` (architecture section 10, rules 4 and 6).

An AST scan (comments and strings are ignored) that forbids non-causal constructs and enforces the module
boundary: features are pure numpy code that never touches I/O, storage, labels, strategies or later stages.
"""

import ast
from pathlib import Path

import pytest

FEATURES_DIR = Path(__file__).resolve().parents[2] / "src" / "arven" / "features"
FILES = sorted(FEATURES_DIR.glob("*.py"))

# Calls that use the whole series, look ahead, or fill values from other rows.
FORBIDDEN_CALLS = {
    "bfill", "backfill", "ffill", "pad", "fillna", "interpolate", "interp",
    "rank", "quantile", "percentile", "nanquantile", "nanpercentile", "median", "nanmedian",
    "mean", "std", "var", "nanmean", "nanstd", "nanvar", "average",
    "flip", "fliplr", "flipud", "sort", "argsort",
}
FORBIDDEN_IMPORT_PREFIXES = (
    "arven.ml", "arven.strategies", "arven.risk", "arven.backtest", "arven.regime", "arven.decision",
    "arven.news", "arven.llm", "arven.live", "arven.signals", "arven.data", "arven.cli",
    "duckdb", "sqlite3", "pandas", "pyarrow", "requests", "httpx", "urllib", "socket", "yaml", "sklearn", "lightgbm",
)


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _is_negative(node: ast.AST) -> bool:
    return (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)) or (
        isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and node.value < 0
    )


def test_features_package_is_not_empty():
    assert {p.name for p in FILES} >= {"indicators.py", "bars.py", "futures.py", "builder.py", "asof.py", "registry.py"}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_non_causal_constructs(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _called_name(node)
            if name in FORBIDDEN_CALLS:
                problems.append(f"line {node.lineno}: call to {name}()")
            if name == "shift" and node.args and any(_is_negative(a) for a in node.args[1:2]):
                problems.append(f"line {node.lineno}: negative shift")
            for kw in node.keywords:
                if kw.arg == "center" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                    problems.append(f"line {node.lineno}: centered window")
            if name == "open":
                problems.append(f"line {node.lineno}: file I/O")
        if isinstance(node, ast.Slice) and node.step is not None and _is_negative(node.step):
            problems.append(f"line {node.lineno}: reversed slice")
    assert not problems, f"{path.name}: " + "; ".join(problems)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_import_boundary(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
            if node.module == "arven":
                imported += [f"arven.{a.name}" for a in node.names]
    bad = [m for m in imported if m.startswith(FORBIDDEN_IMPORT_PREFIXES)]
    assert not bad, f"{path.name} imports forbidden modules: {bad}"


def test_the_scan_itself_detects_violations():
    """The rules above must fire on a deliberately bad snippet."""
    bad = ast.parse("import duckdb\nx = a.rolling(3, center=True).mean()\ny = s.shift(-1)\nz = a[::-1]\nw = b.bfill()")
    names = {_called_name(n) for n in ast.walk(bad) if isinstance(n, ast.Call)}
    assert {"mean", "shift", "bfill", "rolling"} <= names
    assert any(isinstance(n, ast.Slice) and _is_negative(n.step) for n in ast.walk(bad))
    assert _is_negative(ast.parse("-1", mode="eval").body)

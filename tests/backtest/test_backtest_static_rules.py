"""Import and construct boundaries of ``arven.backtest`` (CLAUDE.md rules 7, 8, 10, 12).

The engine is pure numpy/stdlib: no I/O, no database, no wall-clock, no unseeded randomness and nothing from
strategies, risk, regime, ML, data or features. In the other direction, no lower layer may import the backtester.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "arven"
BACKTEST_FILES = sorted((SRC / "backtest").glob("*.py"))

FORBIDDEN_IMPORTS = (
    "duckdb", "sqlite3", "pandas", "pyarrow", "requests", "httpx", "urllib", "socket", "subprocess", "yaml",
    "arven.data", "arven.features", "arven.strategies", "arven.risk", "arven.regime", "arven.ml", "arven.decision",
    "arven.news", "arven.llm", "arven.live", "arven.signals", "arven.cli", "arven.runs",
)


def _imports(tree):
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
            if node.module == "arven":
                out += [f"arven.{a.name}" for a in node.names]
    return out


def test_backtest_package_exists():
    assert {p.name for p in BACKTEST_FILES} >= {"engine.py", "execution.py", "accounting.py", "baselines.py", "metrics.py", "report.py", "provider.py"}


@pytest.mark.parametrize("path", BACKTEST_FILES, ids=lambda p: p.name)
def test_backtest_import_boundary(path):
    bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith(FORBIDDEN_IMPORTS)]
    assert not bad, f"{path.name} imports {bad}"


@pytest.mark.parametrize("path", BACKTEST_FILES, ids=lambda p: p.name)
def test_no_wall_clock_io_or_unseeded_randomness(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name in ("time", "random", "datetime") for a in node.names):
            problems.append(f"line {node.lineno}: imports {[a.name for a in node.names]}")
        if isinstance(node, ast.ImportFrom) and node.module in ("time", "random", "datetime"):
            problems.append(f"line {node.lineno}: from {node.module} import ...")
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name in ("open", "now", "utcnow", "today", "time", "seed", "rand", "randn", "random", "shuffle"):
                problems.append(f"line {node.lineno}: call to {name}()")
            # numpy randomness only through an explicitly seeded Generator (baselines.py)
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute) and f.value.attr == "random" and f.attr not in ("Generator", "PCG64", "SeedSequence"):
                problems.append(f"line {node.lineno}: np.random.{f.attr}")
    assert not problems, f"{path.name}: " + "; ".join(problems)


def test_no_real_order_execution_code():
    """CLAUDE.md rule 12: nothing that could talk to an exchange."""
    for path in BACKTEST_FILES:
        text = path.read_text(encoding="utf-8").lower()
        for word in ("api_key", "apikey", "secret", "/fapi/", "order/test", "newOrder".lower(), "signature"):
            assert word not in text, f"{path.name} mentions {word}"


@pytest.mark.parametrize("package", ["features", "data", "core"])
def test_lower_layers_never_import_the_backtester(package):
    for path in (SRC / package).rglob("*.py"):
        bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith(("arven.backtest", "arven.runs"))]
        assert not bad, f"{path} imports {bad}"


@pytest.mark.parametrize("package", ["strategies", "risk", "regime", "decision", "ml"])
def test_future_stage_packages_may_not_import_the_backtester(package):
    d = SRC / package
    if not d.exists():
        pytest.skip(f"{package} does not exist yet (Stage 5+)")
    for path in d.rglob("*.py"):
        assert not [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith("arven.backtest")], path

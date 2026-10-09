"""Module boundary of the web layer: read-only over stored artifacts, no execution code, nobody imports it back."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "arven"
WEB = SRC / "web"


def _imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_web_never_imports_execution_ingestion_or_decision_code():
    forbidden = ("arven.backtest", "arven.data.download", "arven.data.rest_ingestion", "arven.data.adapters", "arven.risk",
                 "arven.decision", "arven.strategies", "arven.regime", "arven.ml", "arven.paper")
    for path in WEB.rglob("*.py"):
        bad = [m for m in _imports(path) if m.startswith(forbidden)]
        assert not bad, f"{path.name}: {bad}"


def test_web_source_has_no_order_or_exchange_key_vocabulary():
    for path in WEB.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for word in ("place_order", "new_order", "api_secret", "binance_api_key", "/order"):
            assert word not in text, f"{path.name} mentions {word}"


def test_no_other_package_imports_the_web_layer():
    for package in SRC.iterdir():
        if package.name in ("web", "cli.py", "__pycache__") or not package.is_dir():
            continue
        for path in package.rglob("*.py"):
            assert not [m for m in _imports(path) if m.startswith("arven.web")], path

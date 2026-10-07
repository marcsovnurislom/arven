"""Module-boundary checks for Phase 6 (CLAUDE.md rule 9: Telegram message text is formatted from
already-computed data, never a trading decision/indicator/price/size/PnL of its own)."""

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


def test_telegram_never_imports_decision_risk_strategies_regime():
    forbidden = ("arven.decision", "arven.risk", "arven.strategies", "arven.regime", "arven.backtest", "arven.ml")
    for path in (SRC / "telegram").rglob("*.py"):
        bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith(forbidden)]
        assert not bad, f"{path}: {bad}"


def test_no_stage_0_to_8_or_engine_package_imports_telegram():
    packages = ("regime", "strategies", "risk", "decision", "features", "ml", "backtest", "engine")
    for pkg in packages:
        for path in (SRC / pkg).rglob("*.py"):
            bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith("arven.telegram")]
            assert not bad, f"{path}: {bad}"


def test_telegram_client_never_references_an_order_or_account_endpoint():
    text = (SRC / "telegram" / "client.py").read_text(encoding="utf-8")
    for forbidden in ("/order", "fapi"):
        assert forbidden not in text.lower()

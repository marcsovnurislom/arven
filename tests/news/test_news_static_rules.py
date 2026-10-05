"""Module-boundary checks for Stage 9b (CLAUDE.md rule 9: an LLM is never the source of a trading
decision, indicator, price, size, stop or PnL)."""

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


def test_news_and_llm_never_import_decision_risk_strategies_regime_or_backtest():
    forbidden = ("arven.decision", "arven.risk", "arven.strategies", "arven.regime", "arven.backtest")
    for package in ("news", "llm"):
        for path in (SRC / package).rglob("*.py"):
            bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith(forbidden)]
            assert not bad, f"{path}: {bad}"


def test_no_stage_0_to_8_package_imports_arven_news_or_arven_llm():
    """One-directional dependency: today, nothing reads news/llm output at all - a later integration stage
    would be the first caller, and this test would then need a deliberate, reviewed update."""
    packages = ("regime", "strategies", "risk", "decision", "features", "ml", "backtest", "paper")
    for pkg in packages:
        for path in (SRC / pkg).rglob("*.py"):
            bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith(("arven.news", "arven.llm"))]
            assert not bad, f"{path}: {bad}"


def test_news_never_imports_splitguard_or_the_backtest_period_type():
    """Forward-only by construction (see news/__init__.py's module docstring): this package has no notion
    of development/validation/test at all, so there is nothing that could resolve the sealed test period."""
    for path in (SRC / "news").rglob("*.py"):
        bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if "splitguard" in m.lower()]
        assert not bad, path


def test_llm_client_never_references_an_order_or_account_endpoint():
    text = (SRC / "llm" / "anthropic_client.py").read_text(encoding="utf-8")
    for forbidden in ("/v1/order", "account", "trade"):
        assert forbidden not in text.lower()

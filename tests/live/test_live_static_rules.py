"""Module boundaries of the live loop: it sits on top (nothing below imports it), it never talks to an order or
account endpoint, and LLM / news code is never part of a signal (CLAUDE.md rules 7, 9, 12)."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "arven"
LIVE = sorted((SRC / "live").glob("*.py"))


def _modules(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_nothing_below_imports_the_live_loop():
    for package in ("core", "data", "features", "engine", "backtest", "strategies", "regime", "decision", "risk", "ml", "paper", "telegram", "news", "llm"):
        for path in (SRC / package).rglob("*.py"):
            assert not [m for m in _modules(path) if m.startswith("arven.live")], path


def test_live_never_uses_llm_or_news_code():
    for path in LIVE:
        assert not [m for m in _modules(path) if m.startswith(("arven.llm", "arven.news"))], path


def test_no_order_or_account_endpoint_anywhere_in_the_live_path():
    files = [*LIVE, SRC / "data" / "adapters" / "binance_rest.py", SRC / "data" / "rest_ingestion.py"]
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        for bad in ("/fapi/v1/order", "/fapi/v2/account", "/fapi/v1/leverage", "x-mbx-apikey", "signature=", "api_secret"):
            assert bad not in text, (path, bad)


def test_strategies_reuse_the_research_code_instead_of_reimplementing_it():
    text = (SRC / "live" / "strategies.py").read_text(encoding="utf-8")
    for needed in ("detect_setups", "simulate_setup", "process_events", "resolve_signal", "resolve_block", "signal_mask"):
        assert needed in text, needed
    assert "def track_signal" not in text and "def _detect_long" not in text

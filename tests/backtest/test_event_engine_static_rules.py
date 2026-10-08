"""Module boundary of the Phase 3 event-driven backtest loop (``src/arven/backtest/event_engine.py``).

Resolution of the Phase 1/2 rule "``arven.engine`` never imports ``arven.backtest``" against Phase 3's
requirement to reuse the Stage 4 execution layer unchanged: the loop lives in ``arven.backtest`` and imports
*from* ``arven.engine`` (the dependency points ``backtest -> engine`` only), so the Phase 1/2 rule stays
exactly as it was (``tests/engine/test_engine_static_rules.py``). What this file pins down:

- the loop takes from ``arven.engine`` only the clock/event vocabulary (``clock``, ``events``), not the
  feature/view machinery (migrating strategies to ``MultiTFView`` is a later phase);
- it reuses the Stage 4 primitives but never the legacy orchestration: from ``arven.backtest.engine`` it may
  import only the ``BacktestResult`` dataclass (not ``Backtester``/``decision_grid``), and it never imports
  ``arven.backtest.clock`` (the flat-grid ``SimulationClock`` is superseded by ``EventClock``);
- it never touches decision/risk/strategies/regime/ML (also covered package-wide by
  ``test_backtest_static_rules.py``);
- no legacy ``arven.backtest`` module, and no later-stage package, imports the loop or ``arven.engine`` - the
  legacy 1h path (and the golden ``result_hash``) cannot be influenced by the new code.

Phase 4 note: ``arven.backtest.paper_tracker`` (the signal-ladder paper tracker) resolves the same tension
the same way - it also lives in ``arven.backtest`` and imports *from* ``arven.engine`` (its own
``test_paper_tracker_static_rules.py`` pins its precise vocabulary).

Phase 7b note: ``arven.backtest.strategy_s4_provider`` (the S4 ``SignalProvider`` adapter) is a third such
module, same resolution again (its own ``test_strategy_s4_provider_static_rules.py`` pins its precise
vocabulary). ``test_legacy_backtest_modules_never_import_the_engine_or_the_loop`` below therefore excludes
all three new modules, not just the first one, by name - any *other* file in ``arven.backtest``
(``execution.py``, ``engine.py``, ``clock.py``, ``provider.py``, ...) still may not import ``arven.engine``
or any of them.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "arven"
LOOP = SRC / "backtest" / "event_engine.py"
TRACKER = SRC / "backtest" / "paper_tracker.py"
S4_PROVIDER = SRC / "backtest" / "strategy_s4_provider.py"
NEW_MODULES = (LOOP, TRACKER, S4_PROVIDER)


def _import_nodes(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, None
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                yield node.module, a.name


def test_loop_exists():
    assert LOOP.is_file()


def test_loop_uses_only_the_clock_and_event_vocabulary_of_the_engine():
    used = {m for m, _ in _import_nodes(LOOP) if m == "arven.engine" or m.startswith("arven.engine.")}
    assert used and used <= {"arven.engine.clock", "arven.engine.events"}, used


def test_loop_never_reuses_the_legacy_orchestration():
    for module, name in _import_nodes(LOOP):
        assert not module.startswith("arven.backtest.clock"), module
        if module == "arven.backtest.engine":
            assert name == "BacktestResult", f"only BacktestResult may come from arven.backtest.engine, got {name}"
        if module == "arven.backtest":
            assert name not in ("engine", "clock"), name
    tree = ast.parse(LOOP.read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"Backtester", "SimulationClock", "decision_grid"}


def test_loop_never_imports_the_decision_stack():
    forbidden = ("arven.decision", "arven.risk", "arven.strategies", "arven.regime", "arven.ml")
    bad = [m for m, _ in _import_nodes(LOOP) if m.startswith(forbidden)]
    assert not bad, bad


def test_legacy_backtest_modules_never_import_the_engine_or_the_loop():
    for path in sorted((SRC / "backtest").glob("*.py")):
        if path in NEW_MODULES:
            continue
        bad = [
            m
            for m, n in _import_nodes(path)
            if m.startswith(("arven.engine", "arven.backtest.event_engine", "arven.backtest.paper_tracker", "arven.backtest.strategy_s4_provider"))
            or (m == "arven.backtest" and n in ("event_engine", "paper_tracker", "strategy_s4_provider"))
        ]
        assert not bad, f"{path.name}: {bad}"


def test_no_later_stage_package_imports_the_loop():
    for package in ("strategies", "risk", "regime", "decision", "ml", "features", "data", "core", "engine"):
        for path in (SRC / package).rglob("*.py"):
            bad = [m for m, _ in _import_nodes(path) if m.startswith("arven.backtest.event_engine")]
            assert not bad, f"{path}: {bad}"

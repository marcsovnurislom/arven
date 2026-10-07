"""Phase 2 module-boundary checks (on top of ``test_engine_static_rules.py``, which already scans every file
under ``src/arven/engine/`` for the legacy decision/risk/strategies/regime/backtest imports).

- The Phase 2 modules really exist and are among the scanned files (the Phase 1 rule is not vacuous for them).
- The engine reuses only the generic feature primitives (``indicators``, ``asof``), never the frozen Stage 3
  feature-set machinery (``bars``, ``builder``, ``registry``, ...) that feeds the golden ``result_hash``.
- No engine module uses look-ahead-prone pandas idioms (``shift(-n)``, ``bfill``, centered windows).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "src" / "arven" / "engine"
PHASE2 = ("errors.py", "features.py", "multitf.py")
FORBIDDEN = ("arven.decision", "arven.risk", "arven.strategies", "arven.regime", "arven.backtest")
ALLOWED_FEATURE_MODULES = {"arven.features.indicators", "arven.features.asof"}


def _imports(path: Path) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
            if node.module == "arven.features":
                out += [f"arven.features.{a.name}" for a in node.names]
    return out


def test_phase2_modules_exist_and_import_nothing_from_the_legacy_decision_stack():
    for name in PHASE2:
        path = ENGINE / name
        assert path.is_file(), path
        bad = [m for m in _imports(path) if m.startswith(FORBIDDEN)]
        assert not bad, f"{path}: {bad}"


def test_engine_uses_only_generic_feature_primitives():
    for path in ENGINE.rglob("*.py"):
        used = {m for m in _imports(path) if m.startswith("arven.features.")}
        assert used <= ALLOWED_FEATURE_MODULES, f"{path}: {sorted(used - ALLOWED_FEATURE_MODULES)}"


def test_engine_has_no_lookahead_prone_idioms():
    pattern = re.compile(r"shift\(\s*-|\.bfill\(|backfill|center\s*=\s*True")
    for path in ENGINE.rglob("*.py"):
        hits = [ln for ln in path.read_text(encoding="utf-8").splitlines() if pattern.search(ln)]
        assert not hits, f"{path}: {hits}"

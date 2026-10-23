"""The control panel's settings check (scripts/check_config.py): the real config passes, a broken one is refused."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_config", ROOT / "scripts" / "check_config.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def test_the_real_config_passes(capsys):
    assert check.main() == 0
    assert "OK" in capsys.readouterr().out


def test_a_broken_yaml_or_a_bad_parameter_is_refused(tmp_path, capsys):
    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfg)
    live = cfg / "live.yaml"
    text = live.read_text(encoding="utf-8")
    live.write_text(text.replace("      tf: 15m\n", "      tf: 7m\n", 1), encoding="utf-8")  # a timeframe S7 does not know
    assert check.main(str(cfg)) == 1
    assert "ОШИБКА" in capsys.readouterr().out
    live.write_text(text + "\n  - this: [is not yaml\n", encoding="utf-8")
    assert check.main(str(cfg)) == 1


def test_the_guides_example_of_a_new_s7_variant_is_accepted(tmp_path, capsys):
    """docs/ARVEN_BEZ_CLAUDE.md, example 2: pasting that block after s7_trend_break_fib must give a valid config."""
    guide = (ROOT / "docs" / "ARVEN_BEZ_CLAUDE.md").read_text(encoding="utf-8")
    block = guide.split("### Пример 2", 1)[1].split("```yaml\n", 1)[1].split("```", 1)[0]
    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfg)
    live = cfg / "live.yaml"
    text = live.read_text(encoding="utf-8")
    anchor = "  - id: s7_smc\n"
    live.write_text(text.replace(anchor, block + anchor, 1), encoding="utf-8")
    assert check.main(str(cfg)) == 0
    assert "s7_1h (s7, 1h)" in capsys.readouterr().out

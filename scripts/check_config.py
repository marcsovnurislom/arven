"""Check config/live.yaml before a restart (the control panel's "check settings" button): the file parses, every enabled
strategy of every market builds with its parameters, and the Telegram language is known. Prints the result in Russian;
exit code 0 = fine, 1 = an error (the running process keeps its old settings until a restart).

Usage: PYTHONPATH=src python scripts/check_config.py [config_dir]
"""

from __future__ import annotations

import sys

from arven.core.live_config import load_live_config
from arven.live.registry import build_strategies


def main(config_dir: str | None = None) -> int:
    try:
        live = load_live_config(config_dir)
    except Exception as exc:  # noqa: BLE001 - any parse / validation error is shown to the owner as is
        print(f"ОШИБКА в config/live.yaml (файл не читается или значение не того вида):\n  {exc}")
        return 1
    ok = True
    sets = [("BTC", live)] + [(m.title or m.instrument, live.for_market(m)) for m in live.markets if m.enabled]
    for label, cfg in sets:
        try:
            strategies = build_strategies(cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"ОШИБКА в стратегиях рынка {label}:\n  {exc}")
            ok = False
            continue
        print(f"{label}: включено стратегий {len(strategies)}")
        for s in cfg.enabled():
            tf = s.params.get("tf")
            print(f"  - {s.id} ({s.kind}{', ' + str(tf) if tf else ''})")
    off = [s.id for s in live.strategies if not s.enabled]
    if off:
        print(f"Выключены (BTC): {', '.join(off)}")
    print(f"Язык Telegram: {live.telegram.language}; напоминание о новостях за {live.telegram.event_reminder_minutes} мин")
    print("OK" if ok else "Есть ошибки")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))

"""H3 "1000 parallel universes": for every strategy and period of the Strategies page, 1000 random traders who copy
each trade's side, stop distance and R ladder but enter at random 1m bars of the same period (``arven.backtest.universes``).

Inputs are the exported trades (``scripts/strategy_trades_export.py``); the same CFD costs, the same $1000 account rules.
Crowded Shorts is left out (a time exit, no stop / target ladder to copy). Writes
``<research root>/research/universes/<strategy>_<period>.json`` and ``index.json`` - BTC under ``data/``, gold under
``data/markets/XAUUSD/`` - each with the seed, draws, git commit, rules and costs (CLAUDE.md rule 10). The web page only
draws these files. The strategy's own curve is recomputed from its trades with the same account code and must equal the
export (checked here).

Usage: PYTHONPATH=src python scripts/research/universes.py [--instrument XAUUSD] [--draws 1000] [strategy ...]
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import zlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import strategy_trades_export as ex  # noqa: E402

from arven.backtest.universes import (  # noqa: E402
    MIN_TRADES, SKILL_PERCENTILE, RandomTrade, TradeTemplate, equity_curve, percentile_of, thin, universe, verdict,
)

PERIODS = ("development", "validation", "forward")
SKIP = ("crowded_shorts",)
SEED = 7
POINTS = 120  # points kept per curve


def commit() -> str | None:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip() or None


def run(sid: str, period: str, market, draws: int) -> dict | None:
    src = ex.OUT / sid / f"{period}.json"
    if not src.exists():
        return None
    payload = json.loads(src.read_text(encoding="utf-8"))
    trades = payload["trades"]
    templates = [t for t in (TradeTemplate.from_trade(x["side"], x["entry"], x["stop"], x["targets"]) for x in trades) if t is not None]
    if not templates:
        return None
    own = equity_curve([RandomTrade(0, x["risk_per_unit"], x["net_r"]) for x in trades], ex.RULES)
    exported = [ex.RULES.start_equity, *(x["equity_after"] for x in trades)]
    if not np.allclose(own, exported, atol=0.01):
        raise RuntimeError(f"{sid} {period}: the recomputed account differs from the export")
    symbol = ex.APP.market.symbol
    rng = np.random.default_rng([SEED, zlib.crc32(f"{symbol}|{sid}|{period}".encode())])
    finals, total_rs, mean_rs, counts, curves = [], [], [], [], []
    t0 = time.time()
    for _ in range(draws):
        u = universe(templates, market, rng, ex.CFD, symbol)
        c = equity_curve(u, ex.RULES)
        finals.append(c[-1])
        total_rs.append(sum(x.net_r for x in u))
        mean_rs.append(float(np.mean([x.net_r for x in u])) if u else float("nan"))
        counts.append(len(u))
        curves.append([round(v, 2) for v in thin(c, POINTS)])
    strat_final, strat_r = exported[-1], float(sum(x["net_r"] for x in trades))
    pct = percentile_of(strat_final, finals)
    f = np.array(finals)
    out = {
        "market": symbol, "strategy": sid, "title": payload.get("title", sid), "period": period, "period_label": payload.get("period_label", period),
        "draws": draws, "seed": [SEED, zlib.crc32(f"{symbol}|{sid}|{period}".encode())], "git_commit": commit(),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"), "costs": "cfd",
        "account_rules": {"start_equity": ex.RULES.start_equity, "risk_fraction": ex.RULES.risk_fraction, "min_lot": ex.RULES.min_lot,
                          "lot_step": ex.RULES.lot_step, "max_loss_fraction": ex.RULES.max_loss_fraction},
        "trades": len(trades), "templates": len(templates), "random_trades_mean": float(np.mean(counts)),
        "strategy_result": {"final_equity": strat_final, "total_r": strat_r, "mean_r": strat_r / len(trades), "curve": [round(v, 2) for v in thin(exported, POINTS)]},
        "universes": {
            "final_p05": float(np.percentile(f, 5)), "final_p50": float(np.percentile(f, 50)), "final_p95": float(np.percentile(f, 95)),
            "share_above_start": float(np.mean(f > ex.RULES.start_equity)),
            "total_r_p05": float(np.percentile(total_rs, 5)), "total_r_p50": float(np.percentile(total_rs, 50)), "total_r_p95": float(np.percentile(total_rs, 95)),
            "mean_r_p50": float(np.nanpercentile(mean_rs, 50)), "mean_r_p95": float(np.nanpercentile(mean_rs, 95)),
        },
        "percentile": pct, "percentile_total_r": percentile_of(strat_r, total_rs), "verdict": verdict(pct, len(trades)), "skill_percentile": SKILL_PERCENTILE, "min_trades": MIN_TRADES,
        "finals": [round(v, 2) for v in finals], "curves": curves,
    }
    print(f"{sid:20s} {period:11s} trades {len(trades):4d} -> ${strat_final:8.2f}; universes p5/p50/p95 ${out['universes']['final_p05']:.0f}/"
          f"{out['universes']['final_p50']:.0f}/{out['universes']['final_p95']:.0f}; percentile {pct:5.1f} ({out['verdict']}) [{time.time() - t0:.0f}s]",
          flush=True)
    return out


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["--instrument"]:
        ex.setup(args[1])
        args = args[2:]
    draws = 1000
    if args[:1] == ["--draws"]:
        draws, args = int(args[1]), args[2:]
    root = ex.OUT.parent / "research" / "universes"
    root.mkdir(parents=True, exist_ok=True)
    index = json.loads((ex.OUT / "index.json").read_text(encoding="utf-8"))
    wanted = [s for s in dict.fromkeys(e["strategy"] for e in index) if s not in SKIP and (not args or s in args)]
    entries = []
    for period in PERIODS:
        market = ex.market_for(period)[0].market
        for sid in wanted:
            res = run(sid, period, market, draws)
            if res is None:
                continue
            (root / f"{sid}_{period}.json").write_text(json.dumps(res), encoding="utf-8")
            entries.append({k: res[k] for k in ("strategy", "title", "period", "period_label", "trades", "percentile", "verdict", "draws")}
                           | {"final_equity": res["strategy_result"]["final_equity"], "final_p50": res["universes"]["final_p50"]})
    old = json.loads((root / "index.json").read_text(encoding="utf-8")) if (root / "index.json").exists() and args else []
    keep = [e for e in old if (e["strategy"], e["period"]) not in {(x["strategy"], x["period"]) for x in entries}]
    (root / "index.json").write_text(json.dumps(keep + entries, indent=1), encoding="utf-8")
    print(f"index: {len(keep) + len(entries)} entries -> {root}")


if __name__ == "__main__":
    main()

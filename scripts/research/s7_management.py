"""S7 trade-management study (owner, 2026-10-11): the S7 configuration selected on development, unchanged, with each
management variant of ``arven.engine.strategy_s7_plan.MANAGEMENTS``. Pre-registered rule: the variant with the highest
total R on development (CFD) is chosen; validation and forward (2026-07 -> now, S7 never run there before) are the checks.
Writes ``data/research/s7_management.json``. Research-only."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import s7_study as st  # noqa: E402

from arven.backtest.account_sim import AccountRules, TradeForAccount, replay_account, summarize_account  # noqa: E402
from arven.core.splitguard import BacktestPeriod  # noqa: E402
from arven.engine.strategy_s7_plan import MANAGEMENTS  # noqa: E402


def main() -> None:
    base = json.loads(Path("data/s7_study/development.json").read_text(encoding="utf-8"))["report"]["selected"]["config"]
    out: dict = {"config": base, "managements": list(MANAGEMENTS), "periods": {}}
    for period in (BacktestPeriod.DEVELOPMENT, BacktestPeriod.VALIDATION, BacktestPeriod.FORWARD):
        study = st.Study(period)
        rows = {}
        for mg in MANAGEMENTS:
            cfg = base | {"management": mg}
            row = {}
            for costs, stress in (("cfd", False), ("cfd", True), ("perp", False)):
                m = study.evaluate(cfg, costs, stress)
                outs = sorted((o for o in study.outcomes(cfg, costs, stress) if o.status == "trade"), key=lambda o: o.entry_time_ms)
                acc = summarize_account(replay_account([TradeForAccount(sum(lg.weight * abs(lg.entry_price - lg.stop) for lg in o.legs), o.net_r) for o in outs]), AccountRules())
                row[f"{costs}{'_x4' if stress else ''}"] = {k: m.get(k) for k in ("trades", "total_r", "mean_r", "win_rate", "max_drawdown_r")} | {
                    "account_final": acc["final_equity"], "account_max_dd": acc["max_drawdown"], "skipped_by_5pct_rule": acc["skipped"]}
            rows[mg] = row
            c = row["cfd"]
            print(f"{period.value:11s} {mg:14s} trades {c['trades']:4d} totalR {c['total_r']:+7.2f} meanR {c.get('mean_r') or 0:+.3f} win {c.get('win_rate') or 0:.0%} "
                  f"$1000->{c['account_final']:8.2f} DD {c['account_max_dd']:.1%} | x4 {row['cfd_x4']['total_r']:+.2f} | perp {row['perp']['total_r']:+.2f}")
        out["periods"][period.value] = rows
    dev = out["periods"]["development"]
    chosen = max(MANAGEMENTS, key=lambda mg: dev[mg]["cfd"]["total_r"])
    out["chosen_on_development"] = chosen
    print("\nchosen on development (highest total R, CFD):", chosen)
    for per in ("validation", "forward"):
        a, b = out["periods"][per][chosen]["cfd"], out["periods"][per]["V0"]["cfd"]
        print(f"  {per}: {chosen} {a['total_r']:+.2f} R vs V0 {b['total_r']:+.2f} R")
    Path("data/research/s7_management.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()

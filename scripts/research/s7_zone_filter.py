"""S7 with an SMC-zone entry filter (idea from the development/validation breakdown, 2026-10-11): the development-selected
configuration, unchanged, but a setup is traded only if its entry area holds an iFVG (filter A) or at least three distinct
zone types (filter B). Development and validation are where the idea came from (descriptive only); forward
(2026-07 -> now) is the only clean check. One trade at a time is re-applied after filtering. Research-only."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import s7_study as st  # noqa: E402

from arven.backtest.account_sim import AccountRules, TradeForAccount, replay_account, summarize_account  # noqa: E402
from arven.backtest.strategy_s7_sim import make_context, run_setups  # noqa: E402
from arven.core.splitguard import BacktestPeriod  # noqa: E402

FILTERS = {
    "none (S7 as is)": lambda s: True,
    "A: iFVG in the zone": lambda s: any(z.kind == "ifvg" for z in s.confluence),
    "B: 3+ zone types": lambda s: s.confluence_score >= 3,
}


def main() -> None:
    cfg = json.loads(Path("data/s7_study/development.json").read_text(encoding="utf-8"))["report"]["selected"]["config"]
    out = {}
    for period in (BacktestPeriod.DEVELOPMENT, BacktestPeriod.VALIDATION, BacktestPeriod.FORWARD):
        study = st.Study(period)
        tf, p, tp = st.split(cfg)
        setups = study.setups(tf, p)
        out[period.value] = {}
        for name, keep in FILTERS.items():
            row = {}
            for costs, stress in (("cfd", False), ("cfd", True), ("perp", False)):
                ctx = make_context(study.s7bars(st.TFS[tf]), study.s7bars(st.LOWER[tf]), study.market, study.costs[costs], p, tp,
                                   higher=study.s7bars(st.HIGHER[tf]), stress=stress)
                chosen = [s for s in setups if keep(s)]
                trades = sorted((o for o in run_setups(ctx, chosen) if o.status == "trade"), key=lambda o: o.entry_time_ms)
                r = np.array([o.net_r for o in trades])
                acc = summarize_account(replay_account([TradeForAccount(sum(lg.weight * abs(lg.entry_price - lg.stop) for lg in o.legs), o.net_r) for o in trades]), AccountRules())
                row[f"{costs}{'_x4' if stress else ''}"] = {"setups": len(chosen), "trades": len(r), "total_r": float(r.sum()) if len(r) else 0.0,
                                                           "mean_r": float(r.mean()) if len(r) else 0.0, "win_rate": float(np.mean(r > 0)) if len(r) else 0.0,
                                                           "account_final": acc["final_equity"], "account_max_dd": acc["max_drawdown"]}
            out[period.value][name] = row
            c = row["cfd"]
            print(f"{period.value:11s} {name:22s} trades {c['trades']:4d} totalR {c['total_r']:+7.2f} meanR {c['mean_r']:+.3f} win {c['win_rate']:.0%} "
                  f"$1000->{c['account_final']:8.2f} DD {c['account_max_dd']:.1%} | x4 {row['cfd_x4']['total_r']:+.2f} | perp {row['perp']['total_r']:+.2f}")
    Path("data/research/s7_zone_filter.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()

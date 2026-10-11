"""Export every S7 trade of the development-selected configuration for the web page "S7 trades".

For development and validation: each trade with its setup (line, touches, Fibonacci, zone), entry/stop/targets, exit
reasons, the SMC zones found in the entry area (order block, FVG, iFVG, prior swing levels), net R (CFD costs) and the dollar account replay ($1000, 1 % risk, 0.01 BTC lots, stop loss <= 5 %), plus the 15m
candles around it for the chart. Writes ``data/s7_study/trades_<period>.json``. Read-only research output: the
evaluation itself (``scripts/s7_study.py``) is not re-run or changed. Usage:
    PYTHONPATH=src python scripts/s7_trades_export.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s7_study as st  # noqa: E402

from arven.backtest.account_sim import AccountRules, TradeForAccount, replay_account, summarize_account  # noqa: E402
from arven.core.splitguard import BacktestPeriod  # noqa: E402

BEFORE_BARS, AFTER_BARS, MAX_BARS = 40, 24, 600


def export(period: BacktestPeriod, cfg: dict, rules: AccountRules) -> Path:
    study = st.Study(period)
    tf, p, _ = st.split(cfg)
    setups = study.setups(tf, p)
    outs = [o for o in study.outcomes(cfg, "cfd") if o.status == "trade"]
    outs.sort(key=lambda o: o.entry_time_ms)
    bars = study.bars[st.TFS[tf]]
    t_ms = bars.open_time_ms
    steps = replay_account(
        [TradeForAccount(sum(lg.weight * abs(lg.entry_price - lg.stop) for lg in o.legs), o.net_r) for o in outs], rules)
    trades = []
    for n, (o, step) in enumerate(zip(outs, steps, strict=True), start=1):
        s = setups[o.setup_index]
        leg = o.legs[0]
        risk = abs(leg.entry_price - leg.stop)
        first = max(0, min(s.line.a_index, s.level0_index) - BEFORE_BARS)
        last = min(len(t_ms) - 1, int(np.searchsorted(t_ms, o.exit_time_ms, side="right")) + AFTER_BARS)
        first = max(first, last - MAX_BARS)
        tm = lambda i: int(t_ms[i])  # noqa: E731
        trades.append({
            "n": n, "id": f"{tf}-{tm(s.arm_index)}-{'L' if s.side == 1 else 'S'}", "side": s.side,
            "arm_time_ms": tm(s.arm_index), "entry_time_ms": o.entry_time_ms, "exit_time_ms": o.exit_time_ms,
            "entry": leg.entry_price, "stop": leg.stop,
            "targets": [leg.entry_price + s.side * r * risk for r in leg.ladder_r],
            "exit_reasons": list(leg.reasons), "net_r": o.net_r,
            "size_btc": step.size, "risk_usd": step.risk_usd, "pnl_usd": step.pnl_usd, "equity_after": step.equity_after,
            "skipped": step.skipped,
            "line": {"points": [{"timeMs": tm(s.line.a_index), "price": s.line.a_price}, {"timeMs": tm(s.cross_index), "price": float(s.line.at(s.cross_index))}]},
            "touches": [{"timeMs": tm(i), "price": float(bars.high[i] if s.side == 1 else bars.low[i])} for i in s.touches],
            "level0": {"timeMs": tm(s.level0_index), "price": s.level0}, "level1": {"timeMs": tm(s.level1_index), "price": s.level1},
            "zone": {"low": s.zone_low, "high": s.zone_high},
            "smc_zones": [{"kind": z.kind, "low": z.low, "high": z.high, "timeMs": tm(z.index)} for z in s.confluence],
            "candles": [{"t": tm(i), "o": float(bars.open[i]), "h": float(bars.high[i]), "l": float(bars.low[i]), "c": float(bars.close[i]),
                         "v": float(bars.volume[i]), "complete": True} for i in range(first, last + 1)],
        })
    rs = np.array([o.net_r for o in outs])
    payload = {
        "period": period.value, "window_ms": [study.window.start_ms, study.window.end_ms], "config": cfg, "costs": "cfd",
        "account_rules": {"start_equity": rules.start_equity, "risk_fraction": rules.risk_fraction, "min_lot": rules.min_lot,
                          "lot_step": rules.lot_step, "max_loss_fraction": rules.max_loss_fraction},
        "summary": {"trades": len(outs), "win_rate": float(np.mean(rs > 0)) if len(rs) else 0.0, "total_r": float(rs.sum()),
                    "account": summarize_account(steps, rules)},
        "trades": trades,
    }
    path = study.app.data.data_dir / "s7_study" / f"trades_{period.value}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    acc = payload["summary"]["account"]
    print(f"{period.value}: {len(outs)} trades, $1000 -> ${acc['final_equity']:.2f} ({acc['return']:+.1%}), max DD {acc['max_drawdown']:.1%}, "
          f"skipped {acc['skipped']} -> {path}")
    return path


def main() -> None:
    cfg = json.loads(Path("data/s7_study/development.json").read_text(encoding="utf-8"))["report"]["selected"]["config"]
    for period in (BacktestPeriod.DEVELOPMENT, BacktestPeriod.VALIDATION):
        export(period, cfg, AccountRules())


if __name__ == "__main__":
    main()

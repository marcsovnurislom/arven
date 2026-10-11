"""Export every strategy's trades for the web page "Strategies" (read-only research output; nothing in ``src/`` imports
this). One JSON per strategy and period in ``data/strategy_trades/<strategy>/<period>.json`` plus ``index.json``.

Same schema for all: entry/exit times and prices, stop, targets, exit reasons, net R (CFD costs), the $1000 account
(1 % risk, 0.01 BTC lots, minimum lot only while its stop loss is <= 5 %), and the candles around each trade.

- S4/S5/S6: the recorded development/validation signals (``data/tmp/s*_signals_*.json``) and the forward signal store
  (``data/signals/<id>/signals.jsonl``), replayed on 1m bars with the strategy's own TP ladder, CFD costs, one trade at a
  time - the same replay as ``scripts/s4_variant_study.py`` but with the full ladder.
- S7: the development-selected configuration (``scripts/s7_study.py``), development / validation / forward.
- Crowded Shorts: the pre-registered rules (``scripts/research/cs_sealed_test.py``): development+validation, the already
  evaluated sealed test (displayed only - the access is logged by SplitGuard with that reason), forward.
Usage: PYTHONPATH=src python scripts/strategy_trades_export.py [strategy ...]
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "research"))

from arven.backtest.account_sim import AccountRules, TradeForAccount, replay_account, summarize_account  # noqa: E402
from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate  # noqa: E402
from arven.backtest.paper_tracker import track_signal  # noqa: E402
from arven.core.config import CostsConfig, load_config  # noqa: E402
from arven.core.features_config import load_features_config  # noqa: E402
from arven.core.splitguard import BacktestPeriod  # noqa: E402
from arven.core.timeframes import Timeframe  # noqa: E402
from arven.data.reader import load_feature_inputs, open_readonly  # noqa: E402
from arven.engine.grading import Grade  # noqa: E402
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel  # noqa: E402
from arven.runs import load_inputs, make_guard  # noqa: E402

OUT = Path("data/strategy_trades")
H = 3_600_000
LABELS = {"development": "2020 - mid 2023", "validation": "mid 2023 - 2024", "devval": "2020 - 2024", "test": "2025 - mid 2026 (sealed test)",
          "forward": "Jul 2026 - now (fresh data)"}
TITLES = {"s4_impulse_retest": "S4 Impulse-Retest", "s5_squeeze_breakout": "S5 Squeeze-Breakout", "s6_trend_pullback": "S6 Trend-Pullback",
          "s7": "S7 Trend-Break Fib (owner's method)", "crowded_shorts": "Crowded Shorts (funding + OI)"}

APP, FCFG = load_config(), load_features_config()
GUARD = make_guard(APP)
CFD = CostsConfig.model_validate(yaml.safe_load(Path("config/costs_cfd_justmarkets.yaml").read_text(encoding="utf-8")))


def window(period: str):
    if period == "development":
        return [GUARD.resolve(BacktestPeriod.DEVELOPMENT)]
    if period == "validation":
        return [GUARD.resolve(BacktestPeriod.VALIDATION)]
    if period == "devval":
        return [GUARD.resolve(BacktestPeriod.DEVELOPMENT), GUARD.resolve(BacktestPeriod.VALIDATION)]
    if period == "test":
        return [GUARD.resolve(BacktestPeriod.TEST, allow_sealed=True,
                              reason="display of the already-evaluated Crowded Shorts sealed-test trades on the web page (no new evaluation)")]
    from arven.paper.runs import latest_forward_window_end_ms
    return [GUARD.resolve(BacktestPeriod.FORWARD, end_ms=latest_forward_window_end_ms(APP))]


def market_for(period: str):
    """1m market (and Stage 3 features where needed) for the period, through the guarded loaders."""
    if period == "forward":
        from arven.paper.runs import load_paper_inputs
        return [load_paper_inputs(APP, FCFG, w) for w in window(period)]
    return [load_inputs(APP, FCFG, w) for w in window(period)]


def h1_bars(end_ms: int):
    con = open_readonly(APP.data.database_path)
    try:
        return load_feature_inputs(con, APP, start=APP.data.history_start, end=datetime.fromtimestamp(end_ms / 1000, UTC)).bars[Timeframe.H1]
    finally:
        con.close()


def candles(bars, t0: int, t1: int, before_h: int = 48, after_h: int = 24, cap: int = 500) -> list[dict]:
    t = bars.open_time_ms
    a = int(np.searchsorted(t, t0 - before_h * H)); b = int(np.searchsorted(t, t1 + after_h * H))
    a = max(a, b - cap)
    return [{"t": int(t[i]), "o": float(bars.open[i]), "h": float(bars.high[i]), "l": float(bars.low[i]), "c": float(bars.close[i]), "v": float(bars.volume[i]), "complete": True}
            for i in range(a, min(b, len(t))) if np.isfinite(bars.close[i])]


def finish(sid: str, period: str, trades: list[dict], bars) -> dict:
    trades.sort(key=lambda x: x["entry_time_ms"])
    steps = replay_account([TradeForAccount(x["risk_per_unit"], x["net_r"]) for x in trades], AccountRules())
    for n, (x, st) in enumerate(zip(trades, steps, strict=True), start=1):
        x.update({"n": n, "size_btc": st.size, "risk_usd": st.risk_usd, "pnl_usd": st.pnl_usd, "equity_after": st.equity_after, "skipped": st.skipped,
                  "candles": candles(bars, x["entry_time_ms"], x["exit_time_ms"])})
    r = np.array([x["net_r"] for x in trades])
    payload = {"strategy": sid, "title": TITLES[sid], "period": period, "period_label": LABELS[period], "costs": "cfd",
               "summary": {"trades": len(trades), "win_rate": float(np.mean(r > 0)) if len(r) else 0.0, "total_r": float(r.sum()) if len(r) else 0.0,
                           "account": summarize_account(steps, AccountRules())},
               "trades": trades}
    (OUT / sid).mkdir(parents=True, exist_ok=True)
    (OUT / sid / f"{period}.json").write_text(json.dumps(payload, default=float), encoding="utf-8")
    acc = payload["summary"]["account"]
    print(f"{sid:20s} {period:11s} trades {len(trades):4d} totalR {payload['summary']['total_r']:+7.2f}  $1000 -> {acc['final_equity']:8.2f}")
    return payload


def replay_signals(signals: list[dict], market) -> list[dict]:
    """One trade at a time, the strategy's own ladder, CFD costs (as scripts/s4_variant_study.py replay, full ladder)."""
    fee = taker_fee_rate(CFD)
    free_at, out = 0, []
    for rec in sorted(signals, key=lambda r: r["event_time_ms"]):
        t = int(rec["event_time_ms"])
        if t < free_at:
            continue
        i = market.first_at_or_after(t)
        if i >= len(market) or int(market.time_ms[i]) != t:
            continue
        side = int(rec["side"])
        o, h, lo = float(market.open[i]), float(market.high[i]), float(market.low[i])
        fill = adverse_price(o, side, slippage_fraction(o, h, lo, CFD, False))
        stop = float(rec["stop"])
        risk = abs(fill - stop)
        if risk <= 0 or (fill - stop) * side <= 0:
            continue
        try:
            ladder = tuple(TPLevel.from_r_multiple((p - fill) * side / risk, f, entry=fill, stop=stop, side=side) for _, f, p in rec["ladder"])
            sig = EngineSignal(symbol="BTCUSDT", side=side, strategy_id="replay", strategy_version="v1", grade=Grade.EXPERIMENTAL, event_time_ms=t,
                               entry_reference=fill, stop=stop, tp_ladder=ladder, risk_fraction=0.01, confidence=0.5, regime="replay",
                               reasons=("replay",), risk_checks=(), versions=SignalVersions("v1", "replay", None))
        except ValueError:
            continue  # the fill already passed a target: no valid plan, no trade
        res = track_signal(sig, t, fill, market, CFD)
        if res.resolution is None or not res.resolution.fully_closed:
            break  # still open when the data ends
        closes = [u.time_ms for u in res.updates if u.kind.name in ("TP_HIT", "CLOSED")]
        out.append({"id": f"{t}-{'L' if side == 1 else 'S'}", "side": side, "entry_time_ms": t, "exit_time_ms": max(closes), "entry": fill, "stop": stop,
                    "targets": [float(p) for _, _, p in rec["ladder"]], "exit_reasons": [lg.exit_reason for lg in res.resolution.legs],
                    "net_r": res.resolution.r_multiple - fill * fee / risk, "risk_per_unit": risk})
        free_at = max(closes) + 60_000
    return out


def export_s456(sid: str) -> None:
    short = {"s4_impulse_retest": "s4", "s5_squeeze_breakout": "s5", "s6_trend_pullback": "s6"}[sid]
    for period in ("development", "validation", "forward"):
        if period == "forward":
            path = Path(f"data/signals/{sid}/signals.jsonl")
            sigs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
            sigs = [{"event_time_ms": s["event_time_ms"], "side": s["side"], "stop": s["stop"], "ladder": s["tp_ladder"]} for s in sigs]
        else:
            path = Path(f"data/tmp/{short}_signals_{period}.json")
            if not path.exists():
                continue
            sigs = json.loads(path.read_text(encoding="utf-8"))["signals"]
        li = market_for(period)
        trades = replay_signals(sigs, li[0].market)
        finish(sid, period, trades, h1_bars(li[0].market.window_end_ms))


def export_s7() -> None:
    import s7_study as st
    cfg = json.loads(Path("data/s7_study/development.json").read_text(encoding="utf-8"))["report"]["selected"]["config"]
    for period in (BacktestPeriod.DEVELOPMENT, BacktestPeriod.VALIDATION, BacktestPeriod.FORWARD):
        study = st.Study(period)
        tf, p, _ = st.split(cfg)
        setups = study.setups(tf, p)
        bars = study.bars[st.TFS[tf]]
        tm = lambda i: int(bars.open_time_ms[i])  # noqa: E731
        trades = []
        for o in (x for x in study.outcomes(cfg) if x.status == "trade"):
            s = setups[o.setup_index]
            leg = o.legs[0]
            risk = sum(lg.weight * abs(lg.entry_price - lg.stop) for lg in o.legs)
            trades.append({
                "id": f"{tf}-{tm(s.arm_index)}-{'L' if s.side == 1 else 'S'}", "side": s.side, "entry_time_ms": o.entry_time_ms, "exit_time_ms": o.exit_time_ms,
                "entry": leg.entry_price, "stop": leg.stop, "targets": [leg.entry_price + s.side * r * abs(leg.entry_price - leg.stop) for r in leg.ladder_r],
                "exit_reasons": list(leg.reasons), "net_r": o.net_r, "risk_per_unit": risk,
                "line": {"points": [{"timeMs": tm(s.line.a_index), "price": s.line.a_price}, {"timeMs": tm(s.cross_index), "price": float(s.line.at(s.cross_index))}]},
                "level0": {"timeMs": tm(s.level0_index), "price": s.level0}, "level1": {"timeMs": tm(s.level1_index), "price": s.level1},
                "zone": {"low": s.zone_low, "high": s.zone_high},
                "smc_zones": [{"kind": z.kind, "low": z.low, "high": z.high, "timeMs": tm(z.index)} for z in s.confluence],
            })
        finish("s7", period.value, trades, study.bars[Timeframe.H1])


def export_cs() -> None:
    import cs_sealed_test as cs
    for period in ("devval", "test", "forward"):
        li = market_for(period)
        t = np.concatenate([x.features.t_ms for x in li]); names = li[0].features.names
        vals = np.vstack([x.features.values for x in li])
        f = {n: vals[:, k] for k, n in enumerate(names)}
        m = {k: np.concatenate([getattr(x.market, k) for x in li]) for k in ("time_ms", "open", "high", "low")}
        ft = np.concatenate([x.market.funding_time_ms for x in li]); fr = np.concatenate([x.market.funding_rate for x in li])
        res = cs.simulate(cs.trades_from_signals(t, f), m, ft, fr, CFD, False, False)
        trades = [{"id": f"{x['entry_ms']}-L", "side": 1, "entry_time_ms": x["entry_ms"], "exit_time_ms": x["exit_ms"], "entry": x["entry"],
                   "stop": x["entry"] * (1 - cs.STOP), "targets": [], "exit_reasons": [x["reason"]], "net_r": x["r"], "risk_per_unit": x["risk"]} for x in res]
        finish("crowded_shorts", period, trades, h1_bars(li[-1].market.window_end_ms))


def main() -> None:
    which = sys.argv[1:] or ["s4_impulse_retest", "s5_squeeze_breakout", "s6_trend_pullback", "s7", "crowded_shorts"]
    for sid in which:
        {"s7": export_s7, "crowded_shorts": export_cs}.get(sid, lambda s=sid: export_s456(s))()
    index = []
    for d in sorted(OUT.iterdir()):
        if d.is_dir():
            for f in sorted(d.glob("*.json")):
                p = json.loads(f.read_text(encoding="utf-8"))
                index.append({"strategy": p["strategy"], "title": p["title"], "period": p["period"], "period_label": p["period_label"], "summary": p["summary"]})
    (OUT / "index.json").write_text(json.dumps(index, default=float), encoding="utf-8")
    print("index:", len(index), "entries")


if __name__ == "__main__":
    main()

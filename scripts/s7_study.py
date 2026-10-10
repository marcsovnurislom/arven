"""S7 development evaluation (docs/strategy_s7_trend_break_fib.md section 6). Research-only: nothing in ``src/``
imports this.

Runs the pre-registered one-at-a-time variant procedure on the development period under the broker (CFD) cost
profile, then reports the selected configuration under all cost profiles against the baselines (no trade,
buy-and-hold, random-entry control), with the analysis-only breakdowns. Writes everything (config, data range, git
commit, every configuration's metrics) to ``data/s7_study/development.json``.

``--period validation`` runs the configuration selected on development **once**, unchanged (no selection), and writes
``data/s7_study/validation.json``; it refuses to run again if that file exists (spec section 6: validation is evaluated
once). Every run is appended to ``data/s7_study/evaluations.log``. The sealed test period is never requested. Usage:
    PYTHONPATH=src python scripts/s7_study.py [--period development|validation] [--draws 200]
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate
from arven.backtest.paper_tracker import track_signal
from arven.backtest.strategy_s7_sim import S7Bars, S7Outcome, make_context, run_setups
from arven.core.config import CostsConfig, load_config
from arven.core.features_config import load_features_config
from arven.core.splitguard import BacktestPeriod
from arven.core.time import from_ms
from arven.core.timeframes import Timeframe
from arven.data.reader import load_feature_inputs, open_readonly
from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel
from arven.engine.strategy_s7 import S7Params, S7Setup, detect_setups
from arven.engine.strategy_s7_plan import S7TradeParams
from arven.runs import load_inputs, make_guard

SEED = 7
SOURCES = ("src/arven/engine/strategy_s7.py", "src/arven/engine/strategy_s7_plan.py", "src/arven/backtest/strategy_s7_sim.py",
           "src/arven/backtest/paper_tracker.py", "src/arven/backtest/costs.py", "scripts/s7_study.py", "config/costs_cfd_justmarkets.yaml")
MIN_TRADES = 100
TFS = {"15m": Timeframe.M15, "1h": Timeframe.H1, "4h": Timeframe.H4}
LOWER = {"15m": Timeframe.M5, "1h": Timeframe.M15, "4h": Timeframe.H1}
HIGHER = {"15m": Timeframe.H1, "1h": Timeframe.H4, "4h": None}

# (question, key, options) in the spec's table order; the first option is the baseline
QUESTIONS: list[tuple[str, str, list[Any]]] = [
    ("1 timeframe", "tf", ["1h", "15m", "4h"]),
    ("2 touches", "min_touches", [3, 2, 4]),
    ("3 impulse on the break", "impulse", ["none", "body_1atr", "fvg"]),
    ("4 level-1 freeze", "freeze_pullback", [0.236, 0.382]),
    ("5 entry", "entry", ["E1", "E2", "E3", "E4"]),
    ("6 stop", "stop", ["S2", "S1", "S3"]),
    ("7 breakeven after TP1", "breakeven_after_tp1", [False, True]),
    ("8 minimum R to TP1", "min_tp1_r", [None, 1.0]),
    ("9 touch counting", "count_every_touch", [False, True]),
    ("10 level 0 after a range", "level0_range_bottom", [False, True]),
    ("11 leg beyond the line's anchor", "skip_beyond_line_start", [True, False]),
    ("12 break definition", "break_on_cross", [False, True]),
    ("13 line start", "line_from_major_high", [False, True]),
    ("14 zone convention", "shallow_zone", [False, True]),
]
DETECTOR_KEYS = {"min_touches", "freeze_pullback", "count_every_touch", "level0_range_bottom", "skip_beyond_line_start",
                 "break_on_cross", "line_from_major_high", "shallow_zone"}
TRADE_KEYS = {"entry", "stop", "breakeven_after_tp1", "min_tp1_r"}


def split(cfg: dict[str, Any]) -> tuple[str, S7Params, S7TradeParams]:
    det = {k: v for k, v in cfg.items() if k in DETECTOR_KEYS}
    det["impulse_body_atr"] = 1.0 if cfg["impulse"] == "body_1atr" else None
    det["impulse_fvg"] = cfg["impulse"] == "fvg"
    return cfg["tf"], S7Params(**det), S7TradeParams(**{k: v for k, v in cfg.items() if k in TRADE_KEYS})


def key(cfg: dict[str, Any]) -> str:
    return json.dumps(cfg, sort_keys=True)


class Study:
    def __init__(self, period: BacktestPeriod = BacktestPeriod.DEVELOPMENT) -> None:
        if period not in (BacktestPeriod.DEVELOPMENT, BacktestPeriod.VALIDATION):
            raise SystemExit("only development or validation (the sealed test is not available here)")
        self.period = period
        self.app, fcfg = load_config(), load_features_config()
        self.window = make_guard(self.app).resolve(period)
        t0 = time.time()
        self.market = load_inputs(self.app, fcfg, self.window).market
        con = open_readonly(self.app.data.database_path)
        try:
            self.bars = load_feature_inputs(con, self.app, start=self.app.data.history_start, end=from_ms(self.window.end_ms)).bars
        finally:
            con.close()
        print(f"data loaded in {time.time() - t0:.0f}s: {len(self.market)} 1m bars, window {from_ms(self.window.start_ms)} -> {from_ms(self.window.end_ms)}")
        self.costs = {
            "cfd": CostsConfig.model_validate(yaml.safe_load(Path("config/costs_cfd_justmarkets.yaml").read_text(encoding="utf-8"))),
            "perp": self.app.costs,
        }
        self._setups: dict[str, list[S7Setup]] = {}
        self._results: dict[tuple[str, str, bool], dict[str, Any]] = {}
        self._outcomes: dict[tuple[str, str, bool], list[S7Outcome]] = {}

    def s7bars(self, tf: Timeframe | None) -> S7Bars | None:
        return None if tf is None else S7Bars.from_series(self.bars[tf])

    def setups(self, tf: str, p: S7Params) -> list[S7Setup]:
        k = f"{tf}|{asdict(p)}"
        if k not in self._setups:
            b = self.bars[TFS[tf]]
            found = detect_setups(b.open, b.high, b.low, b.close, p, volume=b.volume)
            close_ms = b.open_time_ms + TFS[tf].ms
            self._setups[k] = [s for s in found if self.window.start_ms <= int(close_ms[s.arm_index]) < self.window.end_ms]
        return self._setups[k]

    def evaluate(self, cfg: dict[str, Any], costs: str = "cfd", stress: bool = False) -> dict[str, Any]:
        rk = (key(cfg), costs, stress)
        if rk not in self._results:
            tf, p, tp = split(cfg)
            setups = self.setups(tf, p)
            ctx = make_context(self.s7bars(TFS[tf]), self.s7bars(LOWER[tf]), self.market, self.costs[costs], p, tp,
                               higher=self.s7bars(HIGHER[tf]), stress=stress)
            outs = run_setups(ctx, setups)
            self._outcomes[rk] = outs
            self._results[rk] = metrics(outs, len(setups))
        return self._results[rk]

    def outcomes(self, cfg: dict[str, Any], costs: str = "cfd", stress: bool = False) -> list[S7Outcome]:
        self.evaluate(cfg, costs, stress)
        return self._outcomes[(key(cfg), costs, stress)]


def metrics(outs: list[S7Outcome], n_setups: int) -> dict[str, Any]:
    trades = [o for o in outs if o.status == "trade"]
    rs = np.array([o.net_r for o in trades])
    statuses: dict[str, int] = {}
    for o in outs:
        statuses[o.status] = statuses.get(o.status, 0) + 1
    m: dict[str, Any] = {"setups": n_setups, "trades": len(trades), "statuses": dict(sorted(statuses.items()))}
    if len(rs) == 0:
        return m | {"total_r": 0.0, "r_per_100_setups": 0.0}
    curve = np.cumsum(rs)
    equity = np.cumprod(1.0 + 0.01 * rs)  # 1 % risk per trade, compounded
    wins, losses = rs[rs > 0].sum(), -rs[rs < 0].sum()
    return m | {
        "total_r": float(rs.sum()), "mean_r": float(rs.mean()), "win_rate": float(np.mean(rs > 0)),
        "profit_factor": float(wins / losses) if losses > 0 else math.inf,
        "max_drawdown_r": float(np.max(np.maximum.accumulate(np.concatenate([[0.0], curve]))[1:] - curve)),
        "return_at_1pct_risk": float(equity[-1] - 1.0),
        "max_drawdown_at_1pct_risk": float(np.max(1.0 - equity / np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:])),
        "r_per_100_setups": float(100.0 * rs.sum() / n_setups) if n_setups else 0.0,
    }


def select(study: Study) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cfg = {k: opts[0] for _, k, opts in QUESTIONS}
    log: list[dict[str, Any]] = []
    for question, k, opts in QUESTIONS:
        rows = []
        for v in opts:
            trial = cfg | {k: v}
            t0 = time.time()
            m = study.evaluate(trial)
            rows.append((v, m))
            print(f"  {question:34s} {k}={v!s:6s} setups={m['setups']:4d} trades={m['trades']:4d} "
                  f"totalR={m['total_r']:+7.2f} R/100setups={m['r_per_100_setups']:+7.2f} ({time.time() - t0:.0f}s)")
        eligible = [(v, m) for v, m in rows if m["trades"] >= MIN_TRADES]
        chosen = max(eligible, key=lambda vm: vm[1]["r_per_100_setups"])[0] if eligible else cfg[k]
        log.append({"question": question, "key": k, "kept": chosen, "eligible": [v for v, _ in eligible],
                    "rows": [{"value": v, **m} for v, m in rows]})
        print(f"  -> {k} = {chosen!s}{'' if eligible else ' (no option reached 100 trades: earlier value kept)'}")
        cfg = cfg | {k: chosen}
    return cfg, log


def random_control(study: Study, outs: list[S7Outcome], costs: CostsConfig, draws: int) -> dict[str, Any]:
    """Same side, stop distance (fraction of price) and TP R ladder as each S7 trade, at random 1m bars."""
    m = study.market
    trades = [o for o in outs if o.status == "trade"]
    rng = np.random.default_rng(SEED)
    fee_rate = taker_fee_rate(costs)
    horizon = 30 * 24 * 60  # keep random entries at least 30 days before the end so they can resolve
    means: list[float] = []
    for _ in range(draws):
        rs: list[float] = []
        for o in trades:
            leg = o.legs[0]
            side = 1 if leg.entry_price > leg.stop else -1
            dist = abs(leg.entry_price - leg.stop) / leg.entry_price
            i = int(rng.integers(0, len(m) - horizon))
            op, hi, lo = float(m.open[i]), float(m.high[i]), float(m.low[i])
            fill = adverse_price(op, side, slippage_fraction(op, hi, lo, costs, False))
            stop = fill * (1.0 - side * dist)
            ladder = tuple(TPLevel.from_r_multiple(r, f, entry=fill, stop=stop, side=side) for r, f in zip(leg.ladder_r, (0.5, 0.3, 0.2), strict=True))
            sig = EngineSignal(
                symbol="BTCUSDT", side=side, strategy_id="random_control", strategy_version="v1", grade=Grade.EXPERIMENTAL,
                event_time_ms=int(m.time_ms[i]), entry_reference=fill, stop=stop, tp_ladder=ladder, risk_fraction=0.01,
                confidence=0.5, regime="control", reasons=("control",), risk_checks=(), versions=SignalVersions("v1", "control", None),
            )
            res = track_signal(sig, int(m.time_ms[i]), fill, m, costs).resolution
            if res is not None and res.fully_closed:
                rs.append(res.r_multiple - fill * fee_rate / abs(fill - stop))
        means.append(float(np.mean(rs)) if rs else math.nan)
    a = np.array(means)
    return {"draws": draws, "seed": SEED, "mean_of_means": float(np.nanmean(a)), "p05": float(np.nanpercentile(a, 5)),
            "p50": float(np.nanpercentile(a, 50)), "p95": float(np.nanpercentile(a, 95))}


def breakdowns(study: Study, cfg: dict[str, Any], outs: list[S7Outcome]) -> dict[str, Any]:
    tf, p, _ = split(cfg)
    setups = study.setups(tf, p)
    groups: dict[str, dict[str, list[float]]] = {}
    for o in outs:
        if o.status != "trade":
            continue
        s = setups[o.setup_index]
        tags = {
            "side": "long" if s.side == 1 else "short", "confluence_score": str(s.confluence_score), "touches": str(len(s.touches)),
            "range_before_break": str(s.range_box is not None), "level1_moves": "0" if s.level1_moves == 0 else ("1-2" if s.level1_moves <= 2 else "3+"),
            "zone_touched_at_arm": str(s.zone_touched_at_arm),
        }
        for dim, val in tags.items():
            groups.setdefault(dim, {}).setdefault(val, []).append(o.net_r)
    return {dim: {v: {"n": len(r), "total_r": float(np.sum(r)), "mean_r": float(np.mean(r)), "win_rate": float(np.mean(np.array(r) > 0))}
                  for v, r in sorted(vals.items())} for dim, vals in groups.items()}


def cost_report(study: Study, cfg: dict[str, Any], name: str) -> dict[str, Any]:
    rep: dict[str, Any] = {"config": cfg}
    for costs in ("cfd", "perp"):
        for stress in (False, True):
            m = study.evaluate(cfg, costs, stress)
            rep[f"{costs}{'_stress' if stress else ''}"] = m
            print(f"  {name:8s} {costs:4s} stress={stress!s:5s} trades={m['trades']:4d} totalR={m['total_r']:+7.2f} "
                  f"meanR={m.get('mean_r', float('nan')):+.3f} win={m.get('win_rate', float('nan')):.1%} "
                  f"ret@1%={m.get('return_at_1pct_risk', float('nan')):+.1%} maxDD@1%={m.get('max_drawdown_at_1pct_risk', float('nan')):.1%}")
    return rep


def run_meta(study: Study, t_start: float) -> dict[str, Any]:
    return {
        "strategy": "s7_trend_break_fib", "period": study.period.value,
        "window_ms": [study.window.start_ms, study.window.end_ms],
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip() or None,
        "source_sha256": {f: hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in SOURCES},
        "git_dirty": bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=False).stdout.strip()),
        "cost_profiles": {k: v.model_dump() for k, v in study.costs.items()},
        "runtime_s": round(time.time() - t_start),
    }


def finish(study: Study, out: dict[str, Any], name: str) -> None:
    path = study.app.data.data_dir / "s7_study" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    sel = out["report"]["selected"]["cfd"]
    line = (f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} period={out['period']} commit={out['git_commit']} dirty={out['git_dirty']} "
            f"config={json.dumps(out['report']['selected']['config'], sort_keys=True)} trades={sel['trades']} total_r_cfd={sel['total_r']:+.2f}\n")
    with (path.parent / "evaluations.log").open("a", encoding="utf-8") as fh:
        fh.write(line)
    print(f"written {path} in {out['runtime_s']}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=("development", "validation"), default="development")
    ap.add_argument("--draws", type=int, default=200)
    args = ap.parse_args()
    t_start = time.time()
    if args.period == "validation":
        validate(args.draws, t_start)
        return
    study = Study()
    print("\n== one-at-a-time selection (development, CFD costs)")
    final, log = select(study)
    baseline = {k: opts[0] for _, k, opts in QUESTIONS}
    print("\n== selected configuration:", final)
    report = {"baseline": cost_report(study, baseline, "baseline"), "selected": cost_report(study, final, "selected")}
    sel_outs = study.outcomes(final)
    print(f"\n== random-entry control ({args.draws} draws)")
    control = random_control(study, sel_outs, study.costs["cfd"], args.draws)
    print("  ", control, "| S7 mean R:", report["selected"]["cfd"].get("mean_r"))
    m = study.market
    buy_hold = float(m.close[-1] / m.open[0] - 1.0)
    out = run_meta(study, t_start) | {
        "selection_metric": "total R per 100 armed setups, CFD costs, among options with >= 100 trades",
        "configurations_evaluated": len({k for k, c, s in study._results if c == "cfd" and not s}),
        "selection_log": log, "report": report,
        "baselines": {"no_trade_r": 0.0, "buy_and_hold_return": buy_hold, "random_entry_control_cfd": control},
        "breakdowns_selected_cfd": breakdowns(study, final, sel_outs),
    }
    print(f"\nbuy-and-hold {buy_hold:+.1%}; configurations evaluated: {out['configurations_evaluated']}")
    finish(study, out, "development")


def validate(draws: int, t_start: float) -> None:
    """The selected configuration, unchanged, once on validation."""
    app = load_config()
    out_dir = app.data.data_dir / "s7_study"
    dev_path, val_path = out_dir / "development.json", out_dir / "validation.json"
    if val_path.exists():
        raise SystemExit(f"{val_path} exists: validation has already been evaluated once (spec section 6); not re-running")
    dev_bytes = dev_path.read_bytes()
    final = json.loads(dev_bytes)["report"]["selected"]["config"]
    study = Study(BacktestPeriod.VALIDATION)
    print("\n== validation, selected configuration (unchanged):", final)
    report = {"selected": cost_report(study, final, "selected")}
    sel_outs = study.outcomes(final)
    print(f"\n== random-entry control ({draws} draws)")
    control = random_control(study, sel_outs, study.costs["cfd"], draws)
    print("  ", control, "| S7 mean R:", report["selected"]["cfd"].get("mean_r"))
    m = study.market
    buy_hold = float(m.close[-1] / m.open[0] - 1.0)
    out = run_meta(study, t_start) | {
        "selected_from": {"file": "data/s7_study/development.json", "sha256": hashlib.sha256(dev_bytes).hexdigest()},
        "report": report,
        "baselines": {"no_trade_r": 0.0, "buy_and_hold_return": buy_hold, "random_entry_control_cfd": control},
        "breakdowns_selected_cfd": breakdowns(study, final, sel_outs),
    }
    print(f"\nbuy-and-hold {buy_hold:+.1%}")
    finish(study, out, "validation")


if __name__ == "__main__":
    main()

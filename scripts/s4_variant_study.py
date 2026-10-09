"""S4 exit-management study (docs/strategy_impulse_retest.md section 11, variants V0/A/B/C/D).

Two phases, both research-only (nothing here is imported by ``src/``):

* ``record <period>`` - runs the unchanged S4 v1.1 provider through the Stage 4 event backtester on the
  period and dumps every signal it proposed (decision time, side, reference entry, stop, TP ladder) to JSON.
  Only this phase touches the backtester; it takes 20-30 minutes per multi-year period.
* ``evaluate <costs-profile> <signals.json>...`` - replays those signals on 1m bars with
  ``arven.backtest.paper_tracker.track_signal`` for each pre-registered exit variant. Fast.

Periods are resolved through ``SplitGuard`` (the sealed test period is never requested here).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import yaml

from arven.backtest.event_engine import EventBacktester, WindowEventClock
from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate
from arven.backtest.paper_tracker import track_signal
from arven.backtest.provider import DecisionContext
from arven.backtest.metrics import compute_metrics
from arven.backtest.strategy_s4_provider import ImpulseRetestProvider
from arven.backtest.strategy_s5_provider import SqueezeBreakoutProvider
from arven.core.backtest_config import load_backtest_config
from arven.core.config import CostsConfig, load_config
from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel
from arven.core.features_config import load_features_config
from arven.core.splitguard import BacktestPeriod
from arven.core.time import from_ms
from arven.core.timeframes import Timeframe
from arven.data.reader import load_feature_inputs, open_readonly
from arven.runs import load_inputs, make_guard

FORWARD_START_MS = 1782864000000


class _Recording:
    """Mixin: records every engine signal the wrapped provider proposes."""

    recorded: list[dict]

    def decide(self, ctx: DecisionContext):
        if not hasattr(self, "recorded"):
            self.recorded = []
        signal = super().decide(ctx)
        if signal is not None:
            es = self.to_engine_signal(ctx.now_ms, feature_version="v1", config_hash="study", git_commit=None)
            if es is not None:
                self.recorded.append({
                    "event_time_ms": ctx.now_ms, "side": es.side, "entry_reference": es.entry_reference, "stop": es.stop,
                    "ladder": [[lv.r_multiple, lv.close_fraction, lv.price] for lv in es.tp_ladder],
                })
        return signal


class RecordingS4(_Recording, ImpulseRetestProvider):
    pass


class RecordingS5(_Recording, SqueezeBreakoutProvider):
    pass


def record(period: str, out: Path, strategy: str = "s4") -> None:
    app, fcfg, bt_cfg = load_config(), load_features_config(), load_backtest_config()
    guard = make_guard(app)
    if period == "development":
        window = guard.resolve(BacktestPeriod.DEVELOPMENT)
    elif period == "validation":
        window = guard.resolve(BacktestPeriod.VALIDATION)
    else:
        raise SystemExit("period must be development or validation (the sealed test is not available here)")
    inputs = load_inputs(app, fcfg, window)
    con = open_readonly(app.data.database_path)
    market_inputs = load_feature_inputs(con, app, start=app.data.history_start, end=from_ms(window.end_ms))
    con.close()
    provider = (RecordingS4 if strategy == "s4" else RecordingS5)(market_inputs.bars[Timeframe.H1], market_inputs.bars[Timeframe.M15], market_inputs.bars[Timeframe.H4])
    clock = WindowEventClock(app.market.symbol, (Timeframe.M15,), window.start_ms, window.end_ms)
    result = EventBacktester(app, bt_cfg, window, inputs.market, inputs.features).run(clock, {Timeframe.M15: provider})
    metrics = compute_metrics(result, bt_cfg)
    print("ENGINE", strategy, period, {k: metrics.get(k) for k in ("n_trades", "win_rate", "total_return", "max_drawdown", "sharpe", "final_equity")})
    out.write_text(json.dumps({"strategy": strategy, "period": period, "window": [window.start_ms, window.end_ms], "signals": provider.recorded}))
    print("recorded", len(provider.recorded), "signals ->", out)


VARIANTS = ("V0", "A", "B", "C", "D")
RISK_FRACTION = 0.01


def build_signal(rec: dict, variant: str) -> tuple[EngineSignal, float | None]:
    """The variant's exit plan as an EngineSignal plus its breakeven trigger (in R, or None)."""
    side, entry, stop = rec["side"], rec["entry_reference"], rec["stop"]
    risk = abs(entry - stop)
    tp1_r, _, tp1_price = rec["ladder"][0]

    def rung(r: float, fraction: float) -> TPLevel:
        return TPLevel.from_r_multiple(r, fraction, entry=entry, stop=stop, side=side)

    be = None
    if variant == "V0":
        ladder = (TPLevel(tp1_r, 1.0, tp1_price),)
    elif variant == "A":
        ladder, be = (TPLevel(tp1_r, 1.0, tp1_price),), 1.0
    elif variant == "B":
        be = 1.0
        ladder = (rung(2.0, 0.3), TPLevel(tp1_r, 0.7, tp1_price)) if tp1_r > 2.0 else (TPLevel(tp1_r, 1.0, tp1_price),)
    elif variant == "C":
        ladder = (rung(2.0, 1.0),)
    elif variant == "D":
        ladder = (rung(3.0, 1.0),)
    else:
        raise ValueError(variant)
    sig = EngineSignal(
        symbol="BTCUSDT", side=side, strategy_id="s4_impulse_retest", strategy_version="v1.1", grade=Grade.EXPERIMENTAL,
        event_time_ms=rec["event_time_ms"], entry_reference=entry, stop=stop, tp_ladder=ladder, risk_fraction=RISK_FRACTION,
        confidence=0.5, regime="study", reasons=("study",), risk_checks=(), versions=SignalVersions("v1", "study", None),
    )
    return sig, be


def replay(signals: list[dict], variant: str, market, costs: CostsConfig, stress: bool) -> list[float]:
    """Net R of every resolved trade of ``variant`` (one open trade at a time; entry fee and slippage included)."""
    fee_rate = taker_fee_rate(costs)
    free_at = 0
    out: list[float] = []
    for rec in signals:
        t = rec["event_time_ms"]
        if t < free_at:
            continue
        i = market.first_at_or_after(t)
        if i >= len(market) or int(market.time_ms[i]) != t:
            continue
        side = rec["side"]
        o, h, lo = float(market.open[i]), float(market.high[i]), float(market.low[i])
        fill = adverse_price(o, side, slippage_fraction(o, h, lo, costs, stress))
        sig, be = build_signal(rec, variant)
        result = track_signal(sig, t, fill, market, costs, stress=stress, breakeven_at_r=be)
        if result.resolution is None:
            break  # data ran out before this trade resolved; it and everything after stay unresolved
        risk = abs(fill - rec["stop"])
        out.append(result.resolution.r_multiple - fill * fee_rate / risk)
        free_at = result.updates[-1].time_ms + 60_000
    return out


def summarize(rs: list[float]) -> str:
    if not rs:
        return "n=0"
    a = np.array(rs)
    wins, losses = a[a > 0].sum(), -a[a < 0].sum()
    equity = np.cumprod(1.0 + RISK_FRACTION * a)
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    return (f"n={len(a):3d} win={np.mean(a > 0):5.1%} totalR={a.sum():+7.2f} meanR={a.mean():+6.3f} "
            f"PF={(wins / losses if losses > 0 else float('inf')):5.2f} ret={equity[-1] - 1:+7.1%} maxDD={np.max(1 - equity / peak):5.1%}")


def evaluate(paths: list[Path]) -> None:
    app, fcfg = load_config(), load_features_config()
    profiles = {
        "perp (config/costs.yaml)": app.costs,
        "CFD JustMarkets (config/costs_cfd_justmarkets.yaml)": CostsConfig.model_validate(
            yaml.safe_load(Path("config/costs_cfd_justmarkets.yaml").read_text(encoding="utf-8"))),
    }
    guard = make_guard(app)
    for path in paths:
        data = json.loads(path.read_text())
        period = BacktestPeriod(data["period"])
        window = guard.resolve(period)
        market = load_inputs(app, fcfg, window).market
        print(f"\n=== {data['period']}  signals={len(data['signals'])}")
        variants = VARIANTS if data.get("strategy", "s4") == "s4" else ("V0",)  # only S4's variants were pre-registered
        for name, costs in profiles.items():
            for stress in (False, True):
                print(f"-- {name}  stress={stress}")
                for v in variants:
                    print(f"   {v}: {summarize(replay(data['signals'], v, market, costs, stress))}")


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "record":
        record(sys.argv[2], Path(sys.argv[3]), sys.argv[4] if len(sys.argv) > 4 else "s4")
    elif len(sys.argv) >= 3 and sys.argv[1] == "evaluate":
        evaluate([Path(p) for p in sys.argv[2:]])
    else:
        raise SystemExit("usage: s4_variant_study.py record <development|validation> <out.json> [s4|s5] | evaluate <signals.json>...")

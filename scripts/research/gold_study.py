"""The full gold (XAUUSD) evaluation - every analysis that was run for BTC, with the same code and the same, unchanged
strategy parameters (nothing is re-tuned for gold; the one exception is the clearly separate ``s7select`` step, which
re-runs S7's own selection procedure on gold development to see whether the *method* replicates). Research-only:
nothing in ``src/`` imports this. The sealed test period (2025-01 -> 2026-07) is never requested.

Data: Dukascopy XAUUSD mid prices (instrument ``XAUUSD``), CME metals session calendar, the gold CFD cost profile
(``config/costs_cfd_justmarkets_xauusd.yaml``; ``x4`` = its spread times 4). Output: ``data/markets/XAUUSD/research/``.

Steps (``python scripts/research/gold_study.py <step> [period]``; periods: development, validation, forward):
    crosscheck            Dukascopy XAUUSD vs Binance XAUUSDT on their overlap; Dukascopy spread by year
    record <period>       S4/S5/S6 signals through the event backtester (as scripts/s4_variant_study.py record)
    all <period>          every strategy one trade at a time: own exits and without the time exit, CFD and x4
                          (as the BTC all7 study), trade lists with side, fill, stop, entry/exit time
    money                 the $1000 account (1 % and 2 % risk, 1 oz minimum lot, 5 % cap) and swap sensitivity
    s7grid <period>       S7 stop x TP3 x after-TP2 grid with and without FVG, CFD and x4; per-setup outcomes with the
                          8 situation features (as the BTC s7_stops study)
    s7rules               S7 "range before the break -> stop fib 0.3", management variants, SMC zone filters, random
                          control and breakdowns, on all three periods
    s7select              S7's 14-question selection re-run on gold development; the result checked on validation/forward
    s7full <period>       S7 grid: touches {3,2} x impulse {fvg,none} x 6 stops x SMC zone filters (FVG/iFVG/OB), CFD and x4
    s7full_select         the pre-registered pick on development (max mean R, >= 50 trades), validation/forward read once
S1-S3 as the full Stage 5 pipeline (decision + risk engine) and its baselines run through the CLI:
    python -m arven --instrument XAUUSD features build
    python -m arven --instrument XAUUSD backtest run --provider pipeline --period development|validation [--stress]
    python -m arven --instrument XAUUSD backtest baselines --period development|validation
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import s7_study as st  # noqa: E402

import arven.backtest.strategy_s7_sim as sim  # noqa: E402
from arven.backtest.account_sim import AccountRules, TradeForAccount, replay_account, summarize_account  # noqa: E402
from arven.backtest.clock import SimulationClock  # noqa: E402
from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate  # noqa: E402
from arven.backtest.event_engine import EventBacktester, WindowEventClock  # noqa: E402
from arven.backtest.paper_tracker import track_signal  # noqa: E402
from arven.backtest.provider import DecisionContext, FeatureView  # noqa: E402
from arven.backtest.strategy_s4_provider import ImpulseRetestProvider  # noqa: E402
from arven.backtest.strategy_s5_provider import SqueezeBreakoutProvider  # noqa: E402
from arven.backtest.strategy_s6_provider import TrendPullbackProvider  # noqa: E402
from arven.core.backtest_config import load_backtest_config  # noqa: E402
from arven.core.config import load_config  # noqa: E402
from arven.core.features_config import load_features_config  # noqa: E402
from arven.core.live_config import load_live_config  # noqa: E402
from arven.core.regime_config import load_regime_config  # noqa: E402
from arven.core.risk_config import load_risk_config  # noqa: E402
from arven.core.splitguard import BacktestPeriod  # noqa: E402
from arven.core.strategies_config import load_strategies_config  # noqa: E402
from arven.core.time import from_ms  # noqa: E402
from arven.core.timeframes import Timeframe  # noqa: E402
from arven.decision.pipeline import Stage5Pipeline  # noqa: E402
from arven.engine.grading import Grade  # noqa: E402
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel  # noqa: E402
from arven.engine.strategy_s7_plan import MANAGEMENTS, S7TradeParams  # noqa: E402
from arven.live.strategies import S7Strategy  # noqa: E402

INSTRUMENT = "XAUUSD"
CONFIG_DIR = os.environ.get("ARVEN_CONFIG_DIR")  # another configuration (e.g. a scratch data directory for a dry run)
APP = load_config(CONFIG_DIR, instrument=INSTRUMENT)
OUT = APP.market_root / "research"
PERIODS = {"development": BacktestPeriod.DEVELOPMENT, "validation": BacktestPeriod.VALIDATION, "forward": BacktestPeriod.FORWARD}
PROFILES = {"cfd": False, "cfd_x4": True}
# The live S7 configuration (config/live.yaml), which is the one BTC's development selection chose. Gold uses it unchanged.
S7_CFG = next(s.params for s in load_live_config(CONFIG_DIR).strategies if s.kind == "s7")
OZ_RULES = {"1%": AccountRules(risk_fraction=0.01, min_lot=1.0, lot_step=1.0), "2%": AccountRules(risk_fraction=0.02, min_lot=1.0, lot_step=1.0)}
# Overnight swap sensitivity (an estimate - JustMarkets publishes no XAUUSD swap we could find; typical retail gold swaps
# are a clearly negative long rate and a near-zero short rate). Per night held, as a fraction of the position's notional;
# Wednesday's rollover counts three nights. Applied as an upper bound: the full position is assumed held to the final exit.
SWAP_PER_NIGHT = {1: -2.0e-4, -1: -0.5e-4}
ROLLOVER_HOUR_NY = 17  # the CME metals daily close


def save(name: str, obj: Any) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(obj, indent=1, default=float), encoding="utf-8")
    print("saved", path, flush=True)
    return path


def load(name: str) -> Any:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


# --- data cross-check -----------------------------------------------------------------------------------------------


def crosscheck() -> None:
    from arven.data.adapters.dukascopy import DukaDayFile, decode_m1, plan_days
    from arven.data.reader import open_readonly

    con = open_readonly(APP.data.database_path)
    try:
        q = ("SELECT a.open_time_ms, a.close, b.close FROM ohlcv_1m a JOIN ohlcv_1m b USING (open_time_ms) "
             "WHERE a.symbol = 'XAUUSD' AND b.symbol = 'XAUUSDT' ORDER BY 1")
        t, duka, perp = (np.asarray(x) for x in zip(*con.execute(q).fetchall(), strict=True))
    finally:
        con.close()
    basis = perp - duka
    rel = basis / duka
    out: dict[str, Any] = {"overlap_minutes": int(len(t)), "first": from_ms(int(t[0])).isoformat(), "last": from_ms(int(t[-1])).isoformat(),
                           "basis_usd": {"median": float(np.median(basis)), "p05": float(np.percentile(basis, 5)), "p95": float(np.percentile(basis, 95))},
                           "basis_bps": {"median": float(np.median(rel) * 1e4), "mean_abs": float(np.mean(np.abs(rel)) * 1e4)}}
    for k, step in (("1m", 1), ("15m", 15), ("1h", 60)):
        a, b = np.log(duka[::step]), np.log(perp[::step])
        ra, rb = np.diff(a), np.diff(b)
        out[f"return_corr_{k}"] = float(np.corrcoef(ra, rb)[0, 1])
    # Dukascopy's own spread (ask - bid at the close of in-session minutes with volume), by year, in bps
    cal = APP.session_calendar()
    spreads: dict[str, list[float]] = {}
    for day in plan_days(INSTRUMENT, APP.data.history_start, from_ms(int(t[-1]) + 86_400_000)):
        if day.weekday() >= 5:
            continue
        paths = [APP.data.raw_dir / DukaDayFile(INSTRUMENT, day, s).key for s in ("BID", "ASK")]
        if not all(p.exists() for p in paths):
            continue
        bid, ask = (decode_m1(p.read_bytes(), day, APP.dukascopy.point) for p in paths)  # type: ignore[union-attr]
        if len(bid) == 0 or len(bid) != len(ask):
            continue
        ok = cal.is_open(bid.time_ms) & (bid.volume > 0)
        mid = (bid.close + ask.close) / 2
        spreads.setdefault(str(day.year), []).extend(((ask.close - bid.close)[ok] / mid[ok] * 1e4)[::30].tolist())  # every 30 min
    out["dukascopy_spread_bps"] = {y: {"median": float(np.median(v)), "p90": float(np.percentile(v, 90)), "n": len(v)} for y, v in sorted(spreads.items())}
    save("crosscheck.json", out)
    print(json.dumps(out, indent=1, default=float))


# --- shared loading -------------------------------------------------------------------------------------------------


class Ctx:
    """One period's data: the 1m market, the bars (from history start, so indicators warm up), Stage 3 features."""

    def __init__(self, period: str) -> None:
        from arven.data.reader import load_feature_inputs, open_readonly
        from arven.paper.runs import latest_forward_window_end_ms, load_paper_inputs
        from arven.runs import load_inputs, make_guard

        t0 = time.perf_counter()
        self.period = period
        self.fcfg = load_features_config(CONFIG_DIR)
        guard = make_guard(APP)
        pk = PERIODS[period]
        self.window = guard.resolve(pk, end_ms=latest_forward_window_end_ms(APP)) if pk == BacktestPeriod.FORWARD else guard.resolve(pk)
        self.inputs = (load_paper_inputs if pk == BacktestPeriod.FORWARD else load_inputs)(APP, self.fcfg, self.window)
        self.m = self.inputs.market
        con = open_readonly(APP.data.database_path)
        try:
            self.bars = load_feature_inputs(con, APP, start=APP.data.history_start, end=from_ms(self.window.end_ms)).bars
        finally:
            con.close()
        self.through = (int(self.m.time_ms[-1]) + 60_000) // 900_000 * 900_000
        self.costs = APP.costs
        print(f"{period}: loaded in {time.perf_counter() - t0:.0f}s, {from_ms(self.window.start_ms)} -> {from_ms(self.window.end_ms)}, "
              f"{len(self.m)} 1m bars", flush=True)


def trade(entry_ms: int, exit_ms: int, r: float, fill: float, stop: float, side: int) -> dict[str, Any]:
    return {"entry_ms": int(entry_ms), "exit_ms": int(exit_ms), "r": float(r), "stop_pct": abs(fill - stop) / fill, "fill": float(fill),
            "side": int(side)}


def _sig(side: int, t: int, entry: float, stop: float, ladder: tuple[TPLevel, ...], hold: int | None = None) -> EngineSignal:
    return EngineSignal(symbol=INSTRUMENT, side=side, strategy_id="replay", strategy_version="v1", grade=Grade.EXPERIMENTAL, event_time_ms=t,
                        entry_reference=entry, stop=stop, tp_ladder=ladder, risk_fraction=0.01, confidence=0.5, regime="replay",
                        reasons=("replay",), risk_checks=(), versions=SignalVersions("v1", "replay", None), max_holding_minutes=hold)


# --- S4 / S5 / S6: record the signals ------------------------------------------------------------------------------


class _Recording:
    recorded: list[dict]

    def decide(self, ctx: DecisionContext):
        if not hasattr(self, "recorded"):
            self.recorded = []
        signal = super().decide(ctx)  # type: ignore[misc]
        if signal is not None:
            es = self.to_engine_signal(ctx.now_ms, feature_version="v1", config_hash="study", git_commit=None)  # type: ignore[attr-defined]
            if es is not None:
                self.recorded.append({"event_time_ms": es.event_time_ms, "side": es.side, "entry_reference": es.entry_reference,
                                      "stop": es.stop, "ladder": [[lv.r_multiple, lv.close_fraction, lv.price] for lv in es.tp_ladder]})
        return signal


class RecS4(_Recording, ImpulseRetestProvider):
    pass


class RecS5(_Recording, SqueezeBreakoutProvider):
    pass


class RecS6(_Recording, TrendPullbackProvider):
    pass


PROVIDERS = {"s4_impulse_retest": RecS4, "s5_squeeze_breakout": RecS5, "s6_trend_pullback": RecS6}


def record(period: str) -> None:
    c = Ctx(period)
    bt = load_backtest_config(CONFIG_DIR)
    out = {"period": period, "window_ms": [c.window.start_ms, c.window.end_ms], "signals": {}}
    for sid, cls in PROVIDERS.items():
        t0 = time.perf_counter()
        provider = cls(c.bars[Timeframe.H1], c.bars[Timeframe.M15], c.bars[Timeframe.H4], symbol=INSTRUMENT)
        clock = WindowEventClock(INSTRUMENT, (Timeframe.M15,), c.window.start_ms, c.window.end_ms, calendar=APP.session_calendar())
        EventBacktester(APP, bt, c.window, c.m, c.inputs.features).run(clock, {Timeframe.M15: provider})
        out["signals"][sid] = getattr(provider, "recorded", [])
        print(f"  {sid}: {len(out['signals'][sid])} signals in {time.perf_counter() - t0:.0f}s", flush=True)
    save(f"signals_{period}.json", out)


# --- every strategy, one trade at a time ----------------------------------------------------------------------------


def recorded_replay(c: Ctx, signals: list[dict], stress: bool) -> tuple[list[dict], int]:
    """S4-S6: market entry at the signal's minute (adverse slippage), own TP ladder, one at a time."""
    fee = taker_fee_rate(c.costs)
    free_at, out = 0, []
    for rec in sorted(signals, key=lambda x: x["event_time_ms"]):
        t = int(rec["event_time_ms"])
        if t < free_at or t > c.through:
            continue
        i = c.m.first_at_or_after(t)
        if i >= len(c.m) or int(c.m.time_ms[i]) != t:
            continue
        side = int(rec["side"])
        o, h, lo = float(c.m.open[i]), float(c.m.high[i]), float(c.m.low[i])
        fill = adverse_price(o, side, slippage_fraction(o, h, lo, c.costs, stress))
        stop = float(rec["stop"])
        risk = abs(fill - stop)
        if risk <= 0 or (fill - stop) * side <= 0:
            continue
        try:
            ladder = tuple(TPLevel.from_r_multiple((p - fill) * side / risk, f, entry=fill, stop=stop, side=side) for _, f, p in rec["ladder"])
            sig = _sig(side, t, fill, stop, ladder)
        except ValueError:
            continue
        res = track_signal(sig, t, fill, c.m, c.costs, stress=stress)
        if res.resolution is None or not res.resolution.fully_closed:
            return out, 1
        closes = [u.time_ms for u in res.updates if u.kind.name in ("TP_HIT", "CLOSED")]
        out.append(trade(t, max(closes), res.resolution.r_multiple - fill * fee / risk, fill, stop, side))
        free_at = max(closes) + 60_000
    return out, 0


def s123_candidates(c: Ctx) -> dict[str, list[tuple]]:
    """S1-S3 at every (tradable) hourly decision time, the strategy's own % stop / take-profit / holding time."""
    pipe = Stage5Pipeline(load_regime_config(CONFIG_DIR), load_strategies_config(CONFIG_DIR), load_risk_config(CONFIG_DIR),
                          load_backtest_config(CONFIG_DIR))
    f = c.inputs.features
    clock = SimulationClock(f.t_ms)
    view = FeatureView(f.t_ms, f.names, f.values, clock, f.first_ready_ms)
    out: dict[str, list[tuple]] = {s.strategy_id: [] for s in pipe.strategies}
    while (t := clock.advance()) is not None:
        for s in pipe.strategies:
            cand = s.evaluate(view, t)
            if cand is not None:
                out[s.strategy_id].append((int(t), cand.direction, cand.stop_pct, cand.take_profit_pct, cand.max_holding_minutes))
    return out


def s123_replay(c: Ctx, cands: list[tuple], stress: bool, drop_time_exit: bool) -> tuple[list[dict], int]:
    fee = taker_fee_rate(c.costs)
    free_at, out = 0, []
    for t, side, stop_pct, tp_pct, hold in cands:
        if t < free_at:
            continue
        i = c.m.first_at_or_after(t)
        if i >= len(c.m) or int(c.m.time_ms[i]) != t:
            continue
        o, h, lo = float(c.m.open[i]), float(c.m.high[i]), float(c.m.low[i])
        fill = adverse_price(o, side, slippage_fraction(o, h, lo, c.costs, stress))
        stop, tp = fill * (1 - side * stop_pct), fill * (1 + side * tp_pct)
        sig = _sig(side, t, fill, stop, (TPLevel(tp_pct / stop_pct, 1.0, tp),), None if drop_time_exit else hold)
        res = track_signal(sig, t, fill, c.m, c.costs, stress=stress)
        if res.resolution is None or not res.resolution.fully_closed:
            return out, 1
        out.append(trade(t, res.updates[-1].time_ms, res.resolution.r_multiple - fill * fee / abs(fill - stop), fill, stop, side))
        free_at = res.updates[-1].time_ms + 60_000
    return out, 0


def s7_trades(c: Ctx, stress: bool, cfg: dict[str, Any] = S7_CFG) -> tuple[list[dict], int]:
    tf, p, tp = st.split(cfg)
    b = c.bars[st.TFS[tf]]
    from arven.engine.strategy_s7 import detect_setups

    close_ms = b.open_time_ms + st.TFS[tf].ms
    setups = [s for s in detect_setups(b.open, b.high, b.low, b.close, p, volume=b.volume)
              if c.window.start_ms <= int(close_ms[s.arm_index]) <= c.through]
    ctx = sim.make_context(sim.S7Bars.from_series(b), sim.S7Bars.from_series(c.bars[st.LOWER[tf]]), c.m, c.costs, p, tp,
                           higher=sim.S7Bars.from_series(c.bars[st.HIGHER[tf]]), stress=stress, calendar=APP.session_calendar())
    out, still_open = [], 0
    for r in sim.run_setups(ctx, setups):
        if r.status == "trade":
            leg = r.legs[0]
            out.append(trade(r.entry_time_ms, r.exit_time_ms, r.net_r, leg.entry_price, leg.stop, 1 if leg.entry_price > leg.stop else -1))
        elif r.status == "unresolved":
            still_open = 1
    out.sort(key=lambda x: x["entry_ms"])
    return out, still_open


def all_strategies(period: str) -> None:
    c = Ctx(period)
    recorded = load(f"signals_{period}.json")["signals"]
    res: dict[str, Any] = {"period": period, "start_ms": c.window.start_ms, "end_ms": c.window.end_ms,
                           "first_open": float(c.m.open[0]), "last_close": float(c.m.close[-1]), "strategies": {}}
    cands = s123_candidates(c)
    for sid, cs in cands.items():
        res["strategies"][sid] = {f"{v}/{prof}": dict(zip(("trades", "open_at_end"), s123_replay(c, cs, stress, v == "no_time"), strict=True))
                                  for prof, stress in PROFILES.items() for v in ("own", "no_time")}
        print(" ", sid, "done", flush=True)
    for sid, sigs in recorded.items():
        res["strategies"][sid] = {}
        for prof, stress in PROFILES.items():
            tr = dict(zip(("trades", "open_at_end"), recorded_replay(c, sigs, stress), strict=True))
            res["strategies"][sid] |= {f"own/{prof}": tr, f"no_time/{prof}": tr}  # S4-S6 have no time exit
        print(" ", sid, "done", flush=True)
    res["strategies"]["s7_trend_break_fib"] = {}
    for prof, stress in PROFILES.items():
        tr = dict(zip(("trades", "open_at_end"), s7_trades(c, stress), strict=True))
        res["strategies"]["s7_trend_break_fib"] |= {f"own/{prof}": tr, f"no_time/{prof}": tr}
    print("  s7 done", flush=True)
    save(f"all_{period}.json", res)


# --- the $1000 account and swap ------------------------------------------------------------------------------------


def rollovers(entry_ms: int, exit_ms: int) -> int:
    """Nights held: CME rollovers (17:00 New York) passed between entry and exit; Wednesday's counts three."""
    from datetime import timedelta

    from arven.core.sessions import NEW_YORK

    a = from_ms(entry_ms).astimezone(NEW_YORK)
    b = from_ms(exit_ms).astimezone(NEW_YORK)
    n, d = 0, a.date()
    while True:
        roll = a.replace(year=d.year, month=d.month, day=d.day, hour=ROLLOVER_HOUR_NY, minute=0, second=0, microsecond=0)
        if roll > b:
            break
        if roll > a and roll.weekday() < 5:
            n += 3 if roll.weekday() == 2 else 1
        d += timedelta(days=1)
    return n


def money() -> None:
    out: dict[str, Any] = {"account_rules": {k: dataclasses.asdict(v) for k, v in OZ_RULES.items()}, "swap_per_night": SWAP_PER_NIGHT, "periods": {}}
    for period in PERIODS:
        path = OUT / f"all_{period}.json"
        if not path.exists():
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        rows: dict[str, Any] = {}
        for sid, variants in d["strategies"].items():
            rows[sid] = {}
            for key, v in variants.items():
                tr = v["trades"]
                r = np.array([t["r"] for t in tr]) if tr else np.zeros(0)
                # swap in R: nights x rate x notional / risk (notional / risk = 1 / stop_pct)
                swap = np.array([rollovers(t["entry_ms"], t["exit_ms"]) * SWAP_PER_NIGHT[t["side"]] / t["stop_pct"] for t in tr]) if tr else np.zeros(0)
                row = {"n": len(tr), "open_at_end": v["open_at_end"], "total_r": float(r.sum()), "win": float((r > 0).mean()) if len(r) else 0.0,
                       "pf": float(r[r > 0].sum() / -r[r < 0].sum()) if (r < 0).any() else None,
                       "total_r_with_swap": float((r + swap).sum()), "swap_r": float(swap.sum()),
                       "hold_h_median": float(np.median([(t["exit_ms"] - t["entry_ms"]) / 3.6e6 for t in tr])) if tr else None,
                       "stop_pct_median": float(np.median([t["stop_pct"] for t in tr])) if tr else None}
                for rk, ru in OZ_RULES.items():
                    row[rk] = summarize_account(replay_account([TradeForAccount(t["stop_pct"] * t["fill"], t["r"]) for t in tr], ru), ru)
                    row[rk + "_swap"] = summarize_account(
                        replay_account([TradeForAccount(t["stop_pct"] * t["fill"], t["r"] + s) for t, s in zip(tr, swap, strict=True)], ru), ru)
                rows[sid][key] = row
        out["periods"][period] = {"buy_hold": d["last_close"] / d["first_open"] - 1, "strategies": rows}
    save("money.json", out)
    for p, d in out["periods"].items():
        print(f"== {p}  buy&hold {d['buy_hold'] * 100:+.1f}%")
        for sid, vs in d["strategies"].items():
            row = vs["own/cfd"]
            a = row["1%"]
            print(f"  {sid:22s} n{row['n']:5d} R{row['total_r']:+8.1f} (swap {row['swap_r']:+6.1f}) win{row['win'] * 100:4.0f}%  "
                  f"$1000 -> {a['final_equity']:8.0f} dd{a['max_drawdown'] * 100:5.1f}%")


# --- S7: stop / management grid ------------------------------------------------------------------------------------

STOPS = ("F0", "S2", "C0", "F01", "F02", "F03")
MGMTS = [(tp3, after) for tp3 in (2.0, 2.618, None) for after in (None, "BE", "TP1")]
CUR: dict[str, Any] = {"stop": "F01", "tp3": 2.0, "after": None}
_ORIG_STOP, _ORIG_MGMT = sim.stop_price, sim.management_plan


def _grid_stop(s, tp):
    k = CUR["stop"]
    if k == "F0":
        return s.fib(0.0)
    if k == "S2":
        return s.level0 - s.side * 0.25 * s.atr
    if k == "C0":
        return s.level0 - s.side * 1.0 * s.atr
    if k == "RULE":  # range before the break -> fib 0.3, else fib 0.1 (the owner's 2026-10-17 idea)
        return s.fib(0.3 if s.range_box is not None else 0.1)
    return s.fib({"F01": 0.1, "F02": 0.2, "F03": 0.3}[k])


def _grid_mgmt(s, tp, fill, prices, fracs):
    p0, p1 = prices[0], prices[1]
    P, F = ((p0, p1), (0.5, 0.3)) if CUR["tp3"] is None else ((p0, p1, s.fib(CUR["tp3"])), (0.5, 0.3, 0.2))
    after = CUR["after"]
    ladder = None if after is None else (None, fill if after == "BE" else p0) + ((None,) if len(P) == 3 else ())
    return P, F, ladder, None


def _grid_tp() -> S7TradeParams:
    return S7TradeParams(entry="E3", stop="S3" if CUR["stop"] == "C0" else "S1", management="V0")


def _stats(rs: list[float]) -> dict[str, Any]:
    a = np.array(rs)
    if not len(a):
        return {"n": 0}
    eq = np.cumprod(1 + 0.01 * a)
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    return {"n": int(len(a)), "total_r": float(a.sum()), "mean_r": float(a.mean()), "win": float((a > 0).mean()),
            "pf": float(a[a > 0].sum() / -a[a < 0].sum()) if (a < 0).any() else None, "ret_1pct": float(eq[-1] - 1),
            "maxdd_1pct": float(np.max(1 - eq / peak)), "se": float(a.std(ddof=1) / np.sqrt(len(a))) if len(a) > 1 else None}


def s7grid(period: str) -> None:
    study = st.Study(PERIODS[period], instrument=INSTRUMENT, config_dir=CONFIG_DIR)
    sim.stop_price, sim.management_plan = _grid_stop, _grid_mgmt
    try:
        h4 = study.bars[Timeframe.H4]
        alpha, acc = 2 / 51, float(h4.close[0])
        ema = np.empty(len(h4.close))
        for i, cl in enumerate(h4.close):
            acc = acc + alpha * (cl - acc) if np.isfinite(cl) else acc
            ema[i] = acc
        h4_close = h4.open_time_ms + Timeframe.H4.ms

        def features(s, tfb) -> dict[str, Any]:
            arm_close = int(tfb.time_ms[s.arm_index]) + tfb.tf_ms
            j = int(np.searchsorted(h4_close, arm_close, side="right")) - 1
            trend = int(np.sign(h4.close[j] - ema[j])) if j >= 50 else 0
            price = s.fib(0.5)
            return {"arm_ms": arm_close, "side": s.side, "leg_atr": abs(s.level1 - s.level0) / s.atr, "atr_pct": s.atr / price,
                    "risk_f0_pct": abs(price - s.level0) / price, "confluence": s.confluence_score, "range": s.range_box is not None,
                    "level1_moves": s.level1_moves, "touches": len(s.touches), "with_4h_trend": trend == s.side,
                    "hour": (arm_close // 3_600_000) % 24}

        out: dict[str, Any] = {"period": period, "grid": {}, "per_setup": {}}
        for impulse in ("fvg", "none"):
            tf, p, _ = st.split(dict(S7_CFG, impulse=impulse))
            setups = study.setups(tf, p)
            print(period, impulse, "setups", len(setups), flush=True)
            for stress in (False, True):
                for stop in STOPS:
                    for tp3, after in MGMTS:
                        CUR.update(stop=stop, tp3=tp3, after=after)
                        outs = sim.run_setups(study.context(tf, p, _grid_tp(), "cfd", stress), setups)
                        key = f"{impulse}|{'x4' if stress else 'cfd'}|{stop}|{tp3}|{after}"
                        out["grid"][key] = _stats([o.net_r for o in outs if o.status == "trade"]) | {
                            "unresolved": sum(o.status == "unresolved" for o in outs)}
            ctx0 = study.context(tf, p, _grid_tp())
            rows = [features(s, ctx0.tf) for s in setups]
            for stop in STOPS:
                for tp3, after in ((2.0, None), (None, "TP1"), (None, "BE")):
                    CUR.update(stop=stop, tp3=tp3, after=after)
                    cx = study.context(tf, p, _grid_tp())
                    for i, s in enumerate(setups):
                        o = sim.simulate_setup(cx, s, i)
                        rows[i][f"{stop}|{tp3}|{after}"] = o.net_r if o.status == "trade" else None
            out["per_setup"][impulse] = rows
        save(f"s7grid_{period}.json", out)
    finally:
        sim.stop_price, sim.management_plan = _ORIG_STOP, _ORIG_MGMT


# --- S7: rules, management variants, zone filters, controls --------------------------------------------------------

ZONE_FILTERS = {
    "none (S7 as is)": lambda s: True,
    "A: iFVG in the zone": lambda s: any(z.kind == "ifvg" for z in s.confluence),
    "B: 3+ zone types": lambda s: s.confluence_score >= 3,
}


def _account(outs) -> dict[str, Any]:
    trades = sorted((o for o in outs if o.status == "trade"), key=lambda o: o.entry_time_ms)
    tr = [TradeForAccount(sum(lg.weight * abs(lg.entry_price - lg.stop) for lg in o.legs), o.net_r) for o in trades]
    return summarize_account(replay_account(tr, OZ_RULES["1%"]), OZ_RULES["1%"])


def s7rules() -> None:
    out: dict[str, Any] = {"config": S7_CFG, "periods": {}}
    for period, pk in PERIODS.items():
        study = st.Study(pk, instrument=INSTRUMENT, config_dir=CONFIG_DIR)
        tf, p, tp = st.split(S7_CFG)
        setups = study.setups(tf, p)
        row: dict[str, Any] = {}
        # as is, all cost profiles; random control; breakdowns
        row["as_is"] = st.cost_report(study, S7_CFG, "as_is")
        outs = study.outcomes(S7_CFG)
        row["random_control_cfd"] = st.random_control(study, outs, study.costs["cfd"], 200)
        row["breakdowns_cfd"] = st.breakdowns(study, S7_CFG, outs)
        row["account_1pct"] = _account(outs)
        # management variants of strategy_s7_plan
        row["managements"] = {}
        for mg in MANAGEMENTS:
            cfg = S7_CFG | {"management": mg}
            row["managements"][mg] = {f"{c}{'_x4' if s else ''}": {k: study.evaluate(cfg, c, s).get(k) for k in ("trades", "total_r", "mean_r", "win_rate")}
                                      for c, s in (("cfd", False), ("cfd", True))}
        # SMC zone filters
        row["zone_filters"] = {}
        for name, keep in ZONE_FILTERS.items():
            chosen = [s for s in setups if keep(s)]
            row["zone_filters"][name] = {}
            for c, s in (("cfd", False), ("cfd", True)):
                o = sim.run_setups(study.context(tf, p, tp, c, s), chosen)
                row["zone_filters"][name][f"{c}{'_x4' if s else ''}"] = _stats([x.net_r for x in o if x.status == "trade"]) | {"setups": len(chosen)}
        # range before the break -> stop fib 0.3 (else fib 0.1); and the two groups on their own
        sim.stop_price, sim.management_plan = _grid_stop, _grid_mgmt
        try:
            row["range_rule"] = {}
            for impulse in ("fvg", "none"):
                tfi, pi, _ = st.split(dict(S7_CFG, impulse=impulse))
                si = study.setups(tfi, pi)
                rng = [s for s in si if s.range_box is not None]
                for c, s in (("cfd", False), ("cfd", True)):
                    tag = f"{impulse}|{'x4' if s else 'cfd'}"
                    for name, stop, subset in (("all F01", "F01", si), ("rule", "RULE", si), ("range only F03", "F03", rng),
                                               ("range only F01", "F01", rng), ("no-range only F01", "F01", [x for x in si if x.range_box is None])):
                        CUR.update(stop=stop, tp3=2.0, after=None)
                        o = sim.run_setups(study.context(tfi, pi, _grid_tp(), c, s), subset)
                        row["range_rule"][f"{tag}|{name}"] = _stats([x.net_r for x in o if x.status == "trade"])
        finally:
            sim.stop_price, sim.management_plan = _ORIG_STOP, _ORIG_MGMT
        m = study.market
        row["buy_and_hold"] = float(m.close[-1] / m.open[0] - 1.0)
        out["periods"][period] = row
        save("s7rules.json", out)


def s7select() -> None:
    """S7's own 14-question procedure on gold development (a second, explicitly re-tuned variant - not the live config)."""
    dev = st.Study(BacktestPeriod.DEVELOPMENT, instrument=INSTRUMENT, config_dir=CONFIG_DIR)
    final, log = st.select(dev)
    out: dict[str, Any] = {"selected_on_gold_development": final, "btc_config": S7_CFG, "selection_log": log, "periods": {}}
    for period, pk in PERIODS.items():
        study = dev if pk == BacktestPeriod.DEVELOPMENT else st.Study(pk, instrument=INSTRUMENT, config_dir=CONFIG_DIR)
        out["periods"][period] = {"gold_selected": st.cost_report(study, final, "gold_sel"), "btc_selected": st.cost_report(study, S7_CFG, "btc_sel")}
    save("s7select.json", out)


# --- S7: full grid - touches x impulse x stop x SMC zone filter ----------------------------------------------------
# Pre-registered 2026-10-21, before the first run (owner: "full S7 report: different stops, extra zones iFVG / FVG /
# order blocks, and S7 with two touches of the line; gold first, BTC if it shows something"):
# - grid: min_touches {3, 2} x break impulse {fvg (live), none} x stop {F0, F01 (live), F02, F03, S2, C0} x zone filter
#   below; everything else is the live configuration (15m, E3 limit at fib 0.5, TP fib 1.0 / 1.272-1.618 / 2.0 at
#   50/30/20 %, no breakeven, one trade at a time), CFD costs and x4;
# - zone filters use only the setup's confluence zones (known at the arming close, overlapping the entry zone);
# - selection: on development CFD only, the highest mean R among configurations with >= 50 trades (ties: more trades);
#   validation and forward are then read once for that configuration, with x4 costs, a bootstrap CI and the
#   random-entry control. The whole grid is reported for every period, with how many configurations are positive.

FULL_STOPS = ("F01", "F0", "F02", "F03", "S2", "C0")
SMC = ("fvg", "ifvg", "order_block")
FULL_ZONES = {
    "all": lambda s: True,
    "fvg": lambda s: any(z.kind == "fvg" for z in s.confluence),
    "ifvg": lambda s: any(z.kind == "ifvg" for z in s.confluence),
    "ob": lambda s: any(z.kind == "order_block" for z in s.confluence),
    "any_smc": lambda s: any(z.kind in SMC for z in s.confluence),
    "2plus_smc": lambda s: len({z.kind for z in s.confluence if z.kind in SMC}) >= 2,
}
FULL_MIN_TRADES = 50


def full_key(touches: int, impulse: str, stop: str, zone: str) -> str:
    return f"t{touches}|{impulse}|{stop}|{zone}"


def s7full(period: str) -> None:
    study = st.Study(PERIODS[period], instrument=INSTRUMENT, config_dir=CONFIG_DIR)
    sim.stop_price, sim.management_plan = _grid_stop, _grid_mgmt
    out: dict[str, Any] = {"period": period, "grid": {}, "setups": {}}
    try:
        for touches in (3, 2):
            for impulse in ("fvg", "none"):
                tf, p, _ = st.split(dict(S7_CFG, impulse=impulse, min_touches=touches))
                setups = study.setups(tf, p)
                subsets = {z: [s for s in setups if keep(s)] for z, keep in FULL_ZONES.items()}
                out["setups"][f"t{touches}|{impulse}"] = {z: len(v) for z, v in subsets.items()}
                print(period, f"touches={touches} impulse={impulse}", {z: len(v) for z, v in subsets.items()}, flush=True)
                for stop in FULL_STOPS:
                    CUR.update(stop=stop, tp3=2.0, after=None)
                    for zone, chosen in subsets.items():
                        row = {}
                        for c, stress in (("cfd", False), ("x4", True)):
                            outs = sim.run_setups(study.context(tf, p, _grid_tp(), "cfd", stress), chosen)
                            row[c] = _stats([o.net_r for o in outs if o.status == "trade"]) | {"setups": len(chosen)}
                            if c == "cfd":
                                row["account_1pct"] = _account(outs)
                        out["grid"][full_key(touches, impulse, stop, zone)] = row
        save(f"s7full_{period}.json", out)
    finally:
        sim.stop_price, sim.management_plan = _ORIG_STOP, _ORIG_MGMT


def s7full_select() -> None:
    """The pre-registered selection on development, then validation / forward read once (see the block comment)."""
    grids = {p: load(f"s7full_{p}.json")["grid"] for p in PERIODS}
    dev = grids["development"]
    eligible = [k for k, v in dev.items() if v["cfd"].get("n", 0) >= FULL_MIN_TRADES]
    best = max(eligible, key=lambda k: (dev[k]["cfd"]["mean_r"], dev[k]["cfd"]["n"]))
    touches, impulse, stop, zone = best.split("|")
    touches_n = int(touches[1:])
    out: dict[str, Any] = {"rule": f"max mean R on development CFD, >= {FULL_MIN_TRADES} trades", "eligible": len(eligible),
                           "configurations": len(dev), "selected": best, "periods": {}}
    rng = np.random.default_rng(st.SEED)
    sim.stop_price, sim.management_plan = _grid_stop, _grid_mgmt
    try:
        for period, pk in PERIODS.items():
            g = grids[period]
            positive = {c: sum(1 for v in g.values() if v[c].get("n", 0) and v[c]["total_r"] > 0) for c in ("cfd", "x4")}
            study = st.Study(pk, instrument=INSTRUMENT, config_dir=CONFIG_DIR)
            tf, p, _ = st.split(dict(S7_CFG, impulse=impulse, min_touches=touches_n))
            chosen = [s for s in study.setups(tf, p) if FULL_ZONES[zone](s)]
            CUR.update(stop=stop, tp3=2.0, after=None)
            outs = sim.run_setups(study.context(tf, p, _grid_tp(), "cfd", False), chosen)
            rs = np.array([o.net_r for o in outs if o.status == "trade"])
            ci = np.percentile([rng.choice(rs, len(rs)).mean() for _ in range(4000)], [2.5, 97.5]).tolist() if len(rs) else None
            out["periods"][period] = {"selected": g[best], "mean_r_ci95": ci,
                                      "random_control_cfd": st.random_control(study, outs, study.costs["cfd"], 200),
                                      "positive_configs": positive, "configs_with_trades": sum(1 for v in g.values() if v["cfd"].get("n", 0))}
            v = g[best]["cfd"]
            print(f"{period:11s} {best}: n={v.get('n')} R={v.get('total_r', 0):+.2f} mean={v.get('mean_r', 0):+.3f} CI={ci} "
                  f"x4 R={g[best]['x4'].get('total_r', 0):+.2f}  positive configs cfd {positive['cfd']}/{len(g)} x4 {positive['x4']}/{len(g)}", flush=True)
    finally:
        sim.stop_price, sim.management_plan = _ORIG_STOP, _ORIG_MGMT
    save("s7full_select.json", out)


def main() -> None:
    step = sys.argv[1]
    t0 = time.perf_counter()
    if step == "crosscheck":
        crosscheck()
    elif step == "record":
        record(sys.argv[2])
    elif step == "all":
        all_strategies(sys.argv[2])
    elif step == "money":
        money()
    elif step == "s7grid":
        s7grid(sys.argv[2])
    elif step == "s7rules":
        s7rules()
    elif step == "s7select":
        s7select()
    elif step == "s7full":
        s7full(sys.argv[2])
    elif step == "s7full_select":
        s7full_select()
    else:
        raise SystemExit(__doc__)
    print(f"{step} finished in {time.perf_counter() - t0:.0f}s")


if __name__ == "__main__":
    main()

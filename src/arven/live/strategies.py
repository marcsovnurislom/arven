"""The strategies the live loop knows how to run - thin adapters over the *same* code the research used
(CLAUDE.md rule 8), never a re-implementation:

- :class:`ProviderStrategy` - S4 / S5 / S6: their ``SignalProvider`` objects, asked at every 15m close exactly as in
  the forward evaluation (``arven.paper.strategies_forward``); a market entry at the decision time, resolved on 1m bars
  with the strategy's own TP ladder.
- :class:`S7Strategy` - S7 (the owner's method): the detector (``arven.engine.strategy_s7``) announces a setup at the
  close of its arming bar as a *resting limit order* with its stop, TP ladder and expiry; the simulator
  (``arven.backtest.strategy_s7_sim.simulate_setup``) says whether it filled, was cancelled, hit targets or closed.
- :class:`CrowdedShortsStrategy` - the pre-registered funding + open-interest rule
  (``arven.engine.strategy_crowded_shorts``): a market long at the first signal of a hold block, out at the stop or
  when the hold ends (``arven.backtest.crowded_shorts_sim``).

Every strategy's parameters come from ``config/live.yaml`` (S4-S6 have none there: theirs are the pre-registered
constants in their own engine modules).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from arven.backtest.crowded_shorts_sim import resolve_block
from arven.backtest.provider import SignalProvider
from arven.backtest.strategy_s7_sim import S7Bars, S7Outcome, make_context, planned_targets, simulate_setup
from arven.core.live_config import LiveStrategyConfig
from arven.core.prices import fmt_price
from arven.core.sessions import SessionCalendar
from arven.core.timeframes import Timeframe
from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind
from arven.engine.strategy_crowded_shorts import CrowdedShortsBlock, CrowdedShortsParams, blocks, signal_mask
from arven.engine.strategy_s7 import S7Params, S7Setup, detect_setups
from arven.engine.strategy_s7_plan import S7TradeParams, ladder_r, limit_orders, management_plan, stop_price
from arven.live.base import LiveContext, LiveOutcome
from arven.paper.strategies_forward import event_times, process_events, resolve_signal
from arven.telegram.chart import ChartOverlay

SYMBOL_RISK_FRACTION = 0.01  # the owner's rule: 1 % of equity at the stop
HOUR_MS = 3_600_000


def natural_key(s: EngineSignal) -> tuple[int, int, float, float]:
    """What makes two announcements the same signal, independent of the code version stamped on it."""
    return (s.event_time_ms, s.side, round(s.entry_reference, 8), round(s.stop, 8))


# --- S4 / S5 / S6 --------------------------------------------------------------------------------------------------


class ProviderStrategy:
    """A ``SignalProvider`` (S4/S5/S6) evaluated at every 15m close; market entry, resolved on its own ladder."""

    tf = "15m"  # its decision timeframe (arven.live.conflicts priority)

    def __init__(self, cfg: LiveStrategyConfig, factory: Callable[..., SignalProvider]) -> None:
        if cfg.params:
            raise ValueError(f"{cfg.id}: S4-S6 take no params in config/live.yaml (their rules are pre-registered constants)")
        self.strategy_id = cfg.id
        self.title = cfg.title or cfg.id
        self._factory = factory

    def scan(self, ctx: LiveContext, after_ms: int, through_ms: int, stored: list[EngineSignal]) -> list[EngineSignal]:
        provider = self._factory(ctx.bars[Timeframe.H1], ctx.bars[Timeframe.M15], ctx.bars[Timeframe.H4], symbol=ctx.app.market.symbol)
        if stored and hasattr(provider, "_last_signal_ms"):
            provider._last_signal_ms = max(s.event_time_ms for s in stored)  # type: ignore[attr-defined]  # restores the cooldown
        return process_events(provider, event_times(after_ms, through_ms, ctx.app.session_calendar()), feature_version=ctx.feature_version,
                              config_hash=ctx.config_hash, commit=ctx.git_commit)

    def resolve(self, ctx: LiveContext, signal: EngineSignal) -> LiveOutcome | None:
        out = resolve_signal(signal, ctx.market, ctx.costs)
        if out is None:
            return None
        return LiveOutcome(signal, out.updates, "closed" if out.closed else "open", out.net_r if out.closed else None)


# --- S7 ------------------------------------------------------------------------------------------------------------

# 30m and 1d added 2026-10-27 (owner: more timeframes); their lower / higher frames follow the same ~4x spacing
S7_TFS = {"15m": Timeframe.M15, "30m": Timeframe.M30, "1h": Timeframe.H1, "4h": Timeframe.H4, "1d": Timeframe.D1}
S7_LOWER = {"15m": Timeframe.M5, "30m": Timeframe.M5, "1h": Timeframe.M15, "4h": Timeframe.H1, "1d": Timeframe.H4}
S7_HIGHER = {"15m": Timeframe.H1, "30m": Timeframe.H4, "1h": Timeframe.H4, "4h": None, "1d": None}
S7_WARMUP_BARS = 3000  # bars of the S7 timeframe before the forward window the detector is given (see S7Strategy._state)
S7_DETECTOR_KEYS = {"min_touches", "freeze_pullback", "count_every_touch", "level0_range_bottom", "skip_beyond_line_start",
                    "break_on_cross", "line_from_major_high", "shallow_zone",
                    "cluster_min_bars", "max_wick_pierce_atr"}  # the last two: S7 v2 (2026-10-28), from the owner's trade verdicts
S7_TRADE_KEYS = {"entry", "stop", "breakeven_after_tp1", "min_tp1_r", "management"}
# setup filter (live only, 2026-10-22): keep a setup only if at least this many *different* SMC zone types overlap its
# entry zone at the arming close - the rule pre-registered and checked once on BTC in scripts/research/s7_smc_btc.py
S7_FILTER_KEYS = {"min_smc_types"}
SMC_KINDS = ("fvg", "ifvg", "order_block")


def smc_types(s: S7Setup) -> int:
    """How many different SMC zone types (FVG, iFVG, order block) the setup's confluence has (prior levels not counted)."""
    return len({z.kind for z in s.confluence if z.kind in SMC_KINDS})


def s7_params(params: dict[str, Any]) -> tuple[str, S7Params, S7TradeParams]:
    """The study's configuration dict (``scripts/s7_study.py`` ``split``) -> detector and trade parameters."""
    unknown = set(params) - S7_DETECTOR_KEYS - S7_TRADE_KEYS - S7_FILTER_KEYS - {"tf", "impulse"}
    if unknown:
        raise ValueError(f"unknown S7 params: {sorted(unknown)}")
    if params.get("min_smc_types", 0) not in (0, 1, 2, 3):
        raise ValueError("S7 min_smc_types must be 0, 1, 2 or 3")
    if params.get("tf") not in S7_TFS:
        raise ValueError(f"S7 tf must be one of {sorted(S7_TFS)}")
    impulse = params.get("impulse", "none")
    if impulse not in ("none", "body_1atr", "fvg"):
        raise ValueError("S7 impulse must be none, body_1atr or fvg")
    det = {k: v for k, v in params.items() if k in S7_DETECTOR_KEYS}
    det["impulse_body_atr"] = 1.0 if impulse == "body_1atr" else None
    det["impulse_fvg"] = impulse == "fvg"
    return params["tf"], S7Params(**det), S7TradeParams(**{k: v for k, v in params.items() if k in S7_TRADE_KEYS})


class S7Strategy:
    """Setup armed => a resting entry (limit at fib 0.5 for E3) with stop, TP ladder and expiry; then its life."""

    def __init__(self, cfg: LiveStrategyConfig) -> None:
        self.strategy_id = cfg.id
        self.title = cfg.title or cfg.id
        self.version = cfg.version
        self.params_hash = cfg.params_hash()
        self.tf, self.p, self.tp = s7_params(cfg.params)
        self.min_smc_types = int(cfg.params.get("min_smc_types", 0))

    def _state(self, ctx: LiveContext) -> dict[str, Any]:
        """Setups since the forward start, their planned signals and the simulator context - once per tick."""
        key = f"s7:{self.strategy_id}"
        if key not in ctx.cache:
            tf = S7_TFS[self.tf]
            b = ctx.bars[tf]
            # only the last S7_WARMUP_BARS bars before the forward window: the detector looks back at most lookback_bars
            # (400) and its Wilder ATR forgets its seed within a few hundred bars, so the setups are exactly those of the
            # full history (checked 2026-10-27 on BTC, gold and ETH, all six S7 variants, with 1000 bars already) at a
            # fraction of the time - every tick used to re-scan 2020 onward (~16 s per variant per market)
            first = int(np.searchsorted(b.open_time_ms + tf.ms, ctx.window.start_ms))
            b = b.tail_from(max(0, first - S7_WARMUP_BARS))
            close_ms = b.open_time_ms + tf.ms
            found = detect_setups(b.open, b.high, b.low, b.close, self.p, volume=b.volume)
            setups = [s for s in found if ctx.window.start_ms <= int(close_ms[s.arm_index]) <= ctx.through_ms
                      and smc_types(s) >= self.min_smc_types]
            higher = S7_HIGHER[self.tf]
            sim = make_context(S7Bars.from_series(b), S7Bars.from_series(ctx.bars[S7_LOWER[self.tf]]), ctx.market, ctx.costs, self.p, self.tp,
                               higher=None if higher is None else S7Bars.from_series(ctx.bars[higher]), calendar=ctx.app.session_calendar())
            planned: list[tuple[S7Setup, EngineSignal]] = []
            for s in setups:
                sig = self._signal(ctx, sim, s)
                if sig is not None:
                    planned.append((s, sig))
            ctx.cache[key] = {"sim": sim, "setups": setups, "planned": planned, "by_key": {natural_key(sig): s for s, sig in planned}, "bars": b}
        return ctx.cache[key]

    def _signal(self, ctx: LiveContext, sim: Any, s: S7Setup) -> EngineSignal | None:
        tf_ms = S7_TFS[self.tf].ms
        arm_close = int(sim.tf.time_ms[s.arm_index]) + tf_ms
        orders = limit_orders(s, self.tp)
        entry = orders[0][0] if orders else s.fib(0.5)
        stop = stop_price(s, self.tp)
        tgt = planned_targets(sim, s)
        prices, fracs, _, _ = management_plan(s, self.tp, entry, tuple(px for px, _ in tgt), tuple(f for _, f in tgt))
        rs = ladder_r(entry, stop, s.side, prices)
        if rs is None:
            return None
        expiry_close = bar_close_after(ctx.app.session_calendar(), S7_TFS[self.tf], int(sim.tf.time_ms[s.arm_index]),
                                       self.p.cancel_after_mult * (s.arm_index - s.break_index))
        order_text = (f"limit {fmt_price(entry)} (fib 0.5)" if self.tp.entry == "E3" else
                      f"limits {', '.join(f'{fmt_price(px, entry)} x{f:g}' for px, f in orders)}" if orders else
                      f"market once a {S7_LOWER[self.tf].value} bar closes back above fib 0.5 ({fmt_price(entry)})")
        zones = ", ".join(sorted({z.kind for z in s.confluence})) or "none"
        try:
            ladder = tuple(TPLevel(r, f, px) for r, f, px in zip(rs, fracs, prices, strict=True))
            return EngineSignal(
                symbol=ctx.app.market.symbol, side=s.side, strategy_id=self.strategy_id, strategy_version=self.version, grade=Grade.EXPERIMENTAL,
                event_time_ms=arm_close, entry_reference=entry, stop=stop, tp_ladder=ladder, risk_fraction=SYMBOL_RISK_FRACTION, confidence=0.5,
                regime="n/a",
                reasons=(f"{self.tf} trend line broken, fib retest setup armed (level 0 {fmt_price(s.level0, entry)}, level 1 {fmt_price(s.level1, entry)})",
                         f"entry: {order_text}; cancelled if a {self.tf} bar closes beyond level 0 or above level 1, expires if unfilled",
                         f"confluence zones: {zones}"),
                risk_checks=(), versions=SignalVersions(ctx.feature_version, self.params_hash, ctx.git_commit),
                entry_type="limit", valid_until_ms=expiry_close,
            )
        except ValueError:
            return None  # a geometry the signal object rejects (e.g. a target on the wrong side) - no signal

    def scan(self, ctx: LiveContext, after_ms: int, through_ms: int, stored: list[EngineSignal]) -> list[EngineSignal]:
        return [sig for _, sig in self._state(ctx)["planned"] if after_ms < sig.event_time_ms <= through_ms]

    def resolve(self, ctx: LiveContext, signal: EngineSignal) -> LiveOutcome | None:
        st = self._state(ctx)
        s = st["by_key"].get(natural_key(signal))
        if s is None:
            return None  # the setup is not in this tick's data (e.g. armed before the forward window)
        return s7_outcome(signal, simulate_setup(st["sim"], s, st["setups"].index(s)))

    def overlay(self, ctx: LiveContext, signal: EngineSignal) -> ChartOverlay | None:
        """The setup behind ``signal`` for its alert picture: the broken trend line and its touches, fib 0 / 0.5 / 1
        and the entry zone - all known at the arming close (``None`` if the setup is not in this tick's data)."""
        st = self._state(ctx)
        s = st["by_key"].get(natural_key(signal))
        if s is None:
            return None
        b, tf_ms = st.get("bars", ctx.bars[S7_TFS[self.tf]]), S7_TFS[self.tf].ms  # the bars the setup's indices refer to
        t = lambda i: int(b.open_time_ms[i]) + tf_ms  # noqa: E731 - bar close times, as the picture's candles
        touches = tuple((t(i), float(b.high[i] if s.side == 1 else b.low[i])) for i in s.touches)
        return ChartOverlay(
            lines=((t(s.line.a_index), s.line.a_price, t(s.cross_index), float(s.line.at(s.cross_index)), "trend line"),),
            points=touches,
            levels=((s.fib(0.0), "fib 0"), (s.fib(0.5), "fib 0.5"), (s.fib(1.0), "fib 1")),
            zone=(s.zone_low, s.zone_high, "entry zone"), zone_from_ms=t(s.level1_index),
            start_ms=t(min(s.line.a_index, s.level0_index)),
        )


def bar_close_after(calendar: SessionCalendar, tf: Timeframe, open_ms: int, n: int) -> int:
    """Close of the ``tf`` bar ``n`` bars after the one opening at ``open_ms`` on the market's grid (S7's expiry is
    counted in bars: around the clock ``open + (n + 1) * tf``; across closures for a session market)."""
    if calendar.always_open:
        return open_ms + tf.ms * (1 + n)
    span = (n + 1) * tf.ms * 3 + 16 * 86_400_000  # far more than n trading bars plus any closure
    opens = calendar.bar_opens(tf, open_ms, open_ms + span)
    return int(opens[n]) + tf.ms


def s7_outcome(signal: EngineSignal, out: S7Outcome) -> LiveOutcome:
    """Simulator outcome -> the signal's updates and state (each leg's events are tagged with the leg when there are two)."""
    sid = signal.signal_id
    ups: list[SignalUpdate] = []
    many = len(out.fills) > 1
    for k, f in enumerate(out.fills, start=1):
        tag = f";leg={k}" if many else ""
        ups.append(SignalUpdate(sid, f.time_ms, SignalUpdateKind.FILLED, f"price={f.price:.8f};weight={f.weight:g}{tag}"))
        ups.extend(SignalUpdate(sid, e.time_ms, e.kind, e.detail + tag) for e in f.events)
    if out.status == "trade":
        return LiveOutcome(signal, tuple(sorted(ups, key=lambda u: u.time_ms)), "closed", out.net_r)
    if out.status == "unresolved":
        return LiveOutcome(signal, tuple(sorted(ups, key=lambda u: u.time_ms)), "open")
    if out.status == "end_of_data":
        return LiveOutcome(signal, (), "pending")
    t = out.status_time_ms if out.status_time_ms is not None else (out.entry_time_ms or signal.event_time_ms)
    reason = out.status.split(":", 1)[-1]
    ups.append(SignalUpdate(sid, t, SignalUpdateKind.CANCELLED, f"reason={reason}"))
    return LiveOutcome(signal, tuple(sorted(ups, key=lambda u: u.time_ms)), "cancelled")


# --- Crowded Shorts ------------------------------------------------------------------------------------------------


class CrowdedShortsStrategy:
    """Market long at the first signal of a hold block; out at the stop or when the hold ends."""

    tf = "1h"  # decided on hourly features (arven.live.conflicts priority)

    def __init__(self, cfg: LiveStrategyConfig) -> None:
        self.strategy_id = cfg.id
        self.title = cfg.title or cfg.id
        self.version = cfg.version
        self.params_hash = cfg.params_hash()
        self.p = CrowdedShortsParams(**cfg.params)

    def _blocks(self, ctx: LiveContext) -> tuple[list[CrowdedShortsBlock], dict[int, tuple[float, float]]]:
        key = f"cs:{self.strategy_id}"
        if key not in ctx.cache:
            f = ctx.features()
            keep = f.t_ms <= ctx.through_ms
            t = f.t_ms[keep]
            col = {n: f.values[keep, k] for k, n in enumerate(f.names)}
            mask = signal_mask(col["fund_z"], col["oi_z"], self.p)
            values = {int(t[i]): (float(col["fund_z"][i]), float(col["oi_z"][i])) for i in np.flatnonzero(mask)}
            ctx.cache[key] = (blocks(t, mask, self.p), values)
        return ctx.cache[key]

    def scan(self, ctx: LiveContext, after_ms: int, through_ms: int, stored: list[EngineSignal]) -> list[EngineSignal]:
        found, values = self._blocks(ctx)
        h1 = ctx.bars[Timeframe.H1]
        out = []
        for b in found:
            if not after_ms < b.start_ms <= through_ms:
                continue
            i = int(np.searchsorted(h1.open_time_ms, b.start_ms - HOUR_MS))
            if i >= len(h1) or int(h1.open_time_ms[i]) != b.start_ms - HOUR_MS or not np.isfinite(h1.close[i]):
                continue  # no closed 1h bar to quote: missing data => no signal
            ref = float(h1.close[i])
            fz, oz = values[b.start_ms]
            out.append(EngineSignal(
                symbol=ctx.app.market.symbol, side=1, strategy_id=self.strategy_id, strategy_version=self.version, grade=Grade.EXPERIMENTAL,
                event_time_ms=b.start_ms, entry_reference=ref, stop=ref * (1.0 - self.p.stop_fraction), tp_ladder=(),
                risk_fraction=SYMBOL_RISK_FRACTION, confidence=0.5, regime="n/a",
                reasons=(f"funding z-score {fz:.2f} <= {self.p.fund_z_max:g} and open-interest z-score {oz:.2f} >= {self.p.oi_z_min:g} (crowded shorts)",
                         f"market buy now; stop {self.p.stop_fraction:.0%} below the fill; no take-profit",
                         f"exit {self.p.hold_hours} h after the last qualifying signal (a repeat signal extends the hold)"),
                risk_checks=(), versions=SignalVersions(ctx.feature_version, self.params_hash, ctx.git_commit),
                max_holding_minutes=self.p.hold_hours * 60,
            ))
        return out

    def resolve(self, ctx: LiveContext, signal: EngineSignal) -> LiveOutcome | None:
        found, _ = self._blocks(ctx)
        block = next((b for b in found if b.start_ms == signal.event_time_ms), None)
        if block is None:
            return None
        trade = resolve_block(block, ctx.market, ctx.costs, self.p.stop_fraction)
        if trade is None:
            return None
        if not trade.closed:
            return LiveOutcome(signal, (), "open")
        detail = f"reason={'TIME_STOP' if trade.reason == 'TIME' else trade.reason};fraction=1.00000000;price={trade.exit:.8f}"
        return LiveOutcome(signal, (SignalUpdate(signal.signal_id, int(trade.exit_ms), SignalUpdateKind.CLOSED, detail),), "closed", trade.r)  # type: ignore[arg-type]


__all__ = ["CrowdedShortsStrategy", "ProviderStrategy", "S7Strategy", "natural_key", "s7_outcome", "s7_params"]

"""Strategy S7 simulator: armed setups -> entries -> exits, in R, net of costs
(`docs/strategy_s7_trend_break_fib.md` sections 3-7).

The plan (entry rules, stop, targets, cancellations) is :mod:`arven.engine.strategy_s7_plan`; this module only models
*execution* on bars and reuses :func:`arven.backtest.paper_tracker.track_signal` for every exit - the same 1m tracker,
cost model and "stop beats target in the same bar" rule as the S4-S6 studies. Dependency direction ``backtest ->
engine``, as for the other strategy adapters.

**Timing (no look-ahead).** A setup is known at the *close* of its arming TF bar; nothing before that close is used to
enter. Each later TF bar ``j`` is processed in time order: entries can happen inside bar ``j`` (on lower-TF / 1m bars),
and only at the close of ``j`` are the cancellation rules evaluated, so a TF bar's close never influences a decision
taken inside it. An E1 entry decided on the last lower-TF bar of ``j`` (i.e. at ``j``'s close) yields to a
cancellation at that same close.

**Fills (conservative).**
- E1 (market): the next lower-TF bar's open = the open of that 1m bar, with the cost model's adverse slippage.
- E2/E3/E4 (limits): a 1m bar fills a buy limit only if its low trades *through* the limit by the per-side slippage
  fraction (on a CFD the ask must reach the limit; chart prices are near the mid), filled at the limit, or at the open
  if the bar opened beyond it. If the fill bar also touches the stop, the leg is stopped in that bar (order unknown =>
  worse outcome); otherwise tracking starts at the next 1m bar, so a target touched earlier in the fill bar is never
  credited. The entry fee is always the taker rate (conservative for a limit).
- E4: the nearer half rests first; once it fills, the deeper half stays working until the first half's first exit
  event; pre-entry cancellations stop applying after the first fill. Each half is tracked on its own and weighted 0.5.
- One trade at a time (spec section 7): setups are taken in order of their entry time; a setup whose entry triggers
  while another trade is open is skipped ("busy"), it does not wait for a later trigger.

Missing bars => no trade (CLAUDE.md rule 5). A trade still open when the data ends is ``unresolved`` and, being still
open, blocks every later setup.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate
from arven.backtest.marketdata import MarketData
from arven.backtest.paper_tracker import TrackedUpdate, track_signal
from arven.core.config import CostsConfig
from arven.core.series import BarSeries
from arven.engine.grading import Grade
from arven.engine.ladder import ClosedLeg, resolve_legs
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel
from arven.engine.signal_events import SignalUpdateKind
from arven.engine.strategy_s7 import S7Params, S7Setup, atr, swing_highs, swing_lows
from arven.engine.strategy_s7_plan import (
    OrientedSetup,
    S7TradeParams,
    e1_trigger,
    ladder_r,
    limit_orders,
    management_plan,
    orient,
    oriented_bars,
    s3_exit_index,
    stop_price,
    targets,
    tf_cancel_reason,
)

STRATEGY_ID = "s7_trend_break_fib"
STRATEGY_VERSION = "v1"
MINUTE_MS = 60_000


@dataclass(frozen=True, slots=True)
class S7Bars:
    """One timeframe as plain arrays (``time_ms`` = bar open time)."""

    tf_ms: int
    time_ms: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    @staticmethod
    def from_series(b: BarSeries) -> S7Bars:
        return S7Bars(b.timeframe.ms, b.open_time_ms, b.open, b.high, b.low, b.close, b.volume)

    def __len__(self) -> int:
        return len(self.time_ms)


@dataclass(frozen=True, slots=True)
class S7Leg:
    weight: float
    entry_time_ms: int
    entry_price: float
    stop: float
    net_r: float  # net of entry fee, exit fees and slippage, per unit of this leg's own risk
    exit_time_ms: int  # last 1m bar the leg was open in
    first_event_ms: int  # first exit event (TP1 or stop)
    reasons: tuple[str, ...]
    ladder_r: tuple[float, ...]  # planned R of TP1-TP3 from this leg's fill (for the random-entry control)


@dataclass(frozen=True, slots=True)
class S7Fill:
    """One filled leg as the live loop reports it: the fill, the plan it was tracked with, and every tracked event so
    far (also for a leg that is still open, which :class:`S7Leg` cannot describe)."""

    weight: float
    time_ms: int
    price: float
    stop: float
    targets: tuple[float, ...]
    fractions: tuple[float, ...]
    events: tuple[TrackedUpdate, ...]
    closed: bool


@dataclass(frozen=True, slots=True)
class S7Outcome:
    setup_index: int
    status: str  # "trade" | "busy" | "cancelled:<reason>" | "expired" | "skipped:<reason>" | "no_data" | "unresolved" | "end_of_data"
    legs: tuple[S7Leg, ...] = ()
    entry_time_ms: int | None = None
    status_time_ms: int | None = None  # when a cancellation / expiry was decided (the TF bar close), for the live loop
    fills: tuple[S7Fill, ...] = ()  # every filled leg with its events (also for "unresolved"), for the live loop

    @property
    def net_r(self) -> float:
        return sum(leg.weight * leg.net_r for leg in self.legs)

    @property
    def exit_time_ms(self) -> int:
        return max(leg.exit_time_ms for leg in self.legs)


@dataclass(frozen=True, slots=True)
class _Context:
    tf: S7Bars
    lower: S7Bars
    market: MarketData
    costs: CostsConfig
    stress: bool
    p: S7Params
    tp: S7TradeParams
    tf_atr: np.ndarray
    oriented_tf: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]
    oriented_lower: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]
    resist_tf: dict[int, tuple[np.ndarray, np.ndarray]]  # side -> (confirmation time ms, raw price) of prior swings
    resist_higher: dict[int, tuple[np.ndarray, np.ndarray]]


def _swing_table(b: S7Bars, side: int, k: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Swing highs (side +1) or lows (side -1) with the time they became known: the close of the bar ``k`` bars later."""
    idx = swing_highs(b.high) if side == 1 else swing_lows(b.low)
    idx = idx[idx + k < len(b)]
    known = b.time_ms[idx + k] + b.tf_ms
    price = b.high[idx] if side == 1 else b.low[idx]
    return known.astype(np.int64), price.astype(float)


def make_context(
    tf: S7Bars, lower: S7Bars, market: MarketData, costs: CostsConfig, p: S7Params, tp: S7TradeParams,
    *, higher: S7Bars | None = None, stress: bool = False,
) -> _Context:
    empty = (np.zeros(0, dtype=np.int64), np.zeros(0))
    return _Context(
        tf=tf, lower=lower, market=market, costs=costs, stress=stress, p=p, tp=tp,
        tf_atr=atr(tf.high, tf.low, tf.close),
        oriented_tf={s: oriented_bars(s, tf.open, tf.high, tf.low, tf.close) for s in (1, -1)},
        oriented_lower={s: oriented_bars(s, lower.open, lower.high, lower.low, lower.close) for s in (1, -1)},
        resist_tf={s: _swing_table(tf, s) for s in (1, -1)},
        resist_higher={s: (_swing_table(higher, s) if higher is not None else empty) for s in (1, -1)},
    )


def _resistances(ctx: _Context, s: S7Setup, known_at_ms: int, lookback_ms: int) -> np.ndarray:
    out = []
    for known, price in (ctx.resist_tf[s.side], ctx.resist_higher[s.side]):
        m = (known <= known_at_ms) & (known > known_at_ms - lookback_ms)
        out.append(price[m])
    return np.concatenate(out)


def planned_targets(ctx: _Context, s: S7Setup) -> tuple[tuple[float, float], ...]:
    """TP1-TP3 ``(raw price, close fraction)`` as planned at the close of the arming bar (resistances known by then)."""
    known_ms = int(ctx.tf.time_ms[s.arm_index]) + ctx.tf.tf_ms
    return targets(s, ctx.tp, _resistances(ctx, s, known_ms, ctx.p.lookback_bars * ctx.tf.tf_ms))


def _bar_at(market: MarketData, t_ms: int) -> int | None:
    i = market.first_at_or_after(t_ms)
    return i if i < len(market) and int(market.time_ms[i]) == t_ms else None


def _sigma(ctx: _Context, i: int) -> float:
    m = ctx.market
    return slippage_fraction(float(m.open[i]), float(m.high[i]), float(m.low[i]), ctx.costs, ctx.stress)


def _limit_fill(ctx: _Context, side: int, limit: float, i0: int, i1: int) -> tuple[int, float] | None:
    """First 1m bar in ``[i0, i1)`` that fills a resting limit (see the module docstring) and its raw fill price."""
    m = ctx.market
    for i in range(i0, i1):
        sig = _sigma(ctx, i)
        o = float(m.open[i])
        if side == 1 and float(m.low[i]) <= limit * (1.0 - sig):
            return i, min(o, limit)
        if side == -1 and float(m.high[i]) >= limit * (1.0 + sig):
            return i, max(o, limit)
    return None


def _engine_signal(s: S7Setup, fill: float, stop: float, prices: tuple[float, ...], rs: tuple[float, ...], fracs: tuple[float, ...], t_ms: int, max_minutes: int | None) -> EngineSignal:
    ladder = tuple(TPLevel(r, f, px) for r, f, px in zip(rs, fracs, prices, strict=True))
    return EngineSignal(
        symbol="BTCUSDT", side=s.side, strategy_id=STRATEGY_ID, strategy_version=STRATEGY_VERSION, grade=Grade.EXPERIMENTAL,
        event_time_ms=t_ms, entry_reference=fill, stop=stop, tp_ladder=ladder, risk_fraction=0.01, confidence=0.5,
        regime="S7", reasons=("S7 trend-break fib retest",), risk_checks=(), versions=SignalVersions("v1", "s7-sim", None),
        max_holding_minutes=max_minutes,
    )


def _track_leg(ctx: _Context, s: S7Setup, os_: OrientedSetup, weight: float, fill_i: int, fill: float, market_order: bool) -> tuple[S7Leg | str, S7Fill | None]:
    """Resolve one filled leg; returns the leg or a status string (``skipped:...`` / ``unresolved``), and the fill as
    the live loop reports it (``None`` if the leg was skipped)."""
    m, tp, side = ctx.market, ctx.tp, s.side
    stop = stop_price(s, tp)
    tgt = planned_targets(ctx, s)
    prices = tuple(px for px, _ in tgt)
    fracs = tuple(f for _, f in tgt)
    rs = ladder_r(fill, stop, side, prices)
    if rs is None:
        return "skipped:invalid_geometry", None
    if tp.min_tp1_r is not None and rs[0] < tp.min_tp1_r:
        return "skipped:tp1_below_min_r", None
    prices, fracs, stop_ladder, be_at_r = management_plan(s, tp, fill, prices, fracs)
    rs = ladder_r(fill, stop, side, prices)
    if rs is None:
        return "skipped:invalid_geometry", None
    risk = side * (fill - stop)
    fee_rate = taker_fee_rate(ctx.costs)
    entry_fee_r = fill * fee_rate / risk
    fill_ms = int(m.time_ms[fill_i])

    def as_fill(events: tuple[TrackedUpdate, ...], closed: bool) -> S7Fill:
        return S7Fill(weight, fill_ms, fill, stop, prices, fracs, events, closed)

    if not market_order:
        o, h, lo = float(m.open[fill_i]), float(m.high[fill_i]), float(m.low[fill_i])
        if (lo <= stop) if side == 1 else (h >= stop):  # stop also touched in the fill bar: assume the worse order
            exit_px = adverse_price(stop, -side, slippage_fraction(o, h, lo, ctx.costs, ctx.stress))
            res = resolve_legs(fill, stop, side, [ClosedLeg(1.0, exit_px, exit_px * fee_rate, "STOP")])
            ev = (TrackedUpdate(fill_ms, SignalUpdateKind.CLOSED, "reason=STOP;fraction=1.00000000"),)
            return S7Leg(weight, fill_ms, fill, stop, res.r_multiple - entry_fee_r, fill_ms, fill_ms, ("STOP",), rs), as_fill(ev, True)
        start_i = fill_i + 1
    else:
        start_i = fill_i
    if start_i >= len(m):
        return "unresolved", as_fill((), False)
    start_ms = int(m.time_ms[start_i])

    max_minutes = None
    if tp.stop == "S3":  # close-based exit: the first TF bar closing below level 0 whose close is after the fill
        j_fill = int(np.searchsorted(ctx.tf.time_ms, fill_ms, side="right")) - 1
        j_exit = s3_exit_index(os_, ctx.oriented_tf[side][3], max(j_fill, s.arm_index + 1))
        if j_exit is not None:
            exit_ms = int(ctx.tf.time_ms[j_exit]) + ctx.tf.tf_ms
            if exit_ms <= start_ms:  # the close fell at or before the first tracked bar: out at its open
                o, h, lo = float(m.open[start_i]), float(m.high[start_i]), float(m.low[start_i])
                exit_px = adverse_price(o, -side, slippage_fraction(o, h, lo, ctx.costs, ctx.stress))
                res = resolve_legs(fill, stop, side, [ClosedLeg(1.0, exit_px, exit_px * fee_rate, "S3_CLOSE")])
                ev = (TrackedUpdate(start_ms, SignalUpdateKind.CLOSED, "reason=S3_CLOSE;fraction=1.00000000"),)
                return S7Leg(weight, fill_ms, fill, stop, res.r_multiple - entry_fee_r, start_ms, start_ms, ("S3_CLOSE",), rs), as_fill(ev, True)
            max_minutes = (exit_ms - start_ms) // MINUTE_MS

    sig = _engine_signal(s, fill, stop, prices, rs, fracs, start_ms, max_minutes)
    tracked = track_signal(sig, start_ms, fill, m, ctx.costs, stress=ctx.stress, move_stop_to_breakeven_after_first_tp=tp.breakeven_after_tp1,
                           stop_after_tp=stop_ladder, breakeven_at_r=be_at_r)
    res = tracked.resolution
    if res is None or not res.fully_closed:
        return "unresolved", as_fill(tracked.updates, False)
    closes = [u.time_ms for u in tracked.updates if u.kind.name in ("TP_HIT", "CLOSED")]
    leg = S7Leg(weight, fill_ms, fill, stop, res.r_multiple - entry_fee_r, max(closes), min(closes), tuple(lg.exit_reason for lg in res.legs), rs)
    return leg, as_fill(tracked.updates, True)


def simulate_setup(ctx: _Context, s: S7Setup, index: int) -> S7Outcome:
    """The setup's own life, ignoring other trades (``run_setups`` applies the one-trade-at-a-time rule)."""
    tf, lower, m, side = ctx.tf, ctx.lower, ctx.market, s.side
    os_ = orient(s)
    o_tf, _h_tf, lo_tf, c_tf = ctx.oriented_tf[side]
    _o_lw, _h_lw, lo_lw, c_lw = ctx.oriented_lower[side]
    orders = limit_orders(s, ctx.tp)
    last_j = min(s.arm_index + ctx.p.cancel_after_mult * (s.arm_index - s.break_index), len(tf) - 1)
    touched = bool(lo_tf[s.arm_index] <= os_.zone_near)  # reached on the arming bar itself (known at its close)

    for j in range(s.arm_index + 1, last_j + 1):
        w0 = int(tf.time_ms[j])
        w1 = w0 + tf.tf_ms
        if not math.isfinite(c_tf[j]):
            return S7Outcome(index, "no_data", status_time_ms=w1)
        if not orders:  # E1 on the lower timeframe
            k0, k1 = (int(x) for x in np.searchsorted(lower.time_ms, [w0, w1]))
            k, touched = e1_trigger(os_, lo_lw[k0:k1], c_lw[k0:k1], touched)
            if k is not None:
                entry_ms = int(lower.time_ms[k0 + k]) + lower.tf_ms
                if entry_ms >= w1 and (reason := tf_cancel_reason(os_, j, o_tf, lo_tf, c_tf, tf.volume, ctx.tf_atr, ctx.p)):
                    return S7Outcome(index, f"cancelled:{reason}", status_time_ms=w1)
                i = _bar_at(m, entry_ms)
                if i is None:
                    return S7Outcome(index, "no_data", status_time_ms=entry_ms)
                fill = adverse_price(float(m.open[i]), side, _sigma(ctx, i))
                return _outcome(index, entry_ms, (_track_leg(ctx, s, os_, 1.0, i, fill, market_order=True),))
        else:
            i0, i1 = m.first_at_or_after(w0), m.first_at_or_after(w1)
            first = _limit_fill(ctx, side, orders[0][0], i0, i1)
            if first is not None:
                return _limit_entry(ctx, s, os_, index, orders, first)
        reason = tf_cancel_reason(os_, j, o_tf, lo_tf, c_tf, tf.volume, ctx.tf_atr, ctx.p)
        if reason:
            return S7Outcome(index, f"cancelled:{reason}", status_time_ms=w1)
    if last_j < len(tf) - 1:
        return S7Outcome(index, "expired", status_time_ms=int(tf.time_ms[last_j]) + tf.tf_ms)
    return S7Outcome(index, "end_of_data")


def _limit_entry(ctx: _Context, s: S7Setup, os_: OrientedSetup, index: int, orders: tuple[tuple[float, float], ...], first: tuple[int, float]) -> S7Outcome:
    i, px = first
    first_leg = _track_leg(ctx, s, os_, orders[0][1], i, px, market_order=False)
    legs = [first_leg]
    leg1 = first_leg[0]
    if len(orders) > 1 and isinstance(leg1, S7Leg):
        # the deeper half works until the first exit event, that bar included: if price reached the stop or TP1 in that
        # bar and also the deeper limit, the limit is assumed filled (for a stop that is the worse outcome)
        until = ctx.market.first_at_or_after(leg1.first_event_ms) + 1
        second = _limit_fill(ctx, s.side, orders[1][0], i, until)
        if second is not None:
            legs.append(_track_leg(ctx, s, os_, orders[1][1], second[0], second[1], market_order=False))
    return _outcome(index, int(ctx.market.time_ms[i]), tuple(legs))


def _outcome(index: int, entry_ms: int, legs: tuple[tuple[S7Leg | str, S7Fill | None], ...]) -> S7Outcome:
    fills = tuple(f for _, f in legs if f is not None)
    for leg, _ in legs:
        if isinstance(leg, str):
            return S7Outcome(index, leg, entry_time_ms=entry_ms, fills=fills)
    return S7Outcome(index, "trade", tuple(leg for leg, _ in legs), entry_ms, fills=fills)  # type: ignore[misc]


def run_setups(ctx: _Context, setups: list[S7Setup]) -> list[S7Outcome]:
    """Every setup's outcome with the one-trade-at-a-time rule, taken in order of entry time."""
    raw = [simulate_setup(ctx, s, i) for i, s in enumerate(setups)]
    order = sorted(range(len(raw)), key=lambda i: (raw[i].entry_time_ms if raw[i].entry_time_ms is not None else math.inf, i))
    out = list(raw)
    free_at = -math.inf
    for i in order:
        r = raw[i]
        if r.entry_time_ms is None:
            continue
        if r.entry_time_ms < free_at:
            out[i] = S7Outcome(r.setup_index, "busy")
            continue
        if r.status == "trade":
            free_at = r.exit_time_ms + MINUTE_MS
        elif r.status == "unresolved":
            free_at = math.inf  # still open when the data ends: nothing after it can be taken
    return out

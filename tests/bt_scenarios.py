"""Independent naive reference engine and random scenario generator shared by the backtest tests."""

import math

import numpy as np
from bt_helpers import FUNDING_INTERVAL, HOUR, T0, bt_config, make_market

from arven.core.signal import Signal
from arven.core.types import Action

MIN = 60_000


def oracle(md, funding_rates, signals, app, cfg, stress):
    costs = app.costs
    fee = costs.fees.taker_fee_bps / 1e4
    t, o, h, l, c = md.time_ms, md.open, md.high, md.low, md.close  # noqa: E741
    n = len(t)
    start, end = md.window_start_ms, md.window_end_ms
    lev, mmr, step, min_n, lat = cfg.leverage, cfg.maintenance_margin_rate, cfg.qty_step_btc, cfg.min_notional_usdt, cfg.latency_ms
    idx = {int(x): i for i, x in enumerate(t)}

    def sigma(j):
        rng = 1e4 * (h[j] - l[j]) / o[j]
        s = costs.slippage.stress_multiplier if stress else 1.0
        return s * (costs.slippage.fixed_bps + costs.slippage.volatility_multiplier * rng) / 1e4

    wallet = cfg.initial_equity_usdt
    pos = None
    pend_e = pend_c = None
    trades, funds, decisions = [], [], []

    def close_pos(j, ref, reason, exit_time):
        nonlocal wallet, pos, pend_c
        d, q = pos["d"], pos["q"]
        if reason == "LIQUIDATION":
            conf = max(pos["m"] + pos["fund"], 0.0) if cfg.liquidation_includes_funding else pos["m"]
            net = -conf - pos["fee"] + pos["fund"]
            wallet -= conf
            px = ref
        else:
            sg = sigma(j)
            px = ref * (1 - d * sg)
            fx = fee * q * px
            wallet += d * q * (px - pos["pe"]) - fx
            gross = d * q * (ref - pos["ref_e"])
            net = gross - (pos["slip"] + q * ref * sg) - (pos["fee"] + fx) + pos["fund"]
        trades.append((pos["t"], exit_time, reason, round(q, 9), net, pos["pe"], px))
        pos = None
        pend_c = None

    for j in range(n):
        tau = int(t[j])
        if tau % HOUR == 0:
            eq = wallet if (pos is None or j == 0) else wallet + pos["d"] * pos["q"] * (c[j - 1] - pos["pe"])
            decisions.append((tau, eq))
            sig = signals.get(tau)
            if sig is not None:
                if sig.action == Action.NO_TRADE:
                    if sig.close_position and pos is not None and pend_c is None and (tau + lat) in idx:
                        pend_c = tau + lat
                else:
                    d = 1 if sig.action == Action.LONG else -1
                    if pos is None and pend_e is None and sig.notional_fraction <= lev and (tau + lat) in idx:
                        pend_e = dict(elig=tau + lat, d=d, eq=eq, f=sig.notional_fraction, sp=sig.stop_pct, tp=sig.take_profit_pct,
                                      mh=sig.max_holding_minutes, sig_t=tau)
        oj, hj, lj = float(o[j]), float(h[j]), float(l[j])
        if pos is not None and tau in funding_rates and tau > pos["t"]:
            cash = -pos["d"] * pos["q"] * oj * funding_rates[tau]
            wallet += cash
            pos["fund"] += cash
            funds.append((tau, cash))
            if cfg.liquidation_includes_funding:
                mb = pos["m"] + pos["fund"]
                pos["lp"] = (pos["pe"] - mb / pos["q"]) / (1 - mmr) if pos["d"] > 0 else (pos["pe"] + mb / pos["q"]) / (1 + mmr)
        if pos is not None and pos["t"] < tau:
            d = pos["d"]
            if (d > 0 and oj <= pos["lp"]) or (d < 0 and oj >= pos["lp"]):
                close_pos(j, oj, "LIQUIDATION", tau)
                continue
            if pos["S"] is not None and ((d > 0 and oj <= pos["S"]) or (d < 0 and oj >= pos["S"])):
                close_pos(j, oj, "STOP", tau)
                continue
            if pos["ts"] is not None and tau >= pos["ts"]:
                close_pos(j, oj, "TIME_STOP", tau)
                continue
            if pend_c is not None and tau >= pend_c:
                close_pos(j, oj, "SIGNAL_CLOSE", tau)
                continue
        elif pend_c is not None and tau >= pend_c:
            pend_c = None
        if pos is None and pend_e is not None and tau == pend_e["elig"]:
            e = pend_e
            pend_e = None
            d = e["d"]
            sg = sigma(j)
            pe = oj * (1 + d * sg)
            q = max(math.floor(e["f"] * e["eq"] / pe / step), 0) * step
            notional = q * pe
            ok = q > 0 and notional >= min_n
            S = None if e["sp"] is None else pe * (1 - d * e["sp"])
            if ok and S is not None and ((d > 0 and S >= oj) or (d < 0 and S <= oj)):
                ok = False
            fe = fee * notional
            m = notional / lev
            if ok and m + fe > wallet:
                ok = False
            if ok:
                lp = pe * (1 - 1 / lev) / (1 - mmr) if d > 0 else pe * (1 + 1 / lev) / (1 + mmr)
                wallet -= fe
                pos = dict(d=d, q=q, pe=pe, ref_e=oj, t=tau, m=m, fee=fe, slip=q * oj * sg, fund=0.0, lp=lp, S=S,
                           T=None if e["tp"] is None else pe * (1 + d * e["tp"]),
                           ts=None if e["mh"] is None else tau + e["mh"] * MIN)
        if pos is not None:
            d, S, T, lp = pos["d"], pos["S"], pos["T"], pos["lp"]
            if d > 0:
                hl, hs, ht = lj <= lp, S is not None and lj <= S, T is not None and hj >= T
                liq_first = hl and (not hs or lp >= S)
            else:
                hl, hs, ht = hj >= lp, S is not None and hj >= S, T is not None and lj <= T
                liq_first = hl and (not hs or lp <= S)
            if liq_first:
                close_pos(j, lp, "LIQUIDATION", tau)
            elif hs:
                close_pos(j, S, "STOP", tau)
            elif ht:
                close_pos(j, T, "TAKE_PROFIT", tau)
    if pos is not None:
        close_pos(n - 1, float(c[n - 1]), "END_OF_PERIOD", end)
    return trades, funds, decisions, wallet


def random_scenario(seed):
    rng = np.random.default_rng(seed)
    hours = int(rng.integers(12, 60))
    n = hours * 60
    vol = float(rng.uniform(0.0002, 0.004))
    bars, last = {}, 30_000.0
    for i in range(n):
        gap = rng.normal(0, vol * 0.5) + (rng.choice([-1, 1]) * rng.uniform(0.02, 0.08) if rng.random() < 0.0015 else 0.0)
        op = last * (1 + gap)
        cl = op * (1 + rng.normal(0, vol))
        hi = max(op, cl) * (1 + abs(rng.normal(0, vol * 0.5)))
        lo = min(op, cl) * (1 - abs(rng.normal(0, vol * 0.5)))
        bars[i] = (op, hi, lo, cl)
        last = cl
    rates = {T0 + k * FUNDING_INTERVAL: float(rng.normal(1e-4, 3e-3)) for k in range(hours // 8 + 2)}  # large: funding can liquidate
    market = make_market(hours, bars, funding_rates=rates)
    signals = {}
    for k in range(hours):
        if rng.random() < 0.18:
            t = T0 + k * HOUR
            if rng.random() < 0.2:
                signals[t] = Signal(t, Action.NO_TRADE, close_position=True)
            else:
                action = Action.LONG if rng.random() < 0.5 else Action.SHORT
                signals[t] = Signal(
                    t, action, notional_fraction=float(rng.uniform(0.2, 3.4)),
                    stop_pct=None if rng.random() < 0.3 else float(rng.uniform(0.002, 0.04)),
                    take_profit_pct=None if rng.random() < 0.3 else float(rng.uniform(0.002, 0.06)),
                    max_holding_minutes=None if rng.random() < 0.4 else int(rng.integers(30, 900)),
                )
    cfg = bt_config(
        leverage=float(rng.choice([1.0, 2.0, 3.0, 5.0, 10.0])),
        latency_minutes=int(rng.choice([0, 0, 7, 30])),
        liquidation_includes_funding=bool(rng.random() < 0.5),
    )
    return hours, market, rates, signals, cfg, bool(rng.random() < 0.3)



"""Edge lab: walk-forward search for a robust BTC edge (research-only; nothing in ``src/`` imports this).

Protocol (fixed before any result was seen, 2026-10-11):
- Data: development + validation only (2020-01-01 -> 2025-01-01), loaded through ``SplitGuard`` windows; the sealed test
  period is never read.
- Decision at each 1h close ``t`` using only Stage 3 features at ``t`` (leakage-tested) and causal transforms of past bars;
  the position is entered at the open of the next hour (the 1m open at ``t``) and held over ``[t, t+1h)``.
- Costs on every change of position: CFD = 1.25 bp per side (spread; ``config/costs_cfd_justmarkets.yaml``), perp =
  5 bp taker + 1 bp + 0.1 x the 1m range... approximated here as 7 bp per side, plus historical funding on the position held
  into each funding time. Stress = CFD x4.
- Walk-forward: train 12 months, test the next 3 months, step 3 months; the first test quarter starts 2021-07-01, the last
  ends 2025-01-01 (14 out-of-sample quarters). In each fold every family picks its parameters on the train window only
  (best train Sharpe among settings with enough trades); only the stitched test quarters are reported.
- A family "passes" only if, out of sample, it is positive under CFD *and* CFD x4 *and* perp costs, has a Sharpe t-stat above
  the Bonferroni threshold for the number of families tried, and is positive in most test quarters. Results of every family are
  printed and written to ``data/research/edge_lab.json``.
"""

from __future__ import annotations

import itertools
import json
import math
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from arven.core.config import load_config
from arven.core.features_config import load_features_config
from arven.core.splitguard import BacktestPeriod
from arven.runs import load_inputs, make_guard

H = 3_600_000
DAY = 24 * H
COST = {"cfd": 1.25e-4, "cfd_x4": 5.0e-4, "perp": 7.0e-4}
HOURS_PER_YEAR = 24 * 365


# ----------------------------------------------------------------------------------------------- data


@dataclass
class Data:
    t: np.ndarray  # decision times (hour closes), ms
    f: dict[str, np.ndarray]  # Stage 3 features at t
    o: np.ndarray  # 1h open of the hour starting at t (= entry price)
    h: np.ndarray
    lo: np.ndarray
    c: np.ndarray  # 1h OHLC of the hour that *closed* at t (known at t)
    ret: np.ndarray  # open(t+1h) / open(t) - 1: the return of holding over [t, t+1h)
    funding: np.ndarray  # funding rate settled at time t (0 where none)
    hour: np.ndarray
    dow: np.ndarray

    def __len__(self) -> int:
        return len(self.t)


def load() -> Data:
    app, fcfg = load_config(), load_features_config()
    guard = make_guard(app)
    ts, feats, opens, highs, lows, closes, fund = [], [], [], [], [], [], []
    for per in (BacktestPeriod.DEVELOPMENT, BacktestPeriod.VALIDATION):
        li = load_inputs(app, fcfg, guard.resolve(per))
        m, fd = li.market, li.features
        ts.append(fd.t_ms)
        feats.append(fd.values)
        names = fd.names
        # hourly OHLC from 1m: hour k covers [t_k - 1h, t_k) for the decision grid t_k
        hour_of = (m.time_ms // H) * H + H  # the decision time at which each 1m bar's hour closes
        idx = np.searchsorted(fd.t_ms, hour_of)
        ok = (idx < len(fd.t_ms)) & (fd.t_ms[np.minimum(idx, len(fd.t_ms) - 1)] == hour_of)
        n = len(fd.t_ms)
        hi = np.full(n, -np.inf); lw = np.full(n, np.inf); cl = np.full(n, np.nan)
        np.maximum.at(hi, idx[ok], m.high[ok]); np.minimum.at(lw, idx[ok], m.low[ok])
        cl[idx[ok]] = m.close[ok]  # 1m bars are in time order, so the last write is the hour's close
        hi[~np.isfinite(hi)] = np.nan; lw[~np.isfinite(lw)] = np.nan
        # entry open at t: the 1m bar opening at t
        j = np.searchsorted(m.time_ms, fd.t_ms)
        op = np.full(n, np.nan)
        good = (j < len(m.time_ms)) & (m.time_ms[np.minimum(j, len(m.time_ms) - 1)] == fd.t_ms)
        op[good] = m.open[j[good]]
        fr = np.zeros(n)
        fi = np.searchsorted(fd.t_ms, m.funding_time_ms)
        fok = (fi < n) & (fd.t_ms[np.minimum(fi, n - 1)] == m.funding_time_ms) & np.isfinite(m.funding_rate)
        fr[fi[fok]] = m.funding_rate[fok]
        opens.append(op); highs.append(hi); lows.append(lw); closes.append(cl); fund.append(fr)
    t = np.concatenate(ts)
    vals = np.vstack(feats)
    o = np.concatenate(opens)
    ret = np.full(len(t), np.nan)
    ret[:-1] = o[1:] / o[:-1] - 1.0
    ret[~np.isfinite(ret)] = 0.0  # a missing open = no return (flat); rare gaps
    f = {n: vals[:, k] for k, n in enumerate(names)}
    return Data(t, f, o, np.concatenate(highs), np.concatenate(lows), np.concatenate(closes), ret, np.concatenate(fund),
                ((t // H) % 24).astype(int), (((t // DAY) + 3) % 7).astype(int))  # 1970-01-01 was a Thursday -> Monday = 0


# ----------------------------------------------------------------------------------------------- P&L


def pnl(pos: np.ndarray, d: Data, cost: str) -> np.ndarray:
    """Hourly net return of holding ``pos[t]`` over [t, t+1h) at 1x notional."""
    pos = np.nan_to_num(pos)
    gross = pos * d.ret
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    net = gross - turn * COST[cost]
    if cost == "perp":  # funding at time t is paid by the position held into t (pos[t-1])
        held = np.concatenate([[0.0], pos[:-1]])
        net = net - held * d.funding
    return net


def stats(r: np.ndarray, pos: np.ndarray) -> dict[str, float]:
    if len(r) == 0:
        return {"ret": 0.0, "sharpe": 0.0, "maxdd": 0.0, "trades": 0, "exposure": 0.0}
    eq = np.cumsum(r)
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq))
    sd = r.std()
    entries = int(np.sum((pos != 0) & (np.concatenate([[0.0], pos[:-1]]) != pos)))
    return {"ret": float(eq[-1]), "sharpe": float(r.mean() / sd * math.sqrt(HOURS_PER_YEAR)) if sd > 0 else 0.0, "maxdd": dd,
            "trades": entries, "exposure": float(np.mean(pos != 0))}


# ----------------------------------------------------------------------------------------------- signal helpers (all causal)


def hold(events: np.ndarray, hours: int) -> np.ndarray:
    """Position = the most recent non-zero event within the last ``hours`` hours (event at t acts from t)."""
    pos = np.zeros(len(events))
    last, left = 0.0, 0
    for i, e in enumerate(events):
        if e != 0:
            last, left = e, hours
        if left > 0:
            pos[i] = last
            left -= 1
    return pos


def daily(pos: np.ndarray, d: Data) -> np.ndarray:
    """Only change the position at 00:00 UTC (fewer trades)."""
    out = np.empty_like(pos)
    cur = 0.0
    for i in range(len(pos)):
        if d.hour[i] == 0:
            cur = pos[i]
        out[i] = cur
    return out


def past_close(d: Data, lag: int) -> np.ndarray:
    x = np.full(len(d), np.nan)
    x[lag:] = d.c[:-lag]
    return x


def roll_max(x: np.ndarray, n: int) -> np.ndarray:
    """max of x[t-n+1 .. t] (inclusive of t: the bar closed at t is known at t)."""
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full(len(x), np.nan)
    out[n - 1:] = np.nanmax(sliding_window_view(x, n), axis=1)
    return out


def roll_min(x: np.ndarray, n: int) -> np.ndarray:
    return -roll_max(-x, n)


def clip_ls(sig: np.ndarray, mode: str) -> np.ndarray:
    return np.where(sig > 0, 1.0, 0.0) if mode == "long" else (np.where(sig < 0, -1.0, 0.0) if mode == "short" else np.sign(sig))


# ----------------------------------------------------------------------------------------------- families


@dataclass
class Family:
    name: str
    grid: list[dict[str, Any]]
    make: Callable[[Data, dict[str, Any], np.ndarray], np.ndarray]  # (data, params, train_mask) -> position over all t
    notes: str = ""
    cache: dict[str, np.ndarray] = field(default_factory=dict)

    def pos(self, d: Data, p: dict[str, Any], train: np.ndarray, learns: bool) -> np.ndarray:
        key = json.dumps(p, sort_keys=True)
        if learns:
            return self.make(d, p, train)
        if key not in self.cache:
            self.cache[key] = self.make(d, p, train)
        return self.cache[key]


def g(**axes: list[Any]) -> list[dict[str, Any]]:
    keys = list(axes)
    return [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*axes.values())]


def f_tsmom(d, p, _):
    sig = d.c / past_close(d, p["L"]) - 1.0
    return daily(clip_ls(np.nan_to_num(sig), p["mode"]), d)


def f_ema(d, p, _):
    return daily(clip_ls(np.nan_to_num(d.f[p["feat"]]), p["mode"]), d)


def f_donchian(d, p, _):
    n = p["N"]
    up, dn = roll_max(d.h, n), roll_min(d.lo, n)
    up_x, dn_x = roll_min(d.lo, max(2, n // 2)), roll_max(d.h, max(2, n // 2))
    prev_up = np.concatenate([[np.nan], up[:-1]]); prev_dn = np.concatenate([[np.nan], dn[:-1]])
    prev_upx = np.concatenate([[np.nan], up_x[:-1]]); prev_dnx = np.concatenate([[np.nan], dn_x[:-1]])
    pos = np.zeros(len(d)); cur = 0.0
    for i in range(len(d)):
        c = d.c[i]
        if not np.isfinite(c):
            pos[i] = cur; continue
        if cur <= 0 and p["mode"] != "short" and np.isfinite(prev_up[i]) and c > prev_up[i]:
            cur = 1.0
        elif cur >= 0 and p["mode"] != "long" and np.isfinite(prev_dn[i]) and c < prev_dn[i]:
            cur = -1.0
        elif cur > 0 and np.isfinite(prev_upx[i]) and c < prev_upx[i]:
            cur = 0.0
        elif cur < 0 and np.isfinite(prev_dnx[i]) and c > prev_dnx[i]:
            cur = 0.0
        pos[i] = cur
    return pos


def f_funding(d, p, _):
    z = np.nan_to_num(d.f["fund_z"])
    ev = np.where(z >= p["z"], -1.0, np.where(z <= -p["z"], 1.0, 0.0))
    return hold(clip_ls(ev, p["mode"]), p["H"])


def f_liq(d, p, _):
    k = np.nan_to_num(d.f["h1_ret_1"] / d.f["h1_atr_pct"])
    oi = np.nan_to_num(d.f["oi_chg_1h"])
    ev = np.where((k <= -p["k"]) & (oi <= -p["oi"]), 1.0, np.where((k >= p["k"]) & (oi <= -p["oi"]), -1.0, 0.0))
    return hold(clip_ls(ev, p["mode"]), p["H"])


def f_rsi_pull(d, p, _):
    trend = np.nan_to_num(d.f["h4_ema_dist_200"])
    rsi = np.nan_to_num(d.f["h1_rsi"], nan=50.0)
    ev = np.where((trend > 0) & (rsi < p["r"]), 1.0, np.where((trend < 0) & (rsi > 100 - p["r"]), -1.0, 0.0))
    return hold(clip_ls(ev, p["mode"]), p["H"])


def f_bb_revert(d, p, _):
    z = np.nan_to_num(d.f["h1_bb_z"])
    ev = np.where(z <= -p["z"], 1.0, np.where(z >= p["z"], -1.0, 0.0))
    return hold(clip_ls(ev, p["mode"]), p["H"])


def f_season(d, p, train):
    """Learn on the train window which hours-of-day (or weekdays) have a significantly positive/negative mean return."""
    key = d.hour if p["by"] == "hour" else d.dow
    k = 24 if p["by"] == "hour" else 7
    sig = np.zeros(k)
    for v in range(k):
        r = d.ret[train & (key == v)]
        if len(r) > 30 and r.std() > 0:
            tt = r.mean() / r.std() * math.sqrt(len(r))
            sig[v] = 1.0 if tt > p["tau"] else (-1.0 if tt < -p["tau"] else 0.0)
    return clip_ls(sig[key], p["mode"])


def f_taker(d, p, _):
    x = np.nan_to_num(d.f["h1_taker_buy_ratio"], nan=0.5)
    ev = np.where(x >= p["hi"], 1.0, np.where(x <= 1 - p["hi"], -1.0, 0.0)) * (1 if p["dir"] == "follow" else -1)
    return hold(clip_ls(ev, p["mode"]), p["H"])


def f_oi_div(d, p, _):
    pr = np.nan_to_num(d.f["h1_ret_4"]); oi = np.nan_to_num(d.f["oi_chg_4h"])
    a = p["a"]
    # price up while OI falls = short covering (fade it); price down while OI rises = new shorts (fade: squeeze risk)
    ev = np.where((pr > a) & (oi < -p["oi"]), -1.0, np.where((pr < -a) & (oi > p["oi"]), 1.0, 0.0))
    return hold(clip_ls(ev, p["mode"]), p["H"])


def f_squeeze_break(d, p, _):
    vr = np.nan_to_num(d.f["h1_vol_ratio"], nan=1.0)
    dp = np.nan_to_num(d.f["h1_donchian_pos_24"], nan=0.5)
    ev = np.where((vr < p["vr"]) & (dp >= 0.999), 1.0, np.where((vr < p["vr"]) & (dp <= 0.001), -1.0, 0.0))
    return hold(clip_ls(ev, p["mode"]), p["H"])


def f_trend_vol(d, p, _):
    """Trend (4h EMA200 side) only while realised vol is below its own recent level."""
    trend = np.sign(np.nan_to_num(d.f["h4_ema_dist_200"]))
    vr = np.nan_to_num(d.f["h1_vol_ratio"], nan=1.0)
    return daily(clip_ls(np.where(vr < p["vr"], trend, 0.0), p["mode"]), d)


def trailing_mean(x: np.ndarray, n: int) -> np.ndarray:
    """Mean of the finite values among x[t-n+1 .. t] (causal)."""
    v = np.where(np.isfinite(x), x, 0.0); k = np.isfinite(x).astype(float)
    cv, ck = np.cumsum(v), np.cumsum(k)
    sv = cv - np.concatenate([np.zeros(n), cv[:-n]]); sk = ck - np.concatenate([np.zeros(n), ck[:-n]])
    return np.where(sk > n // 4, sv / np.maximum(sk, 1), np.nan)


def vol_scale(d: Data) -> np.ndarray:
    vol = d.f["h1_cc_vol_168"]
    return np.clip(np.nan_to_num(trailing_mean(vol, 2160) / vol, nan=1.0), 0.25, 2.0)


def f_trend_ens(d, p, _):
    """Average of the trend signs over several fixed look-backs (no look-back is chosen), optionally vol-scaled."""
    sig = np.mean([np.sign(np.nan_to_num(d.c / past_close(d, L) - 1.0)) for L in (72, 168, 336, 720)], axis=0)
    if p["mode"] == "long":
        sig = np.clip(sig, 0.0, None)
    if p["calm"]:
        sig = np.where(np.nan_to_num(d.f["h1_vol_ratio"], nan=1.0) < 1.0, sig, 0.0)
    pos = sig * (vol_scale(d) if p["vs"] else 1.0)
    return daily(pos, d)


def f_funding_abs(d, p, _):
    """Buy when the settled funding rate itself is negative enough (shorts pay longs), hold H hours."""
    fr = np.nan_to_num(d.f["fund_rate"], nan=0.0)
    ev = np.where(fr <= p["thr"], 1.0, 0.0)
    if p["trend"]:
        ev = ev * (np.nan_to_num(d.f["h4_ema_dist_200"]) > 0)
    return hold(ev, p["H"])


def f_funding_oi(d, p, _):
    """Crowded shorts: funding z very low while open interest is high versus its own history -> long for H hours."""
    z = np.nan_to_num(d.f["fund_z"]); oz = np.nan_to_num(d.f["oi_z"])
    ev = np.where((z <= -p["z"]) & (oz >= p["oz"]), 1.0, 0.0)
    return hold(ev, p["H"])


FAMILIES = [
    Family("tsmom", g(L=[24, 72, 168, 336, 720], mode=["ls", "long"]), f_tsmom, "sign of the past-L-hours return, daily rebalance"),
    Family("ema_trend", g(feat=["h1_ema_dist_200", "h4_ema_dist_50", "h4_ema_dist_200"], mode=["ls", "long"]), f_ema, "price vs EMA, daily rebalance"),
    Family("donchian", g(N=[24, 72, 168, 336], mode=["ls", "long"]), f_donchian, "channel breakout, exit at the half-length opposite channel"),
    Family("funding_contra", g(z=[1.5, 2.0, 2.5, 3.0], H=[8, 24, 72], mode=["ls", "long", "short"]), f_funding, "fade extreme funding z-scores"),
    Family("liq_reversal", g(k=[2.0, 3.0, 4.0], oi=[0.0, 0.005, 0.01], H=[4, 12, 24], mode=["ls", "long"]), f_liq, "fade a big 1h move that came with falling OI"),
    Family("rsi_pullback", g(r=[25, 30, 35], H=[6, 12, 24], mode=["ls", "long"]), f_rsi_pull, "buy oversold 1h RSI in a 4h uptrend (mirror short)"),
    Family("bb_revert", g(z=[2.0, 2.5, 3.0], H=[4, 12, 24], mode=["ls", "long"]), f_bb_revert, "fade Bollinger z extremes"),
    Family("season_hour", g(by=["hour"], tau=[1.0, 1.5, 2.0, 2.5], mode=["ls", "long"]), f_season, "hours of day with a significant mean (learned on train)"),
    Family("season_dow", g(by=["dow"], tau=[1.0, 1.5, 2.0], mode=["ls", "long"]), f_season, "weekdays with a significant mean (learned on train)"),
    Family("taker_flow", g(hi=[0.58, 0.62, 0.66], H=[2, 6, 12], dir=["follow", "fade"], mode=["ls", "long"]), f_taker, "taker buy ratio extremes"),
    Family("oi_divergence", g(a=[0.01, 0.02], oi=[0.005, 0.01, 0.02], H=[6, 24], mode=["ls", "long"]), f_oi_div, "price/OI divergence fade"),
    Family("squeeze_break", g(vr=[0.6, 0.8], H=[6, 24, 72], mode=["ls", "long"]), f_squeeze_break, "24h breakout while vol is compressed"),
    Family("trend_lowvol", g(vr=[0.8, 1.0, 1.2], mode=["ls", "long"]), f_trend_vol, "4h EMA200 trend only in calm vol, daily"),
]
FAMILIES += [  # round 2 (2026-10-11), added after round 1 was seen - counted in the multiple-testing threshold
    Family("trend_ens", g(mode=["ls", "long"], vs=[False, True], calm=[False, True]), f_trend_ens, "mean trend sign over 72/168/336/720 h, daily"),
    Family("funding_abs", g(thr=[0.0, -0.00005, -0.0001], H=[8, 24, 72], trend=[False, True]), f_funding_abs, "long while funding is negative"),
    Family("funding_oi", g(z=[1.0, 1.5, 2.0], oz=[0.0, 1.0], H=[8, 24, 72]), f_funding_oi, "long when shorts are crowded (low funding z, high OI z)"),
]
COMBOS = {  # fixed equal weights, defined before the combined result was seen
    "combo_funding_trendlowvol": ("funding_contra", "trend_lowvol"),
    "combo_funding_donchian": ("funding_contra", "donchian"),
    "combo_funding_trendlowvol_donchian": ("funding_contra", "trend_lowvol", "donchian"),
}
LEARNING = {"season_hour", "season_dow"}


# ----------------------------------------------------------------------------------------------- walk-forward


def months(ms: int, k: int) -> int:
    import datetime as dt
    t = dt.datetime.fromtimestamp(ms / 1000, tz=dt.UTC)
    y, m = divmod(t.month - 1 + k, 12)
    return int(dt.datetime(t.year + y, m + 1, 1, tzinfo=dt.UTC).timestamp() * 1000)


def folds(d: Data) -> list[tuple[np.ndarray, np.ndarray, int]]:
    out = []
    start = 1_593_561_600_000  # 2020-07-01 (features ready from 2020-06-15)
    end = int(d.t[-1]) + H
    while True:
        tr0, te0 = start, months(start, 12)
        te1 = months(te0, 3)
        if te1 > end:
            break
        out.append(((d.t > tr0) & (d.t <= te0), (d.t > te0) & (d.t <= te1), te0))
        start = months(start, 3)
    return out


def walk_forward(d: Data, fam: Family, fl, min_trades: int = 8) -> dict[str, Any]:
    learns = fam.name in LEARNING
    oos_pos = np.zeros(len(d))
    chosen = []
    for train, test, te0 in fl:
        best, best_s = None, -np.inf
        for p in fam.grid:
            pos = fam.pos(d, p, train, learns)
            s = stats(pnl(pos, d, "cfd")[train], pos[train])
            if s["trades"] >= min_trades and s["sharpe"] > best_s:
                best, best_s = p, s["sharpe"]
        if best is not None:
            pos = fam.pos(d, best, train, learns)
            oos_pos[test] = pos[test]
        chosen.append({"test_start_ms": te0, "params": best, "train_sharpe": best_s})
    mask = np.zeros(len(d), dtype=bool)
    for _, test, _ in fl:
        mask |= test
    res: dict[str, Any] = {"family": fam.name, "notes": fam.notes, "grid_size": len(fam.grid), "chosen": chosen}
    for cost in COST:
        r = pnl(oos_pos, d, cost)[mask]
        res[cost] = stats(r, oos_pos[mask])
        res[cost]["quarters_positive"] = int(sum(pnl(oos_pos, d, cost)[test].sum() > 0 for _, test, _ in fl))
        res[cost]["tstat"] = float(r.mean() / r.std() * math.sqrt(len(r))) if r.std() > 0 else 0.0
    res["quarters"] = len(fl)
    res["oos_pos"] = oos_pos
    return res


def main() -> None:
    t0 = time.time()
    d = load()
    print(f"loaded {len(d)} hours in {time.time() - t0:.0f}s ({d.t[0]} -> {d.t[-1]})")
    fl = folds(d)
    mask = np.zeros(len(d), dtype=bool)
    for _, test, _ in fl:
        mask |= test
    bh = d.ret[mask]
    print(f"{len(fl)} folds; buy-and-hold over the test quarters: sum {bh.sum():+.2f}, Sharpe {bh.mean() / bh.std() * math.sqrt(HOURS_PER_YEAR):.2f}")
    k = len(FAMILIES) + len(COMBOS)
    from statistics import NormalDist
    thr = NormalDist().inv_cdf(1 - 0.05 / k)  # Bonferroni, one-sided 5 %
    print(f"{k} families -> Bonferroni t threshold {thr:.2f}\n")
    rows = []
    for fam in FAMILIES:
        t1 = time.time()
        r = walk_forward(d, fam, fl)
        passed = (r["cfd"]["ret"] > 0 and r["cfd_x4"]["ret"] > 0 and r["perp"]["ret"] > 0 and r["cfd"]["tstat"] > thr
                  and r["cfd"]["quarters_positive"] >= math.ceil(0.6 * len(fl)))
        r["passed"] = passed
        rows.append(r)
        c, s, pp = r["cfd"], r["cfd_x4"], r["perp"]
        print(f"{fam.name:15s} CFD ret {c['ret']:+.2f} SR {c['sharpe']:+.2f} t {c['tstat']:+.2f} DD {c['maxdd']:.2f} trades {c['trades']:4d} "
              f"exp {c['exposure']:.0%} q+ {c['quarters_positive']}/{len(fl)} | x4 {s['ret']:+.2f} | perp {pp['ret']:+.2f} SR {pp['sharpe']:+.2f}"
              f" {'PASS' if passed else ''} ({time.time() - t1:.0f}s)")
    by = {r["family"]: r for r in rows}
    for name, parts in COMBOS.items():
        pos = np.mean([by[x]["oos_pos"] for x in parts], axis=0)
        r = {"family": name, "notes": "equal-weight average of " + ", ".join(parts), "quarters": len(fl), "oos_pos": pos}
        for cost in COST:
            rr = pnl(pos, d, cost)[mask]
            r[cost] = stats(rr, pos[mask])
            r[cost]["quarters_positive"] = int(sum(pnl(pos, d, cost)[test].sum() > 0 for _, test, _ in fl))
            r[cost]["tstat"] = float(rr.mean() / rr.std() * math.sqrt(len(rr))) if rr.std() > 0 else 0.0
        r["passed"] = (r["cfd"]["ret"] > 0 and r["cfd_x4"]["ret"] > 0 and r["perp"]["ret"] > 0 and r["cfd"]["tstat"] > thr
                       and r["cfd"]["quarters_positive"] >= math.ceil(0.6 * len(fl)))
        rows.append(r)
        c, s2, pp = r["cfd"], r["cfd_x4"], r["perp"]
        print(f"{name:34s} CFD ret {c['ret']:+.2f} SR {c['sharpe']:+.2f} t {c['tstat']:+.2f} DD {c['maxdd']:.2f} q+ {c['quarters_positive']}/{len(fl)}"
              f" | x4 {s2['ret']:+.2f} | perp {pp['ret']:+.2f} SR {pp['sharpe']:+.2f} {'PASS' if r['passed'] else ''}")
    out = Path("data/research"); out.mkdir(parents=True, exist_ok=True)
    (out / "edge_lab.json").write_text(json.dumps([{k2: v for k2, v in r.items() if k2 != "oos_pos"} for r in rows], indent=1, default=str))
    np.savez_compressed(out / "edge_lab_oos.npz", t=d.t, mask=mask, **{r["family"]: r["oos_pos"] for r in rows})
    print(f"\ndone in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())

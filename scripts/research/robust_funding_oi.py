"""Robustness checks of the round-2 "funding_oi" edge (research-only), all on development + validation, never the test.

1. Parameter surface: full-period CFD result for every grid point and a wider neighbourhood (is it a plateau or a spike?).
2. Entry delay: the same signals entered 1, 2 and 4 hours later.
3. Random-entry control: the same number of entries and the same holding time at random hours (2000 draws) -> where does the
   real result sit (beta of being long BTC 10 % of the time vs a real timing edge)?
4. Per-year breakdown and long-only beta check (result on hours when BTC fell vs rose).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import edge_lab as el  # noqa: E402


def run(d, z, oz, H, delay=0):
    pos = el.f_funding_oi(d, {"z": z, "oz": oz, "H": H}, None)
    if delay:
        pos = np.concatenate([np.zeros(delay), pos[:-delay]])
    return pos


def main() -> None:
    d = el.load()
    fl = el.folds(d)
    mask = np.zeros(len(d), dtype=bool)
    for _, test, _ in fl:
        mask |= test
    ready = d.t >= 1_598_918_400_000  # OI features exist from 2020-09-01
    print("== 1. parameter surface (whole 2020-09 -> 2024-12, CFD, 1x): total return / Sharpe / entries")
    for oz in (-1.0, 0.0, 0.5, 1.0, 1.5):
        row = []
        for z in (0.75, 1.0, 1.25, 1.5, 2.0, 2.5):
            for H in (24,):
                pos = run(d, z, oz, H)
                s = el.stats(el.pnl(pos, d, "cfd")[ready], pos[ready])
                row.append(f"z{z}:{s['ret']:+.2f}/{s['sharpe']:+.1f}/{s['trades']}")
        print(f"  oz {oz:+.1f}  " + "  ".join(row))
    print("  holding time (z=1.5, oz=1.0):", "  ".join(
        f"H{H}:{el.stats(el.pnl(run(d, 1.5, 1.0, H), d, 'cfd')[ready], run(d, 1.5, 1.0, H)[ready])['sharpe']:+.2f}" for H in (4, 8, 12, 24, 48, 72, 120)))

    print("\n== 2. entry delay (walk-forward params are not re-chosen; fixed z=1.5, oz=1.0, H=24, whole period, CFD)")
    for delay in (0, 1, 2, 4, 8):
        pos = run(d, 1.5, 1.0, 24, delay)
        s = el.stats(el.pnl(pos, d, "cfd")[ready], pos[ready])
        print(f"  delay {delay}h: ret {s['ret']:+.2f} SR {s['sharpe']:+.2f}")

    print("\n== 3. random-entry control for the walk-forward OOS positions")
    oos = np.load("data/research/edge_lab_oos.npz")["funding_oi"]
    real = el.pnl(oos, d, "cfd")[mask].sum()
    starts = np.flatnonzero((oos != 0) & (np.concatenate([[0.0], oos[:-1]]) == 0))
    lens = []
    for s0 in starts:
        k = s0
        while k < len(oos) and oos[k] != 0:
            k += 1
        lens.append(k - s0)
    cand = np.flatnonzero(mask)
    rng = np.random.default_rng(7)
    sims = []
    for _ in range(2000):
        pos = np.zeros(len(d))
        for L in lens:
            s0 = int(rng.choice(cand))
            pos[s0:s0 + L] = 1.0
        sims.append(el.pnl(pos, d, "cfd")[mask].sum())
    sims = np.array(sims)
    print(f"  real OOS {real:+.3f}; random mean {sims.mean():+.3f}, 95th pct {np.percentile(sims, 95):+.3f}, 99th {np.percentile(sims, 99):+.3f}; "
          f"p-value {np.mean(sims >= real):.4f} ({len(lens)} entries, mean hold {np.mean(lens):.0f} h)")

    print("\n== 4. OOS by calendar year (CFD) and vs buy-and-hold")
    r = el.pnl(oos, d, "cfd")
    years = ((d.t // el.DAY + 719468) // 365.2425).astype(int)  # rough civil year index
    import datetime as dt
    yr = np.array([dt.datetime.fromtimestamp(x / 1000, tz=dt.UTC).year for x in d.t])
    for y in sorted(set(yr[mask])):
        m = mask & (yr == y)
        print(f"  {y}: S7-free funding_oi {r[m].sum():+.3f} on {int(((oos != 0) & m & (np.concatenate([[0.0], oos[:-1]]) == 0)).sum())} entries | buy-and-hold {d.ret[m].sum():+.3f}")
    del years


if __name__ == "__main__":
    main()

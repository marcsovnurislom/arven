"""When do S4/S5/S6 signals win or lose? Data-mining-aware pattern study (docs/signal_patterns.md).

Development signals only are mined. Every (feature, tercile) bucket is a hypothesis, so significance is judged against a
permutation distribution of the *maximum* |t| over the whole family (family-wise p-value), not a per-bucket p-value.
Validation is read only by ``--validate`` and only for the rules fixed in docs/signal_patterns.md.

    PYTHONPATH=src python scripts/signal_pattern_study.py data/tmp            # mine development
    PYTHONPATH=src python scripts/signal_pattern_study.py data/tmp --validate  # apply the fixed rules once to validation
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ml_signal_filter_study import STRATEGIES, outcomes_with_exit  # noqa: E402

from arven.core.config import CostsConfig, load_config  # noqa: E402
from arven.core.features_config import load_features_config  # noqa: E402
from arven.core.splitguard import BacktestPeriod  # noqa: E402
from arven.ml.splits import HOUR_MS  # noqa: E402
from arven.ml.train import logistic_required_columns  # noqa: E402
from arven.runs import load_inputs, make_guard  # noqa: E402

SEED = 20261010
N_PERM = 2000
# features whose sign means "direction": multiplied by the trade side so that + = in the trade's direction
DIRECTIONAL = (
    "h1_ret_1", "h1_ret_4", "h1_ret_24", "h1_ret_72", "h1_ret_168", "h1_ema_dist_20", "h1_ema_dist_50", "h1_ema_dist_200",
    "h1_ema_slope", "h1_macd_hist", "h1_bb_z", "h4_ret_1", "h4_ret_6", "h4_ret_30", "h4_ema_dist_20", "h4_ema_dist_50",
    "h4_ema_dist_200", "h4_ema_slope", "m15_ret_1", "m15_ret_4", "fund_rate", "fund_z",
)
CENTERED = {"h1_rsi": 50.0, "h4_rsi": 50.0, "m15_rsi": 50.0, "h1_taker_buy_ratio": 0.5, "h4_taker_buy_ratio": 0.5, "h1_donchian_pos_24": 0.5, "h1_donchian_pos_168": 0.5}


def load_period(period: str, tmp: Path):
    app, fcfg = load_config(), load_features_config()
    costs = CostsConfig.model_validate(yaml.safe_load(Path("config/costs_cfd_justmarkets.yaml").read_text(encoding="utf-8")))
    window = make_guard(app).resolve(BacktestPeriod(period))
    loaded = load_inputs(app, fcfg, window)
    required = set(logistic_required_columns(fcfg))
    col_idx = {n: i for i, n in enumerate(loaded.features.names) if n in required}
    rows: list[dict] = []
    for strat in STRATEGIES:
        payload = json.loads((tmp / f"{strat}_signals_{period}.json").read_text())
        rows += [{**r, "strategy": strat} for r in outcomes_with_exit(payload["signals"], loaded.market, costs)]
    rows.sort(key=lambda r: r["event_time_ms"])
    t_hour = np.array([r["event_time_ms"] // HOUR_MS * HOUR_MS for r in rows])
    idx = np.clip(np.searchsorted(loaded.features.t_ms, t_hour, side="right") - 1, 0, len(loaded.features.t_ms) - 1)
    side = np.array([r["side"] for r in rows], dtype=float)
    feats: dict[str, np.ndarray] = {}
    for name, ci in col_idx.items():
        v = loaded.features.values[idx, ci].astype(float)
        if name in DIRECTIONAL:
            feats["aligned_" + name] = v * side
        elif name in CENTERED:
            feats["aligned_" + name] = (v - CENTERED[name]) * side
        else:
            feats[name] = v
    ts = np.array([r["event_time_ms"] for r in rows])
    hour = (ts // HOUR_MS) % 24
    feats["session_asia_0_8"] = (hour < 8).astype(float)
    feats["session_eu_8_16"] = ((hour >= 8) & (hour < 16)).astype(float)
    feats["session_us_16_24"] = (hour >= 16).astype(float)
    feats["weekend"] = (((ts // 86_400_000) + 4) % 7 >= 5).astype(float)  # 1970-01-01 was a Thursday
    feats["stop_pct"] = np.array([abs(r["entry_reference"] - r["stop"]) / r["entry_reference"] for r in rows])
    feats["tp1_r"] = np.array([r["ladder"][0][0] for r in rows])
    feats["side_long"] = (side > 0).astype(float)
    for s in STRATEGIES:
        feats["strategy_" + s] = np.array([float(r["strategy"] == s) for r in rows])
    return rows, feats, np.array([r["net_r"] for r in rows]), ts


def buckets(feats: dict[str, np.ndarray], edges: dict[str, tuple[float, float]] | None = None):
    """(name, mask) for every binary feature and every tercile of every continuous feature."""
    out, new_edges = [], {}
    for name, v in feats.items():
        finite = v[np.isfinite(v)]
        if len(finite) < 30:
            continue
        if set(np.unique(finite)) <= {0.0, 1.0}:
            out += [(f"{name}=1", v == 1.0)]
            continue
        lo, hi = edges[name] if edges else tuple(np.quantile(finite, [1 / 3, 2 / 3]))
        new_edges[name] = (lo, hi)
        out += [(f"{name} low(<= {lo:.4g})", v <= lo), (f"{name} high(>= {hi:.4g})", v >= hi)]
    return out, new_edges


def tstat(r: np.ndarray, m: np.ndarray) -> tuple[float, int]:
    a, b = r[m], r[~m]
    if len(a) < 20 or len(b) < 20:
        return 0.0, int(m.sum())
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float((a.mean() - b.mean()) / se) if se > 0 else 0.0, int(m.sum())


def mine(tmp: Path) -> None:
    rows, feats, r, ts = load_period("development", tmp)
    print(f"development signals: {len(r)}  mean net R {r.mean():+.4f}  win {np.mean(r > 0):.1%}")
    for s in STRATEGIES:
        m = np.array([x["strategy"] == s for x in rows])
        print(f"  {s}: n={m.sum()} meanR={r[m].mean():+.4f} win={np.mean(r[m] > 0):.1%}")
    bks, edges = buckets(feats)
    obs = [(name, *tstat(r, m), r[m].mean() if m.sum() else np.nan, m) for name, m in bks]
    rng = np.random.default_rng(SEED)
    max_null = np.empty(N_PERM)
    for k in range(N_PERM):
        rp = rng.permutation(r)
        max_null[k] = max(abs(tstat(rp, m)[0]) for _, m in bks)
    print(f"family size {len(bks)} buckets; permutation 95th percentile of max|t| = {np.percentile(max_null, 95):.2f}")
    obs.sort(key=lambda x: -abs(x[1]))
    half = ts < np.median(ts)
    print("top buckets by |t| (t = bucket mean R minus rest, family-wise p from max|t| permutation):")
    for name, t, n, mean, m in obs[:20]:
        p = float(np.mean(max_null >= abs(t)))
        first, second = (r[m & half].mean() if (m & half).sum() > 5 else np.nan), (r[m & ~half].mean() if (m & ~half).sum() > 5 else np.nan)
        print(f"  {name:55s} n={n:3d} meanR={mean:+.3f} t={t:+.2f} FWER-p={p:.3f}  1st-half={first:+.3f} 2nd-half={second:+.3f}")
    Path("data/tmp/pattern_edges.json").write_text(json.dumps(edges))


def validate(tmp: Path) -> None:
    """Apply the two rules fixed in docs/signal_patterns.md, once, to the validation signals."""
    rows, feats, r, _ = load_period("validation", tmp)
    print(f"validation signals: {len(r)}  mean net R {r.mean():+.4f}  win {np.mean(r > 0):.1%}")
    rules = {
        "R1 no weak trend, no weekend": ~((feats["weekend"] == 1.0) | (feats["h4_adx"] <= 21.12)),
        "R2 calm market only": feats["h1_cc_vol_168"] <= 0.005419,
    }
    rng = np.random.default_rng(SEED)
    for name, keep in rules.items():
        keep = np.asarray(keep, dtype=bool)
        kept = r[keep]
        draws = np.array([r[rng.choice(len(r), size=len(kept), replace=False)].mean() for _ in range(2000)])
        p95 = float(np.percentile(draws, 95))
        ok = len(kept) >= 60 and kept.mean() > r.mean() and kept.mean() > p95
        print(f"{name}: kept {len(kept)}/{len(r)} meanR={kept.mean():+.4f} totalR={kept.sum():+.2f} win={np.mean(kept > 0):.1%} | all meanR={r.mean():+.4f} | random 95th pct={p95:+.4f} -> {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else Path("data/tmp")
    validate(folder) if "--validate" in sys.argv else mine(folder)

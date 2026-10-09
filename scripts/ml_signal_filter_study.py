"""ML signal-filter study, exactly as pre-registered in docs/ml_signal_filter.md.

Usage (signals recorded beforehand by scripts/s4_variant_study.py record):
    PYTHONPATH=src python scripts/ml_signal_filter_study.py data/tmp
Research-only; nothing in ``src/`` imports this. The sealed test period is never requested.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s4_variant_study import build_signal  # noqa: E402

from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate  # noqa: E402
from arven.backtest.paper_tracker import track_signal  # noqa: E402
from arven.core.config import CostsConfig, load_config  # noqa: E402
from arven.core.features_config import load_features_config  # noqa: E402
from arven.core.splitguard import BacktestPeriod  # noqa: E402
from arven.ml.metrics import log_loss, roc_auc  # noqa: E402
from arven.ml.model import fit_logistic_regression  # noqa: E402
from arven.ml.splits import HOUR_MS, generate_folds, purge_and_embargo_train_mask, validation_mask  # noqa: E402
from arven.ml.train import logistic_required_columns  # noqa: E402
from arven.runs import load_inputs, make_guard  # noqa: E402

STRATEGIES = ("s4", "s5", "s6")
L2_GRID = (10.0, 100.0, 1000.0)
SEED = 20261009


def outcomes_with_exit(signals: list[dict], market, costs: CostsConfig) -> list[dict]:
    """Independent V0 outcome (net R, exit time) of every signal; unresolved ones are dropped."""
    fee_rate = taker_fee_rate(costs)
    out: list[dict] = []
    for rec in signals:
        t = rec["event_time_ms"]
        i = market.first_at_or_after(t)
        if i >= len(market) or int(market.time_ms[i]) != t:
            continue
        side = rec["side"]
        o, h, lo = float(market.open[i]), float(market.high[i]), float(market.low[i])
        fill = adverse_price(o, side, slippage_fraction(o, h, lo, costs, False))
        sig, be = build_signal(rec, "V0")
        result = track_signal(sig, t, fill, market, costs, stress=False, breakeven_at_r=be)
        if result.resolution is None:
            continue
        risk = abs(fill - rec["stop"])
        out.append({**rec, "net_r": result.resolution.r_multiple - fill * fee_rate / risk, "exit_ms": result.updates[-1].time_ms})
    return out


def build_matrix(rows: list[dict], feats, cols: list[int]) -> np.ndarray:
    """Feature matrix: strategy one-hot, side, stop distance, TP1 R, then the Stage 3 columns at the last hourly row <= t."""
    t_hour = np.array([r["event_time_ms"] // HOUR_MS * HOUR_MS for r in rows])
    idx = np.clip(np.searchsorted(feats.t_ms, t_hour, side="right") - 1, 0, len(feats.t_ms) - 1)
    extra = np.array([
        [float(r["strategy"] == s) for s in STRATEGIES] + [float(r["side"]), abs(r["entry_reference"] - r["stop"]) / r["entry_reference"], r["ladder"][0][0]]
        for r in rows
    ])
    return np.hstack([extra, feats.values[idx][:, cols]])


def prepare(train: np.ndarray, other: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Median-impute and standardise with TRAIN statistics only."""
    med = np.nanmedian(train, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    a, b = np.where(np.isfinite(train), train, med), np.where(np.isfinite(other), other, med)
    mu, sd = a.mean(axis=0), a.std(axis=0)
    sd = np.where(sd > 1e-12, sd, 1.0)
    return (a - mu) / sd, (b - mu) / sd


def main(tmp: Path) -> None:
    app, fcfg = load_config(), load_features_config()
    costs = CostsConfig.model_validate(yaml.safe_load(Path("config/costs_cfd_justmarkets.yaml").read_text(encoding="utf-8")))
    guard = make_guard(app)
    required = set(logistic_required_columns(fcfg))
    data: dict[str, dict] = {}
    for period in ("development", "validation"):
        window = guard.resolve(BacktestPeriod(period))
        loaded = load_inputs(app, fcfg, window)
        cols = [i for i, n in enumerate(loaded.features.names) if n in required]
        rows: list[dict] = []
        for strat in STRATEGIES:
            payload = json.loads((tmp / f"{strat}_signals_{period}.json").read_text())
            for r in outcomes_with_exit(payload["signals"], loaded.market, costs):
                rows.append({**r, "strategy": strat})
        rows.sort(key=lambda r: r["event_time_ms"])
        x = build_matrix(rows, loaded.features, cols)
        data[period] = {
            "rows": rows, "x": x, "t": np.array([r["event_time_ms"] for r in rows]), "exit": np.array([r["exit_ms"] for r in rows]),
            "r": np.array([r["net_r"] for r in rows]), "y": np.array([float(r["net_r"] > 0) for r in rows]), "window": window,
        }
        print(f"{period}: {len(rows)} signals, base win rate {data[period]['y'].mean():.3f}, mean net R {data[period]['r'].mean():+.4f}")

    dev, val = data["development"], data["validation"]
    names = tuple(f"f{i}" for i in range(dev["x"].shape[1]))
    folds = generate_folds(dev["window"].start_ms, dev["window"].end_ms, 12, 3)

    # --- development walk-forward: choose l2 by mean out-of-fold log-loss, then report the out-of-fold filter ---
    fold_preds: dict[float, np.ndarray] = {l2: np.full(len(dev["y"]), np.nan) for l2 in L2_GRID}
    fold_thr = np.full(len(dev["y"]), np.nan)
    ll: dict[float, list[float]] = {l2: [] for l2 in L2_GRID}
    for fold in folds:
        vm = validation_mask(dev["t"], fold)
        tm = purge_and_embargo_train_mask(dev["t"], dev["exit"], fold, 96)
        if vm.sum() < 5 or tm.sum() < 50 or len(np.unique(dev["y"][tm])) < 2:
            continue
        xt, xv = prepare(dev["x"][tm], dev["x"][vm])
        fold_thr[vm] = dev["y"][tm].mean()
        for l2 in L2_GRID:
            p = fit_logistic_regression(xt, dev["y"][tm], names, l2).predict_proba(xv)
            fold_preds[l2][vm] = p
            ll[l2].append(log_loss(dev["y"][vm], p))
    mean_ll = {l2: float(np.mean(v)) for l2, v in ll.items() if v}
    best_l2 = min(mean_ll, key=mean_ll.get)
    print("walk-forward mean log-loss by l2:", {k: round(v, 4) for k, v in mean_ll.items()}, "-> chosen", best_l2)
    oof = ~np.isnan(fold_preds[best_l2])
    p_oof, y_oof, r_oof = fold_preds[best_l2][oof], dev["y"][oof], dev["r"][oof]
    print(f"development out-of-fold: n={oof.sum()}  ROC-AUC={roc_auc(y_oof, p_oof)}  log-loss={log_loss(y_oof, p_oof):.4f} (base-rate log-loss {log_loss(y_oof, np.full(len(y_oof), y_oof.mean())):.4f})")
    keep = p_oof >= fold_thr[oof]
    report("development OOF", r_oof, keep)

    # --- validation, once: frozen model trained on ALL development signals ---
    xt, xv = prepare(dev["x"], val["x"])
    model = fit_logistic_regression(xt, dev["y"], names, best_l2)
    p_val = model.predict_proba(xv)
    thr = dev["y"].mean()
    keep_val = p_val >= thr
    print(f"validation: ROC-AUC={roc_auc(val['y'], p_val)}  threshold(base rate)={thr:.3f}")
    verdict = report("validation", val["r"], keep_val, control=True)
    by = {s: (int(np.sum([r['strategy'] == s for r in val['rows']])), int(np.sum([(r['strategy'] == s) and k for r, k in zip(val['rows'], keep_val)]))) for s in STRATEGIES}
    print("validation signals (total, kept) by strategy:", by)
    print("VERDICT:", "USEFUL" if verdict else "NO VALUE")


def report(label: str, r: np.ndarray, keep: np.ndarray, control: bool = False) -> bool:
    kept = r[keep]
    print(f"[{label}] all: n={len(r)} meanR={r.mean():+.4f} totalR={r.sum():+.2f} | kept: n={len(kept)} meanR={(kept.mean() if len(kept) else float('nan')):+.4f} totalR={kept.sum():+.2f} win={(np.mean(kept > 0) if len(kept) else float('nan')):.1%}")
    if not control:
        return False
    rng = np.random.default_rng(SEED)
    draws = np.array([r[rng.choice(len(r), size=len(kept), replace=False)].mean() for _ in range(2000)])
    p95 = float(np.percentile(draws, 95))
    print(f"[{label}] random-rejection control (same keep count): mean {draws.mean():+.4f}, 95th pct {p95:+.4f}; criteria: kept>all {kept.mean() > r.mean()}, kept>p95 {kept.mean() > p95}, n>=60 {len(kept) >= 60}")
    return bool(len(kept) >= 60 and kept.mean() > r.mean() and kept.mean() > p95)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/tmp"))

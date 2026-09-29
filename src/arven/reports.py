"""Post-hoc reporting on a completed backtest (not part of any live decision path).

Per-regime analysis: does strategy performance actually differ by regime? (the stated purpose of regime
detection in docs/architecture.md section 12). Pure: takes an already-completed ``BacktestResult`` and the
:class:`~arven.decision.pipeline.Stage5Pipeline`'s own decision history, no I/O.

Deliberately kept out of ``arven.decision`` (which must stay free of any ``arven.backtest`` dependency
beyond the ``SignalProvider`` contract it implements): this module runs only after a backtest finishes and
never feeds back into regime/strategy/decision/risk, so it is not bound by their separation rules — it is
tooling, like ``arven.backtest.metrics``/``report``, just one layer up.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from arven.backtest.engine import BacktestResult
from arven.decision.pipeline import DecisionRecord


def regime_at_entry(history: list[DecisionRecord], entry_time_ms: int) -> str | None:
    """The regime label of the decision record whose time equals ``entry_time_ms`` (a trade's signal time,
    which is always a real decision time), or ``None`` if it is not found."""
    for rec in history:
        if rec.t_ms == entry_time_ms:
            return rec.regime.label
    return None


def per_regime_breakdown(result: BacktestResult, history: list[DecisionRecord]) -> dict[str, dict[str, Any]]:
    """Trade count, net PnL, win rate and average R-multiple per regime label at each trade's entry decision,
    plus the fraction of all decision times spent in each regime (persistence / distribution over time)."""
    by_t = {rec.t_ms: rec.regime.label for rec in history}
    time_in_regime: dict[str, int] = defaultdict(int)
    for label in by_t.values():
        time_in_regime[label] += 1
    total_bars = len(by_t) or 1

    trades_by_regime: dict[str, list] = defaultdict(list)
    unattributed = 0
    for t in result.trades:
        label = by_t.get(t.signal_ms)
        if label is None:
            unattributed += 1
            continue
        trades_by_regime[label].append(t)

    out: dict[str, dict[str, Any]] = {}
    for label in sorted(set(time_in_regime) | set(trades_by_regime)):
        trades = trades_by_regime.get(label, [])
        wins = [t for t in trades if t.net_pnl > 0]
        out[label] = {
            "bars": time_in_regime.get(label, 0),
            "time_fraction": time_in_regime.get(label, 0) / total_bars,
            "n_trades": len(trades),
            "net_pnl_usdt": float(sum(t.net_pnl for t in trades)),
            "win_rate": (len(wins) / len(trades)) if trades else None,
            "avg_r_multiple": (sum(t.r_multiple for t in trades if t.r_multiple == t.r_multiple) / max(1, sum(1 for t in trades if t.r_multiple == t.r_multiple))) if trades else None,
        }
    out["_unattributed_trades"] = {"n_trades": unattributed}
    return out


def format_breakdown(breakdown: dict[str, dict[str, Any]]) -> str:
    lines = [f"{'regime':<24}{'time%':>8}{'trades':>8}{'net_pnl':>12}{'win_rate':>10}{'avg_R':>8}"]
    for label, row in breakdown.items():
        if label == "_unattributed_trades":
            continue
        wr = "n/a" if row["win_rate"] is None else f"{row['win_rate']:.2f}"
        r = "n/a" if row["avg_r_multiple"] is None else f"{row['avg_r_multiple']:.2f}"
        lines.append(f"{label:<24}{100 * row['time_fraction']:>7.1f}%{row['n_trades']:>8}{row['net_pnl_usdt']:>12.2f}{wr:>10}{r:>8}")
    unattributed = breakdown.get("_unattributed_trades", {}).get("n_trades", 0)
    if unattributed:
        lines.append(f"(unattributed trades: {unattributed})")
    return "\n".join(lines)

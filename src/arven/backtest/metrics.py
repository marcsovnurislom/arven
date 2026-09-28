"""Performance metrics from a :class:`BacktestResult` (pure functions; no ranking, scoring or selection).

Conventions (config/backtest.yaml):
- daily returns use the equity at each 00:00 UTC decision (plus the window start and the final point);
- volatility / Sharpe / Sortino annualise with ``sqrt(annualization_days)``; they are null with fewer than
  ``min_days_for_ratios`` daily returns or a zero denominator;
- CAGR is reported only for windows of at least ``annualization_days`` days;
- funding is a signed cash flow (negative = paid); slippage and fees are positive costs.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from arven.backtest.engine import BacktestResult
from arven.backtest.types import EquityKind, ExitReason, OrderStatus
from arven.core.backtest_config import BacktestConfig

DAY_MS = 86_400_000


def _clean(x: float | None) -> float | None:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return float(x)


def daily_equity(result: BacktestResult) -> tuple[np.ndarray, np.ndarray]:
    obs: dict[int, float] = {result.window_start_ms: result.initial_equity}
    for p in result.equity:
        if p.kind == EquityKind.DECISION and p.time_ms % DAY_MS == 0:
            obs[p.time_ms] = p.equity
    final = [p for p in result.equity if p.kind == EquityKind.FINAL]
    obs[result.window_end_ms] = final[-1].equity
    times = np.array(sorted(obs), dtype=np.int64)
    return times, np.array([obs[int(t)] for t in times])


def drawdown(result: BacktestResult) -> dict[str, Any]:
    t = np.array([p.time_ms for p in result.equity], dtype=np.int64)
    v = np.array([p.equity for p in result.equity])
    peak = np.maximum.accumulate(v)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, (peak - v) / peak, 0.0)
    i = int(dd.argmax())
    max_dd = float(dd[i])
    peak_i = int(np.flatnonzero(v[: i + 1] == peak[i])[0])
    after = np.flatnonzero(v[i + 1 :] >= peak[i])
    recovery = int(t[i + 1 + int(after[0])]) if len(after) else None
    end_ms = recovery if recovery is not None else result.window_end_ms
    intrabar = max_dd
    for time_ms, low in result.low_points:
        k = int(np.searchsorted(t, time_ms, side="right")) - 1
        if k >= 0 and peak[k] > 0:
            intrabar = max(intrabar, float((peak[k] - low) / peak[k]))
    return {
        "max_drawdown": max_dd,
        "max_drawdown_peak_ms": int(t[peak_i]),
        "max_drawdown_trough_ms": int(t[i]),
        "max_drawdown_recovery_ms": recovery,
        "max_drawdown_duration_days": (end_ms - int(t[peak_i])) / DAY_MS,
        "max_intrabar_drawdown": intrabar,
    }


def compute_metrics(result: BacktestResult, cfg: BacktestConfig) -> dict[str, Any]:
    e0 = result.initial_equity
    final = [p for p in result.equity if p.kind == EquityKind.FINAL][-1]
    days = (result.window_end_ms - result.window_start_ms) / DAY_MS
    trades = result.trades
    net = np.array([t.net_pnl for t in trades])
    n = len(trades)
    m: dict[str, Any] = {
        "period": result.period,
        "window_days": days,
        "initial_equity": e0,
        "final_equity": final.equity,
        "net_pnl_usdt": final.equity - e0,
        "total_return": final.equity / e0 - 1.0,
        "gross_return": float(sum(t.gross_pnl for t in trades)) / e0,
    }
    m["cagr"] = _clean((final.equity / e0) ** (cfg.annualization_days / days) - 1.0) if days >= cfg.annualization_days and final.equity > 0 else None

    _, dv = daily_equity(result)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = dv[1:] / dv[:-1] - 1.0
    r = r[np.isfinite(r)]
    ann = math.sqrt(cfg.annualization_days)
    m["n_daily_returns"] = int(len(r))
    vol = sharpe = sortino = None
    if len(r) >= cfg.min_days_for_ratios:
        sd = float(r.std(ddof=1))
        vol = sd * ann
        if sd > 0:
            sharpe = float((r - cfg.risk_free_rate / cfg.annualization_days).mean()) / sd * ann
        down = math.sqrt(float(np.mean(np.minimum(r, 0.0) ** 2)))
        if down > 0:
            sortino = float(r.mean()) / down * ann
    m["volatility"], m["sharpe"], m["sortino"] = _clean(vol), _clean(sharpe), _clean(sortino)
    m.update(drawdown(result))

    wins, losses = net[net > 0], net[net < 0]
    m["n_trades"] = n
    m["win_rate"] = float(len(wins) / n) if n else None
    m["avg_trade_usdt"] = float(net.mean()) if n else None
    m["avg_trade_return_on_equity"] = float(np.mean([t.return_on_equity for t in trades])) if n else None
    m["avg_win_usdt"] = float(wins.mean()) if len(wins) else None
    m["avg_loss_usdt"] = float(losses.mean()) if len(losses) else None
    m["profit_factor"] = float(wins.sum() / abs(losses.sum())) if len(losses) and len(wins) else None
    m["profit_factor_undefined_reason"] = None if m["profit_factor"] is not None else ("no trades" if n == 0 else "no winners or no losers")

    m["fees_total"] = float(sum(t.fees for t in trades))
    m["slippage_total"] = float(sum(t.slippage_cost for t in trades))
    m["funding_total"] = float(sum(t.funding for t in trades))
    m["funding_paid"] = float(-sum(f.cash_flow for f in result.funding if f.cash_flow < 0))
    m["funding_received"] = float(sum(f.cash_flow for f in result.funding if f.cash_flow > 0))
    m["liquidation_extra_loss"] = float(sum(t.liquidation_extra_loss for t in trades))

    decisions = [p for p in result.equity if p.kind == EquityKind.DECISION]
    mean_equity = float(np.mean([p.equity for p in decisions])) if decisions else e0
    traded = float(sum(t.notional_entry + t.notional_exit for t in trades))
    m["traded_notional_usdt"] = traded
    m["turnover"] = traded / mean_equity if mean_equity > 0 else None
    minutes_window = (result.window_end_ms - result.window_start_ms) / 60_000.0
    m["exposure_time"] = float(sum(t.minutes_held for t in trades)) / minutes_window
    lev = [p.margin * cfg.leverage / p.equity for p in decisions if p.qty != 0.0 and p.equity > 0]
    m["avg_leveraged_exposure"] = float(np.mean(lev)) if lev else None
    m["max_leveraged_exposure"] = float(max(lev)) if lev else None

    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.exit_reason.value] = reasons.get(t.exit_reason.value, 0) + 1
    m["exit_reasons"] = dict(sorted(reasons.items()))
    m["liquidations"] = reasons.get(ExitReason.LIQUIDATION.value, 0)
    final_status: dict[int, tuple[str, str]] = {}
    for e in result.orders:
        final_status[e.order_id] = (e.status.value, e.reason)
    counts: dict[str, int] = {}
    for status, reason in final_status.values():
        key = status if not reason else f"{status}:{reason}"
        counts[key] = counts.get(key, 0) + 1
    m["orders"] = dict(sorted(counts.items()))
    m["signals"] = dict(sorted(result.signal_counts.items()))
    m["n_decisions"] = result.n_decisions

    warnings: list[str] = []
    if n < cfg.min_trades_warning:
        warnings.append(f"only {n} trades (< {cfg.min_trades_warning}): trade statistics are not statistically meaningful")
    if len(r) < cfg.min_days_for_ratios:
        warnings.append(f"only {len(r)} daily returns (< {cfg.min_days_for_ratios}): volatility / Sharpe / Sortino not reported")
    if m["liquidations"]:
        warnings.append(f"{m['liquidations']} liquidation(s): the sizing that produced them is invalid for real use")
    if result.stress:
        warnings.append("stress run: slippage multiplied by costs.slippage.stress_multiplier")
    if any(s.startswith("REJECTED") for s in counts):
        warnings.append("some orders were rejected; see orders.csv")
    m["warnings"] = warnings
    return m


def summarize_distribution(values: list[float]) -> dict[str, float | None]:
    """Descriptive statistics across seeds (no ranking, no scoring)."""
    if not values:
        return {k: None for k in ("n", "mean", "std", "min", "p5", "p50", "p95", "max")}
    a = np.array(values, dtype=float)
    return {
        "n": int(len(a)),
        "mean": float(a.mean()),
        "std": float(a.std(ddof=1)) if len(a) > 1 else None,
        "min": float(a.min()),
        "p5": float(np.percentile(a, 5)),
        "p50": float(np.percentile(a, 50)),
        "p95": float(np.percentile(a, 95)),
        "max": float(a.max()),
    }


__all__ = ["OrderStatus", "compute_metrics", "daily_equity", "drawdown", "summarize_distribution"]

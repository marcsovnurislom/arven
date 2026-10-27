"""Every trade of every live S7 model on every market, for the web page "S7 trades" (2026-10-27, owner: "a full S7
analysis on the new data, every trade on the site so I can see and judge it - all S7 models").

Models: the six S7 entries of config/live.yaml (15m, SMC 15m, 30m, 1h, 4h, 1d), parameters unchanged. Periods:
development (2020-01 -> 2023-07), validation (2023-07 -> 2025-01) and forward (2026-07-01 -> now: the new data; the
sealed test 2025-01 -> 2026-07 is never requested). Same detector, SMC filter and one-trade-at-a-time simulator as the
live loop and scripts/research/all_markets.py; costs: the market's live profile (BTC: CFD; crypto: Binance taker;
gold / silver / forex: CFD spread). Each trade carries its setup (trend line, touches, fib 0 / 1, entry zone, SMC
zones), entry / stop / targets, exit reasons, net R, a $1000 account replay (1 % risk, fractional size, a trade is
skipped if its stop would lose more than 5 %) and the candles around it for the chart.

Output: <research root>/s7_study/trades_<model>_<period>.json and <research root>/s7_study/trades_index.json
(research root: data/ for BTC, data/markets/<history instrument>/ otherwise - where the web app looks).
Research only: nothing in src/ imports this.

Usage: ARVEN_DB_WAIT_SECONDS=300 PYTHONPATH=src python scripts/s7_all_trades_export.py <INSTRUMENT> [periods...]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

import arven.backtest.strategy_s7_sim as sim
from arven.backtest.account_sim import AccountRules, TradeForAccount, replay_account, summarize_account
from arven.backtest.errors import DataError
from arven.backtest.marketdata import MarketData, funding_schedule
from arven.core.config import CostsConfig, load_config
from arven.core.live_config import load_live_config
from arven.core.splitguard import BacktestPeriod
from arven.core.time import from_ms
from arven.data.reader import EXTRA_TIMEFRAMES, load_1m_bars, load_bar_map, load_feature_inputs, load_funding_window, open_readonly
from arven.engine.strategy_s7 import detect_setups
from arven.live.strategies import S7_HIGHER, S7_LOWER, S7_TFS, s7_params, smc_types
from arven.paper.runs import latest_forward_window_end_ms
from arven.runs import make_guard

BEFORE_BARS, AFTER_BARS, MAX_BARS = 40, 24, 400
PERIODS = {"development": BacktestPeriod.DEVELOPMENT, "validation": BacktestPeriod.VALIDATION, "forward": BacktestPeriod.FORWARD}
# research instrument (stored history) -> the label the web app uses; the forward period of silver / forex reads the
# live feed's symbol because their Dukascopy history does not reach 2020
OUT_AS = {"XAUUSDT": "XAUUSD", "XAGUSDT": "XAGUSD"}  # the web app reads gold / silver research from the history folder
UNITS = {"BTCUSDT": "BTC", "XAUUSD": "oz", "XAUUSDT": "oz", "XAGUSDT": "oz", "EURUSD": "EUR", "GBPUSD": "GBP"}


def trade_id(instrument: str, model: str, tf: str, arm_ms: int, side: int) -> str:
    """The key of the owner's verdict (data/s7_study/trade_labels.json, one file for every market). The main 15m model on
    BTC and gold keeps the old export's id ("15m-<arm>-L"), so verdicts given before 2026-10-27 still apply; every other
    model gets its id as prefix and every other market its symbol, so two markets never share a key."""
    base = f"{tf}-{arm_ms}-{'L' if side == 1 else 'S'}" if model == "s7_trend_break_fib" else f"{model}-{arm_ms}-{'L' if side == 1 else 'S'}"
    return base if instrument in ("BTCUSDT", "XAUUSD", "XAUUSDT") else f"{instrument}:{base}"


def models() -> dict[str, dict[str, Any]]:
    return {s.id: dict(s.params) for s in load_live_config().strategies if s.kind == "s7"}


class Data:
    """1m market + bars for one market and period (no feature cache needed)."""

    def __init__(self, instrument: str, period: str) -> None:
        self.app = load_config(instrument=None if instrument == "BTCUSDT" else instrument)
        guard = make_guard(self.app)
        pk = PERIODS[period]
        self.window = guard.resolve(pk, end_ms=latest_forward_window_end_ms(self.app)) if pk == BacktestPeriod.FORWARD else guard.resolve(pk)
        con = open_readonly(self.app.data.database_path)
        try:
            b = load_1m_bars(con, self.app.market.symbol, self.window)
            f_t, f_r = load_funding_window(con, self.app.market.symbol, self.window)
            end = from_ms(self.window.end_ms)
            self.bars = {**load_feature_inputs(con, self.app, start=self.app.data.history_start, end=end).bars,
                         **load_bar_map(con, self.app, EXTRA_TIMEFRAMES, start=self.app.data.history_start, end=end)}
        finally:
            con.close()
        self.costs = (CostsConfig.model_validate(yaml.safe_load(Path("config/costs_cfd_justmarkets.yaml").read_text(encoding="utf-8")))
                      if instrument == "BTCUSDT" else self.app.costs)
        self.note = ""
        try:
            ft, fr, iv = funding_schedule(self.costs.funding, f_t, f_r, self.window.start_ms, self.window.end_ms)
        except DataError:  # SOL, Nov 2022: funding every 2-4 h for a while (see all_markets.py)
            ok = np.asarray(f_t) % (8 * 3_600_000) == 0
            self.note = f"{int((~ok).sum())} off-grid funding settlements left out"
            ft, fr, iv = funding_schedule(self.costs.funding, np.asarray(f_t)[ok], np.asarray(f_r)[ok], self.window.start_ms, self.window.end_ms)
        self.m = MarketData(b["time_ms"], b["open"], b["high"], b["low"], b["close"], self.window.start_ms, self.window.end_ms, ft, fr, iv,
                            calendar=self.app.session_calendar())


def export(d: Data, instrument: str, model: str, cfg: dict[str, Any], period: str, out_dir: Path) -> dict[str, Any]:
    tf, p, tp = s7_params(cfg)
    need = int(cfg.get("min_smc_types", 0))
    b = d.bars[S7_TFS[tf]]
    t_ms = b.open_time_ms
    close_ms = t_ms + S7_TFS[tf].ms
    through = (int(d.m.time_ms[-1]) + 60_000) // 900_000 * 900_000
    setups = [s for s in detect_setups(b.open, b.high, b.low, b.close, p, volume=b.volume)
              if d.window.start_ms <= int(close_ms[s.arm_index]) <= through and smc_types(s) >= need]
    higher = S7_HIGHER[tf]
    ctx = sim.make_context(sim.S7Bars.from_series(b), sim.S7Bars.from_series(d.bars[S7_LOWER[tf]]), d.m, d.costs, p, tp,
                           higher=None if higher is None else sim.S7Bars.from_series(d.bars[higher]), calendar=d.app.session_calendar())
    outs = sorted((o for o in sim.run_setups(ctx, setups) if o.status == "trade"), key=lambda o: o.entry_time_ms)
    rules = AccountRules() if instrument == "BTCUSDT" else AccountRules(min_lot=1e-6, lot_step=1e-6)
    steps = replay_account([TradeForAccount(sum(lg.weight * abs(lg.entry_price - lg.stop) for lg in o.legs), o.net_r) for o in outs], rules)
    unit = UNITS.get(instrument, instrument.replace("USDT", ""))
    trades = []
    for n, (o, step) in enumerate(zip(outs, steps, strict=True), start=1):
        s = setups[o.setup_index]
        leg = o.legs[0]
        risk = abs(leg.entry_price - leg.stop)
        first = max(0, min(s.line.a_index, s.level0_index) - BEFORE_BARS)
        last = min(len(t_ms) - 1, int(np.searchsorted(t_ms, o.exit_time_ms, side="right")) + AFTER_BARS)
        first = max(first, last - MAX_BARS)
        tm = lambda i: int(t_ms[i])  # noqa: E731
        trades.append({
            "n": n, "id": trade_id(instrument, model, tf, tm(s.arm_index), s.side), "side": s.side,
            "arm_time_ms": tm(s.arm_index), "entry_time_ms": o.entry_time_ms, "exit_time_ms": o.exit_time_ms,
            "entry": leg.entry_price, "stop": leg.stop, "targets": [leg.entry_price + s.side * r * risk for r in leg.ladder_r],
            "exit_reasons": list(leg.reasons), "net_r": o.net_r,
            "size": step.size, "size_unit": unit, "risk_usd": step.risk_usd, "pnl_usd": step.pnl_usd, "equity_after": step.equity_after,
            "skipped": step.skipped,
            "line": {"points": [{"timeMs": tm(s.line.a_index), "price": s.line.a_price}, {"timeMs": tm(s.cross_index), "price": float(s.line.at(s.cross_index))}]},
            "touches": [{"timeMs": tm(i), "price": float(b.high[i] if s.side == 1 else b.low[i])} for i in s.touches],
            "level0": {"timeMs": tm(s.level0_index), "price": s.level0}, "level1": {"timeMs": tm(s.level1_index), "price": s.level1},
            "zone": {"low": s.zone_low, "high": s.zone_high},
            "smc_zones": [{"kind": z.kind, "low": z.low, "high": z.high, "timeMs": tm(z.index)} for z in s.confluence],
            "candles": [{"t": tm(i), "o": float(b.open[i]), "h": float(b.high[i]), "l": float(b.low[i]), "c": float(b.close[i]),
                         "v": float(b.volume[i]), "complete": True} for i in range(first, last + 1)],
        })
    rs = np.array([o.net_r for o in outs])
    gains, losses = (float(rs[rs > 0].sum()), float(-rs[rs < 0].sum())) if len(rs) else (0.0, 0.0)
    summary = {"trades": len(outs), "setups": len(setups), "win_rate": float(np.mean(rs > 0)) if len(rs) else 0.0,
               "total_r": float(rs.sum()), "mean_r": float(rs.mean()) if len(rs) else None,
               "profit_factor": gains / losses if losses > 0 else None, "account": summarize_account(steps, rules)}
    payload = {"period": period, "model": model, "timeframe": tf, "instrument": instrument, "window_ms": [d.window.start_ms, d.window.end_ms],
               "config": cfg, "costs": d.costs.model_dump(), "note": d.note,
               "account_rules": {"start_equity": rules.start_equity, "risk_fraction": rules.risk_fraction, "min_lot": rules.min_lot,
                                 "lot_step": rules.lot_step, "max_loss_fraction": rules.max_loss_fraction},
               "summary": summary, "trades": trades}
    (out_dir / f"trades_{model}_{period}.json").write_text(json.dumps(payload), encoding="utf-8")
    return summary


def main() -> None:
    instrument = sys.argv[1]
    periods = sys.argv[2:] or list(PERIODS)
    app = load_config(instrument=None if instrument == "BTCUSDT" else instrument)
    folder = OUT_AS.get(instrument, instrument)  # gold / silver: the live feed's forward goes next to the history's periods
    out_dir = (app.data.data_dir if instrument == "BTCUSDT" else app.data.data_dir / "markets" / folder) / "s7_study"
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "trades_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    for period in periods:
        t0 = time.time()
        try:
            d = Data(instrument, period)
        except Exception as exc:  # noqa: BLE001 - e.g. no history for this period on this market
            print(f"{instrument} {period}: skipped ({type(exc).__name__}: {exc})", flush=True)
            continue
        if len(d.m) == 0:
            print(f"{instrument} {period}: no 1m data - skipped", flush=True)
            continue
        for model, cfg in models().items():
            s = export(d, instrument, model, cfg, period, out_dir)
            index[f"{model}|{period}"] = {"model": model, "period": period, **{k: s[k] for k in ("trades", "setups", "win_rate", "total_r", "mean_r", "profit_factor")},
                                          "account_return": s["account"]["return"], "max_drawdown": s["account"]["max_drawdown"]}
            print(f"{instrument} {period} {model}: {s['trades']} trades, {s['total_r']:+.1f} R", flush=True)
        print(f"  {period} done in {time.time() - t0:.0f}s", flush=True)
        index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

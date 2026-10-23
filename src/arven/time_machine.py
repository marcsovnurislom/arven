"""The time machine (docs/FEATURES_PLAN.md, H4): a market replayed like a video, the strategy trading on screen.

A scenario is a window of one market. This module turns the strategies' exported trades
(``scripts/strategy_trades_export.py``) into one timeline of items, each with the moment ``t`` it became known:

- ``setup`` (S7): the trend line, Fibonacci 0 / 1 and the entry zone - known when the arming bar **closed**, never at
  the line's first point (the chart must not show what the strategy could not see yet);
- ``fill``: a position (or one S7 leg) opened - side, price, stop, targets;
- ``tp`` / ``stop_moved`` / ``close``: what the paper tracker recorded, at its own time;
- ``result``: the trade's net R and the $1000 account after it (``replay_account``, the Strategies page's rules,
  started fresh at the scenario's start).

Candles are revealed at their close. :func:`check_no_lookahead` asserts the ordering the player relies on; the
builder refuses windows that touch the sealed test period. Pure functions - no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from arven.backtest.account_sim import AccountRules, TradeForAccount, replay_account


def _fields(detail: str) -> dict[str, str]:
    return dict(p.split("=", 1) for p in detail.split(";") if "=" in p)


def overlaps(start_ms: int, end_ms: int, lo_ms: int, hi_ms: int) -> bool:
    return start_ms < hi_ms and lo_ms < end_ms


def trade_items(strategy: str, n: int, trade: dict[str, Any]) -> list[dict[str, Any]]:
    """One exported trade as timeline items (without the account result, see :func:`scenario_timeline`)."""
    side = int(trade["side"])
    base = {"strategy": strategy, "trade": n, "side": side}
    items: list[dict[str, Any]] = []
    if "arm_time_ms" in trade and trade.get("line"):
        items.append(base | {
            "kind": "setup", "t": int(trade["arm_time_ms"]) + int(trade["tf_ms"]),
            "line": trade["line"]["points"], "level0": trade["level0"], "level1": trade["level1"], "zone": trade["zone"],
            "smc_zones": trade.get("smc_zones", []),
        })
    fills = [e for e in trade.get("events", []) if e["kind"] == "FILLED"]
    if not fills:  # a market entry at the signal: one fill at the entry time
        fills = [{"t": trade["entry_time_ms"], "kind": "FILLED", "detail": f"price={trade['entry']};stop={trade['stop']};weight=1"}]
    for e in fills:
        f = _fields(e["detail"])
        items.append(base | {"kind": "fill", "t": int(e["t"]), "price": float(f.get("price", trade["entry"])), "stop": float(f.get("stop", trade["stop"])),
                             "weight": float(f.get("weight", 1.0)), "leg": int(f.get("leg", 0)), "targets": trade["targets"]})
    for e in trade.get("events", []):
        f = _fields(e["detail"])
        leg = int(f.get("leg", 0))
        if e["kind"] == "TP_HIT":
            items.append(base | {"kind": "tp", "t": int(e["t"]), "leg": leg, "level": f.get("level", "TP"), "price": float(f["price"]),
                                 "fraction": float(f.get("fraction", 0.0)), "weight": float(f.get("weight", 1.0))})
        elif e["kind"] == "STOP_MOVED":
            items.append(base | {"kind": "stop_moved", "t": int(e["t"]), "leg": leg, "stop": float(f["new_stop"])})
        elif e["kind"] == "CLOSED":
            items.append(base | {"kind": "close", "t": int(e["t"]), "leg": leg, "reason": f.get("reason", ""), "fraction": float(f.get("fraction", 0.0)),
                                 "weight": float(f.get("weight", 1.0))})
    return items


def scenario_timeline(trades_by_strategy: dict[str, Sequence[dict[str, Any]]], start_ms: int, end_ms: int, rules: AccountRules,
                      max_exit_ms: int | None = None) -> dict[str, dict[str, Any]]:
    """Per strategy: its trades entered in ``[start_ms, end_ms)`` (and, with ``max_exit_ms``, closed by then - a trade
    held for months would stretch a short scenario into a long one), as items sorted by ``t``, and the $1000 account
    replayed over exactly those trades (a fresh start at the scenario's start, in entry order)."""
    out: dict[str, dict[str, Any]] = {}
    for sid, trades in trades_by_strategy.items():
        chosen = sorted((x for x in trades if start_ms <= int(x["entry_time_ms"]) < end_ms
                         and (max_exit_ms is None or int(x["exit_time_ms"]) <= max_exit_ms)), key=lambda x: int(x["entry_time_ms"]))
        if not chosen:
            continue
        steps = replay_account([TradeForAccount(float(x["risk_per_unit"]), float(x["net_r"])) for x in chosen], rules)
        items: list[dict[str, Any]] = []
        for n, (x, st) in enumerate(zip(chosen, steps, strict=True), start=1):
            items += trade_items(sid, n, x)
            items.append({"strategy": sid, "trade": n, "side": int(x["side"]), "kind": "result", "t": int(x["exit_time_ms"]),
                          "net_r": float(x["net_r"]), "pnl_usd": st.pnl_usd, "equity_after": st.equity_after, "skipped": st.skipped,
                          "reasons": list(x.get("exit_reasons", []))})
        items.sort(key=lambda i: (i["t"], _ORDER[i["kind"]]))
        out[sid] = {"trades": len(chosen), "start_equity": rules.start_equity, "final_equity": steps[-1].equity_after if steps else rules.start_equity,
                    "total_r": float(sum(float(x["net_r"]) for x in chosen)), "last_t": max(i["t"] for i in items), "items": items}
    return out


_ORDER = {"setup": 0, "fill": 1, "stop_moved": 2, "tp": 3, "close": 4, "result": 5}


def check_no_lookahead(items: Sequence[dict[str, Any]]) -> list[str]:
    """Problems with the order the player relies on (an empty list is good): a setup shown before its anchors existed,
    a fill before its setup, an exit before its fill, a result before the trade's last exit."""
    problems: list[str] = []
    by_trade: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for i in items:
        by_trade.setdefault((i["strategy"], i["trade"]), []).append(i)
    for key, its in by_trade.items():
        setup = [i for i in its if i["kind"] == "setup"]
        fills = [i["t"] for i in its if i["kind"] == "fill"]
        exits = [i["t"] for i in its if i["kind"] in ("tp", "close", "stop_moved")]
        result = [i["t"] for i in its if i["kind"] == "result"]
        for s in setup:
            anchors = [p["timeMs"] for p in s["line"]] + [s["level0"]["timeMs"], s["level1"]["timeMs"]]
            if max(anchors) >= s["t"]:
                problems.append(f"{key}: setup shown at {s['t']} but an anchor is at {max(anchors)}")
            if fills and min(fills) < s["t"]:
                problems.append(f"{key}: filled at {min(fills)} before the setup was known at {s['t']}")
        if fills and exits and min(exits) < min(fills):
            problems.append(f"{key}: an exit at {min(exits)} before the first fill at {min(fills)}")
        if result and exits and result[0] < max(exits):
            problems.append(f"{key}: result at {result[0]} before the last exit at {max(exits)}")
    return problems


__all__ = ["check_no_lookahead", "overlaps", "scenario_timeline", "trade_items"]

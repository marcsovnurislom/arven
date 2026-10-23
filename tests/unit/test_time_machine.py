"""The time machine's timeline (arven.time_machine): what is shown when, the fresh $1000 account per scenario, and the
look-ahead check that catches an item shown too early."""

from __future__ import annotations

import pytest

from arven.backtest.account_sim import AccountRules, TradeForAccount, replay_account
from arven.time_machine import check_no_lookahead, overlaps, scenario_timeline, trade_items

M = 60_000
TF = 15 * M


def s4_trade(t0: int, net_r: float = 1.1) -> dict:
    return {
        "side": 1, "entry_time_ms": t0, "exit_time_ms": t0 + 90 * M, "entry": 100.0, "stop": 98.0, "targets": [102.0, 104.0, 106.0],
        "exit_reasons": ["TP1", "STOP"], "net_r": net_r, "risk_per_unit": 2.0,
        "events": [{"t": t0 + 30 * M, "kind": "TP_HIT", "detail": "level=TP1;fraction=0.50000000;price=102.00000000"},
                   {"t": t0 + 31 * M, "kind": "STOP_MOVED", "detail": "new_stop=100.00000000"},
                   {"t": t0 + 90 * M, "kind": "CLOSED", "detail": "reason=STOP;fraction=0.50000000"}],
    }


def s7_trade(arm: int) -> dict:
    return {
        "side": -1, "entry_time_ms": arm + TF + 5 * M, "exit_time_ms": arm + TF + 60 * M, "entry": 50.0, "stop": 51.0, "targets": [49.0, 48.0],
        "exit_reasons": ["STOP"], "net_r": -1.0, "risk_per_unit": 1.0, "arm_time_ms": arm, "tf_ms": TF,
        "line": {"points": [{"timeMs": arm - 20 * TF, "price": 45.0}, {"timeMs": arm - 2 * TF, "price": 49.0}]},
        "level0": {"timeMs": arm - 5 * TF, "price": 47.0}, "level1": {"timeMs": arm, "price": 52.0}, "zone": {"low": 50.0, "high": 50.5},
        "events": [{"t": arm + TF + 5 * M, "kind": "FILLED", "detail": "leg=0;weight=1.00000000;price=50.00000000;stop=51.00000000"},
                   {"t": arm + TF + 60 * M, "kind": "CLOSED", "detail": "leg=0;weight=1.00000000;reason=STOP;fraction=1.00000000"}],
    }


def test_a_market_entry_trade_becomes_fill_tp_stop_moved_close():
    items = trade_items("s4", 1, s4_trade(1_000_000 * M))
    assert [i["kind"] for i in items] == ["fill", "tp", "stop_moved", "close"]
    fill, tp = items[0], items[1]
    assert fill["t"] == 1_000_000 * M and fill["price"] == 100.0 and fill["stop"] == 98.0 and fill["targets"] == [102.0, 104.0, 106.0]
    assert tp["level"] == "TP1" and tp["price"] == 102.0 and tp["fraction"] == 0.5 and items[2]["stop"] == 100.0


def test_an_s7_setup_is_shown_when_its_arming_bar_closed_not_at_the_line_start():
    arm = 2_000_000 * M
    items = trade_items("s7", 1, s7_trade(arm))
    setup = items[0]
    assert setup["kind"] == "setup" and setup["t"] == arm + TF and setup["line"][0]["timeMs"] == arm - 20 * TF
    assert [i["kind"] for i in items[1:]] == ["fill", "close"] and items[1]["t"] == arm + TF + 5 * M
    assert check_no_lookahead(items) == []


def test_scenario_takes_the_window_and_restarts_the_account_at_1000():
    t = 3_000_000 * M
    trades = [s4_trade(t - 500 * M, 2.0), s4_trade(t, 1.1), s4_trade(t + 200 * M, -1.0), s4_trade(t + 10_000 * M, 3.0)]
    tl = scenario_timeline({"s4": trades, "none": []}, t, t + 1_000 * M, AccountRules())
    assert list(tl) == ["s4"]
    s4 = tl["s4"]
    want = replay_account([TradeForAccount(2.0, 1.1), TradeForAccount(2.0, -1.0)], AccountRules())
    results = [i for i in s4["items"] if i["kind"] == "result"]
    assert s4["trades"] == 2 and [r["equity_after"] for r in results] == [w.equity_after for w in want]
    assert s4["final_equity"] == want[-1].equity_after and s4["total_r"] == pytest.approx(0.1)
    assert [i["t"] for i in s4["items"]] == sorted(i["t"] for i in s4["items"]) and check_no_lookahead(s4["items"]) == []


def test_the_lookahead_check_catches_items_shown_too_early():
    arm = 2_000_000 * M
    early = s7_trade(arm)
    early["level1"] = {"timeMs": arm + TF, "price": 52.0}  # an anchor the strategy could only see after the bar closed
    assert any("anchor" in p for p in check_no_lookahead(trade_items("s7", 1, early)))
    bad_exit = s4_trade(5_000_000 * M)
    bad_exit["events"][0]["t"] = 5_000_000 * M - M  # a target "hit" before the fill
    assert any("before the first fill" in p for p in check_no_lookahead(trade_items("s4", 1, bad_exit)))


def test_overlaps():
    assert overlaps(0, 10, 9, 20) and not overlaps(0, 10, 10, 20) and not overlaps(20, 30, 0, 20)


def test_no_configured_scenario_touches_the_sealed_test_period():
    from datetime import UTC, datetime
    from pathlib import Path

    import yaml

    from arven.core.config import load_config

    test = load_config().splits.test
    lo, hi = int(test.start.timestamp() * 1000), int(test.end.timestamp() * 1000)
    day = 86_400_000
    for sc in yaml.safe_load(Path("config/time_machine.yaml").read_text(encoding="utf-8"))["scenarios"]:
        a = int(datetime(sc["start"].year, sc["start"].month, sc["start"].day, tzinfo=UTC).timestamp() * 1000)
        b = int(datetime(sc["end"].year, sc["end"].month, sc["end"].day, tzinfo=UTC).timestamp() * 1000)
        assert sc["market"] in ("btc", "gold") and a < b
        assert not overlaps(a - 3 * day, b + 30 * day, lo, hi), sc["id"]  # with the context and room for the last trade's exit


def test_a_trade_held_far_beyond_the_window_is_left_out():
    t = 3_000_000 * M
    long_hold = s4_trade(t + 10 * M) | {"exit_time_ms": t + 100_000 * M}
    tl = scenario_timeline({"s6": [s4_trade(t), long_hold]}, t, t + 1_000 * M, AccountRules(), max_exit_ms=t + 2_000 * M)
    assert tl["s6"]["trades"] == 1 and tl["s6"]["last_t"] <= t + 2_000 * M
    assert scenario_timeline({"s6": [s4_trade(t), long_hold]}, t, t + 1_000 * M, AccountRules())["s6"]["trades"] == 2

"""Canonical serialisation, result hashes and reproducibility."""

import copy
import dataclasses
import math

import pytest
from bt_helpers import Scripted, app_config, features_for, window
from bt_scenarios import random_scenario

from arven.backtest.engine import Backtester
from arven.backtest.report import TABLE_ORDER, combine_hashes, fmt_value, records_csv, result_hash, result_tables, table_hashes
from arven.backtest.types import ExitReason, Side

# Golden hashes were produced by this engine on the seeded scenarios below (numpy PCG64 streams are stable). They pin
# the complete ledgers - orders, fills, funding, trades, equity - so any behavioural change is a conscious update.
GOLDEN = {
    7: "d77ed15ecbcd61500ea8867e7af7060587bb49b28d82364ec766aa47088f955c",
    12: "338e4eb405e540e3f3153c0accb96ff7b9e63d92048e9abecf361107ce2dede8",
    37: "04fd93734c32212acc31a495f820a0d5e282c4cf6bbf3cfeadc7b6eeeb627961",
}


def run_seed(seed):
    hours, market, rates, signals, cfg, stress = random_scenario(seed)
    win = window(hours)
    return Backtester(app_config(), cfg, win, market, features_for(win), stress=stress).run(Scripted(signals))


@pytest.mark.parametrize("seed", sorted(GOLDEN))
def test_golden_result_hashes(seed):
    assert result_hash(run_seed(seed)) == GOLDEN[seed]


@pytest.mark.parametrize("seed", [2, 7, 12])
def test_two_runs_give_identical_tables_and_hash(seed):
    a, b = run_seed(seed), run_seed(seed)
    ta, tb = result_tables(a), result_tables(b)
    assert ta == tb and table_hashes(ta) == table_hashes(tb)
    assert result_hash(a) == result_hash(b)


def test_hash_changes_when_any_ledger_value_changes():
    res = run_seed(7)
    base = result_hash(res)
    t0 = res.trades[0]
    changed = dataclasses.replace(res, trades=(dataclasses.replace(t0, net_pnl=t0.net_pnl + 1e-6),) + res.trades[1:])
    assert result_hash(changed) != base
    changed = dataclasses.replace(res, equity=res.equity[:-1])
    assert result_hash(changed) != base
    changed = dataclasses.replace(res, signal_counts={**res.signal_counts, "none": res.signal_counts["none"] + 1})
    assert result_hash(changed) != base
    # differences below the 10-decimal rounding do not change the hash (no last-bit sensitivity)
    tiny = dataclasses.replace(res, trades=(dataclasses.replace(t0, net_pnl=t0.net_pnl + 1e-13),) + res.trades[1:])
    assert result_hash(tiny) == base


def test_hash_is_independent_of_wall_clock_and_object_identity():
    a = run_seed(3)
    b = copy.deepcopy(a)
    assert result_hash(a) == result_hash(b)


def test_number_formatting_is_canonical():
    assert fmt_value(1.5) == "1.5000000000" and fmt_value(-0.0) == "0.0000000000" and fmt_value(math.nan) == "nan"
    assert fmt_value(0.1 + 0.2) == "0.3000000000"
    assert fmt_value(None) == "" and fmt_value(True) == "1" and fmt_value(7) == "7"
    assert fmt_value(ExitReason.STOP) == "STOP" and fmt_value(Side.SHORT) == "-1"


def test_csv_has_fixed_columns_and_quotes_awkward_text():
    from arven.backtest.types import OrderEvent, OrderStatus

    text = records_csv([OrderEvent(1, 5, OrderStatus.REJECTED, "r", "a,b;c")], OrderEvent)
    assert text.splitlines()[0] == "order_id,time_ms,status,reason,detail"
    assert text.splitlines()[1] == '1,5,REJECTED,r,"a,b;c"'


def test_combined_hash_covers_every_table_in_fixed_order():
    res = run_seed(7)
    hashes = table_hashes(result_tables(res))
    assert list(hashes) == list(TABLE_ORDER) or set(hashes) == set(TABLE_ORDER)
    swapped = dict(hashes, orders=hashes["fills"], fills=hashes["orders"])
    assert combine_hashes(swapped) != combine_hashes(hashes)

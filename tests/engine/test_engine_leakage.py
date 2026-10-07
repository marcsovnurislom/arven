"""Phase 2 gate (ARVEN_MASTER_PROMPT.md section 5.1): truncation + perturbation leakage tests for every new
per-timeframe feature and for ``MultiTFView``, through the project's generic harness (``tests/leakage_harness.py``).

- Truncation: the value at ``t`` computed from all data equals the value computed from only the data
  available at ``t`` (``MarketInputs.available_until``).
- Perturbation: replacing every record that became available after ``t`` with garbage changes nothing at ``t``.

Both are exact (NaN == NaN). The view is checked column-by-column for every role/timeframe/feature plus its
row metadata (open time, availability, ``bars_seen``, ``complete``, ``stale``) and whether it raised.
"""

from __future__ import annotations

import numpy as np
import pytest
from leakage_harness import perturbation_leaks, sample_times, truncation_leaks
from synthetic_market import START_MS, make_market

from arven.core.series import BarSeries, MarketInputs
from arven.core.timeframes import Timeframe
from arven.engine.clock import SimulatedEventClock
from arven.engine.errors import LookAheadError
from arven.engine.features import compute_tf_features, feature_names, qualified_name
from arven.engine.multitf import MultiTFView
from arven.engine.spec import StrategySpec
from arven.features.asof import asof_join

HOUR = 3_600_000
M5, M15, H1, H4 = Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4
TFS = (M5, M15, H1, H4)
FEATURE_COLUMNS = [qualified_name(tf, n) for tf in TFS for n in feature_names()]
META = ("open_ms", "available_at_ms", "bars_seen", "complete", "stale")

SPECS = {
    "m15_trigger": StrategySpec("s4like", "1", context_tfs=(H4,), setup_tf=H1, trigger_tf=M15, warmup_bars=1),
    "h1_legacy": StrategySpec("legacy", "1", context_tfs=(H4,), setup_tf=H1, trigger_tf=H1, warmup_bars=1),
    "m5_trigger": StrategySpec("fast", "1", context_tfs=(H1, H4), setup_tf=M15, trigger_tf=M5, warmup_bars=1),
}


# --- compute callables in the harness's shape: (MarketInputs, t_ms) -> {column: array} --------------


def feature_compute(inputs: MarketInputs, t_ms: np.ndarray) -> dict[str, np.ndarray]:
    """Every per-TF feature, taken at ``t`` by plain backward as-of (no staleness rule: the feature layer alone)."""
    out = {}
    for tf in TFS:
        table = compute_tf_features(inputs.bars[tf])
        for name in table.names:
            out[qualified_name(tf, name)] = asof_join(table.available_at_ms, table.column(name), t_ms)
    return out


def _roles(spec: StrategySpec) -> list[tuple[str, Timeframe]]:
    return [("trigger", spec.trigger_tf), ("setup", spec.setup_tf)] + [
        (f"context{i}", tf) for i, tf in enumerate(spec.context_tfs)
    ]


def view_columns(spec: StrategySpec) -> list[str]:
    cols = ["raised"]
    for role, tf in _roles(spec):
        cols += [f"{role}.{tf.value}.{m}" for m in META]
        cols += [f"{role}.{qualified_name(tf, n)}" for n in feature_names()]
    return cols


def view_compute(spec: StrategySpec, view_cls: type[MultiTFView] = MultiTFView):
    tfs = tuple(dict.fromkeys(tf for _, tf in _roles(spec)))

    def compute(inputs: MarketInputs, t_ms: np.ndarray) -> dict[str, np.ndarray]:
        v = view_cls.from_bars(inputs.bars, tfs)
        out = {c: np.full(len(t_ms), np.nan) for c in view_columns(spec)}
        for k, t in enumerate(t_ms):
            try:
                snap = v.at(int(t), spec)
            except LookAheadError:
                out["raised"][k] = 1.0
                continue
            out["raised"][k] = 0.0
            rows = [snap.trigger, snap.setup, *snap.context]
            for (role, tf), row in zip(_roles(spec), rows, strict=True):
                for m in META:
                    out[f"{role}.{tf.value}.{m}"][k] = float(getattr(row, m))
                for n, x in row.values.items():
                    out[f"{role}.{qualified_name(tf, n)}"][k] = x
        return out

    return compute


# --- data -------------------------------------------------------------------------------------------


def _without(s: BarSeries, drop: np.ndarray) -> BarSeries:
    keep = ~drop
    return BarSeries(
        s.timeframe, s.delay_ms, s.open_time_ms[keep], s.open[keep], s.high[keep], s.low[keep], s.close[keep],
        s.volume[keep], s.trade_count[keep], s.taker_buy_volume[keep], s.complete[keep],
    )


def gappy(inputs: MarketInputs) -> MarketInputs:
    """Missing and incomplete bars inside the data, and a 4h feed that stops two days early (stale rows)."""
    bars = dict(inputs.bars)
    h1 = bars[H1]
    drop = np.zeros(len(h1), dtype=bool)
    drop[[500, 501, 1300]] = True
    bars[H1] = _without(h1, drop)
    m15 = bars[M15]
    complete = m15.complete.copy()
    complete[[2000, 2001, 2002, 5000]] = False
    bars[M15] = BarSeries(m15.timeframe, m15.delay_ms, m15.open_time_ms, m15.open, m15.high, m15.low, m15.close,
                          m15.volume, m15.trade_count, m15.taker_buy_volume, complete)
    h4 = bars[H4]
    bars[H4] = h4.available_until(int(h4.available_at_ms[-13]))
    return MarketInputs(bars=bars, funding=inputs.funding, open_interest=inputs.open_interest)


def grid_for(inputs: MarketInputs) -> np.ndarray:
    """Every 5m close plus a mid-bar instant (+150 s) of each, so non-boundary times are covered too."""
    closes = inputs.bars[M5].close_time_ms
    first = START_MS + Timeframe.M5.ms  # starts before the first 1h/4h close: early rows must raise
    closes = closes[closes >= first]
    return np.unique(np.concatenate([closes, closes + 150_000]))


def samples_for(grid: np.ndarray) -> np.ndarray:
    four_h = grid[(grid % (4 * HOUR)) == 0]
    picks = [
        sample_times(grid, 10, seed=7, tail=2),
        sample_times(grid[: 400], 4, seed=8),  # warm-up / before the first coarse close
        sample_times(grid[len(grid) * 3 // 4 :], 6, seed=9),  # past the longest warm-up
        four_h[::31][:5],  # same-instant 4h/1h/15m/5m closes
    ]
    return np.unique(np.concatenate(picks))


@pytest.fixture(scope="module")
def market():
    return make_market(n_days=60, seed=1)


@pytest.fixture(scope="module")
def grid(market):
    return grid_for(market)


@pytest.fixture(scope="module")
def samples(grid):
    return samples_for(grid)


# --- per-TF features: every column ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def feature_truncation(market, grid, samples):
    return truncation_leaks(feature_compute, market, grid, samples)


@pytest.fixture(scope="module")
def feature_perturbation(market, grid, samples):
    return perturbation_leaks(feature_compute, market, grid, samples[::2])


@pytest.mark.parametrize("name", FEATURE_COLUMNS)
def test_feature_truncation_no_lookahead(name, feature_truncation):
    assert name not in feature_truncation, f"{name} changes when future data is removed: {feature_truncation.get(name)}"


@pytest.mark.parametrize("name", FEATURE_COLUMNS)
def test_feature_perturbation_no_lookahead(name, feature_perturbation):
    assert name not in feature_perturbation, f"{name} changes when future data is replaced: {feature_perturbation.get(name)}"


@pytest.mark.parametrize("name", FEATURE_COLUMNS)
def test_feature_leakage_samples_are_not_vacuous(name, market, samples):
    col = feature_compute(market, samples)[name]
    assert np.isfinite(col).sum() >= 10, f"{name} is NaN at almost every sampled time"


def test_feature_leakage_with_availability_delay():
    inputs = make_market(n_days=45, seed=4, delay_ms=60_000)
    grid = grid_for(inputs)
    samples = samples_for(grid)
    assert truncation_leaks(feature_compute, inputs, grid, samples) == {}
    assert perturbation_leaks(feature_compute, inputs, grid, samples[::3]) == {}


# --- MultiTFView: every role / timeframe / column, several specs ---------------------------------------
# The view is stateless per query (each ``at(t)`` is an independent as-of lookup), so the harness's "full"
# evaluation is done on the sampled times only (grid = samples); the samples themselves are drawn from the
# dense 5m (+ mid-bar, + close+delay) grid. This keeps the suite fast without weakening the comparison.


@pytest.mark.parametrize("key", SPECS)
def test_view_truncation_no_lookahead(key, market, grid, samples):
    assert truncation_leaks(view_compute(SPECS[key]), market, samples, samples) == {}


@pytest.mark.parametrize("key", SPECS)
def test_view_perturbation_no_lookahead(key, market, grid, samples):
    assert perturbation_leaks(view_compute(SPECS[key]), market, samples, samples[::2]) == {}


@pytest.mark.parametrize("key", SPECS)
def test_view_samples_are_not_vacuous(key, market, samples):
    out = view_compute(SPECS[key])(market, samples)
    assert out["raised"].sum() >= 1, "no sample exercises the raise path"
    assert (out["raised"] == 0).sum() >= 20
    for c in view_columns(SPECS[key]):
        if "." in c and not c.endswith(META):
            assert np.isfinite(out[c]).sum() >= 10, f"{c} is NaN at almost every sampled time"


@pytest.mark.parametrize("key", SPECS)
def test_view_leakage_on_gappy_data_with_stale_rows(key, market):
    inputs = gappy(market)
    grid = grid_for(inputs)
    samples = np.unique(np.concatenate([samples_for(grid), grid[-40::7]]))  # the tail hits stale 4h rows
    compute = view_compute(SPECS[key])
    assert truncation_leaks(compute, inputs, samples, samples) == {}
    assert perturbation_leaks(compute, inputs, samples, samples[::2]) == {}
    stale_cols = [c for c in view_columns(SPECS[key]) if c.endswith(f"{H4.value}.stale")]
    assert any(np.nanmax(compute(inputs, samples)[c]) == 1.0 for c in stale_cols), "no sample exercises a stale row"


def test_view_leakage_with_availability_delay():
    inputs = make_market(n_days=45, seed=4, delay_ms=60_000)
    grid = grid_for(inputs)
    grid = np.unique(np.concatenate([grid, inputs.bars[M5].available_at_ms]))  # exact close+delay instants
    samples = samples_for(grid)
    for spec in SPECS.values():
        compute = view_compute(spec)
        assert truncation_leaks(compute, inputs, samples, samples) == {}
        assert perturbation_leaks(compute, inputs, samples, samples[::3]) == {}


def test_event_driven_snapshots_equal_snapshots_from_truncated_data():
    """Drive the view by SimulatedEventClock trigger events (as Phase 3 will): the snapshot at each event
    equals the snapshot built from only the data available at the event's ``available_at_ms``."""
    delay = 30_000
    inputs = make_market(n_days=30, seed=6, delay_ms=delay)
    spec = SPECS["m15_trigger"]
    clock = SimulatedEventClock("BTCUSDT", (M15, H1, H4), START_MS, START_MS + 30 * 24 * HOUR, delay_ms=delay)
    events = [e for e in clock.events if e.timeframe == spec.trigger_tf]
    rng = np.random.default_rng(3)
    picked = [events[i] for i in sorted(rng.choice(len(events), 25, replace=False))] + events[-2:]
    full = MultiTFView.from_bars(inputs.bars, (M15, H1, H4))
    checked = 0
    for ev in picked:
        part = MultiTFView.from_bars(inputs.available_until(ev.available_at_ms).bars, (M15, H1, H4))
        try:
            a = full.for_event(ev, spec)
        except LookAheadError:
            with pytest.raises(LookAheadError):
                part.for_event(ev, spec)
            continue
        b = part.for_event(ev, spec)
        for ra, rb in zip((a.trigger, a.setup, *a.context), (b.trigger, b.setup, *b.context), strict=True):
            assert (ra.open_ms, ra.available_at_ms, ra.bars_seen, ra.complete, ra.stale) == (
                rb.open_ms, rb.available_at_ms, rb.bars_seen, rb.complete, rb.stale)
            assert np.array_equal(list(ra.values.values()), list(rb.values.values()), equal_nan=True)
        assert a.trigger.close_ms == ev.close_ms
        checked += 1
    assert checked >= 20


class _PeekingView(MultiTFView):
    """Deliberately broken: reads each timeframe one bar into the future."""

    def row_at(self, tf, t_ms):
        return super().row_at(tf, int(t_ms) + tf.ms)


def test_canary_the_harness_catches_a_view_that_peeks_one_bar_ahead(market, samples):
    leaky = view_compute(SPECS["h1_legacy"], _PeekingView)
    assert truncation_leaks(leaky, market, samples, samples)
    assert perturbation_leaks(leaky, market, samples, samples[::2])

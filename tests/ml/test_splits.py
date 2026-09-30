"""Purged, embargoed expanding-window walk-forward folds: hand-computed cases and exhaustive overlap checks."""

import numpy as np
import pytest

from arven.ml.splits import HOUR_MS, MONTH_MS, generate_folds, purge_and_embargo_train_mask, validation_mask

DAY_MS = 86_400_000


def test_generate_folds_expanding_window_boundaries():
    start, end = 0, 24 * MONTH_MS
    folds = generate_folds(start, end, min_train_months=12, retrain_interval_months=3)
    assert len(folds) == 4
    assert folds[0].train_start_ms == start and folds[0].valid_start_ms == 12 * MONTH_MS
    for a, b in zip(folds, folds[1:]):
        assert a.valid_end_ms == b.valid_start_ms == b.train_end_ms  # expanding: contiguous, no gap
        assert b.train_end_ms == b.valid_start_ms
    assert folds[-1].valid_end_ms == end


def test_generate_folds_last_fold_is_clipped_to_the_window_end():
    start, end = 0, 13 * MONTH_MS  # only 1 month past min_train
    folds = generate_folds(start, end, min_train_months=12, retrain_interval_months=3)
    assert len(folds) == 1 and folds[0].valid_end_ms == end


def test_generate_folds_empty_when_window_shorter_than_min_train():
    folds = generate_folds(0, 6 * MONTH_MS, min_train_months=12, retrain_interval_months=3)
    assert folds == ()


def test_generate_folds_rejects_bad_range():
    with pytest.raises(ValueError):
        generate_folds(100, 100, 1, 1)


def test_purge_removes_rows_whose_label_horizon_overlaps_validation():
    folds = generate_folds(0, 24 * MONTH_MS, 12, 3)
    fold = folds[0]
    t = np.array([0, fold.valid_start_ms - 10 * HOUR_MS])
    h_no_overlap = np.array([1 * HOUR_MS, fold.valid_start_ms - 1 * HOUR_MS])
    h_overlap = np.array([1 * HOUR_MS, fold.valid_start_ms + 1 * HOUR_MS])
    mask1 = purge_and_embargo_train_mask(t, h_no_overlap, fold, embargo_hours=0)
    mask2 = purge_and_embargo_train_mask(t, h_overlap, fold, embargo_hours=0)
    assert mask1.tolist() == [True, True]
    assert mask2.tolist() == [True, False]


def test_embargo_removes_rows_immediately_before_validation_even_without_horizon_overlap():
    folds = generate_folds(0, 24 * MONTH_MS, 12, 3)
    fold = folds[0]
    t = np.array([fold.valid_start_ms - 200 * HOUR_MS, fold.valid_start_ms - 10 * HOUR_MS])
    h = t + HOUR_MS  # short horizon, no overlap with validation on its own
    mask = purge_and_embargo_train_mask(t, h, fold, embargo_hours=96)
    assert mask.tolist() == [True, False]  # the second row falls inside the 96h embargo window


def test_validation_mask_is_half_open():
    folds = generate_folds(0, 24 * MONTH_MS, 12, 3)
    fold = folds[0]
    t = np.array([fold.valid_start_ms - 1, fold.valid_start_ms, fold.valid_end_ms - 1, fold.valid_end_ms])
    assert validation_mask(t, fold).tolist() == [False, True, True, False]


@pytest.mark.parametrize("seed", range(20))
def test_no_fold_ever_has_a_training_row_overlapping_its_own_validation_block(seed):
    """Exhaustive/property check: for many random row sets, the purge+embargo mask never admits a row whose
    label window reaches into the fold's validation block."""
    rng = np.random.default_rng(seed)
    start, end = 0, 30 * MONTH_MS
    folds = generate_folds(start, end, 12, 3)
    n = 500
    t = rng.integers(start, end, n).astype(np.int64)
    horizon = t + rng.integers(HOUR_MS, 72 * HOUR_MS, n).astype(np.int64)
    for fold in folds:
        mask = purge_and_embargo_train_mask(t, horizon, fold, embargo_hours=96)
        kept_t, kept_h = t[mask], horizon[mask]
        assert np.all(kept_h < fold.valid_start_ms)  # no label window reaches the validation block
        assert np.all(kept_t < fold.valid_start_ms - 96 * HOUR_MS)  # embargo respected
        assert np.all(kept_t < fold.train_end_ms)


def test_folds_are_strictly_chronological_never_shuffled():
    folds = generate_folds(0, 24 * MONTH_MS, 12, 3)
    starts = [f.valid_start_ms for f in folds]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)

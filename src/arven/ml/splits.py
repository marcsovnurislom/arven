"""Purged, embargoed expanding-window walk-forward folds (docs/architecture.md section 10 rule 8, section
11's "expanding-window walk-forward"; approved decisions D4).

Fold boundaries are a deterministic, chronological, **never shuffled** walk over
``development ∪ validation`` (the sealed test period is categorically unreachable: fold generation takes an
:class:`~arven.core.splitguard.AllowedWindow`, resolved only from those two periods by the caller — the
same, already-tested :class:`~arven.core.splitguard.SplitGuard` mechanism Stage 4/5 use, not a new one).

Purging: a training row is removed from a fold if its own label window ``[t_ms, label_horizon_ms]``
overlaps that fold's validation block, even if ``t_ms`` itself is chronologically before the block.
Embargo: an additional buffer of ``embargo_hours`` immediately *before* each validation block is also
excluded from that fold's training set. This is expanding-window (not rolling) walk-forward, so a fold's
validation rows legitimately become training rows for *later* folds once their own labels have safely
resolved — the horizon-overlap purge is re-evaluated fresh for every fold, so it automatically also
excludes any row (validation-period or not) whose label window would overlap a *later* fold's validation
block; a separate "embargo after" is therefore not needed on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MONTH_MS = 30 * 86_400_000  # a fixed 30-day "month", used only for fold step sizing (not calendar-exact)
HOUR_MS = 3_600_000


@dataclass(frozen=True, slots=True)
class Fold:
    fold_index: int
    train_start_ms: int
    train_end_ms: int  # exclusive; the raw (pre-purge) end of the expanding training window
    valid_start_ms: int
    valid_end_ms: int  # exclusive


def generate_folds(window_start_ms: int, window_end_ms: int, min_train_months: int, retrain_interval_months: int) -> tuple[Fold, ...]:
    """Expanding-window fold boundaries covering ``[window_start_ms, window_end_ms)``."""
    if window_end_ms <= window_start_ms:
        raise ValueError("window_end_ms must be after window_start_ms")
    first_valid_start = window_start_ms + min_train_months * MONTH_MS
    step = retrain_interval_months * MONTH_MS
    folds: list[Fold] = []
    valid_start = first_valid_start
    idx = 0
    while valid_start < window_end_ms:
        valid_end = min(valid_start + step, window_end_ms)
        folds.append(Fold(idx, window_start_ms, valid_start, valid_start, valid_end))
        valid_start = valid_end
        idx += 1
    return tuple(folds)


def purge_and_embargo_train_mask(
    row_t_ms: np.ndarray, row_horizon_ms: np.ndarray, fold: Fold, embargo_hours: int
) -> np.ndarray:
    """Boolean mask over ``row_t_ms`` selecting rows usable for training this fold: chronologically before
    the (embargoed) validation block, with no label-window overlap into it."""
    embargo = embargo_hours * HOUR_MS
    embargo_start = fold.valid_start_ms - embargo
    before_train_end = row_t_ms < fold.train_end_ms
    no_horizon_overlap = row_horizon_ms < fold.valid_start_ms
    before_embargo = row_t_ms < embargo_start
    return before_train_end & no_horizon_overlap & before_embargo


def validation_mask(row_t_ms: np.ndarray, fold: Fold) -> np.ndarray:
    return (row_t_ms >= fold.valid_start_ms) & (row_t_ms < fold.valid_end_ms)

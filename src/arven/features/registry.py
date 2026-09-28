"""The feature registry: the ordered list of every column the feature builder produces."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from arven.core.features_config import FeaturesConfig
from arven.core.timeframes import Timeframe
from arven.features.bars import bar_features
from arven.features.futures import funding_specs, oi_specs, time_specs
from arven.features.spec import FeatureSpec

# Timeframes in output-column order. Their source grid is joined onto the 1h decision grid.
BAR_TIMEFRAMES: tuple[Timeframe, ...] = (Timeframe.H1, Timeframe.H4, Timeframe.M15, Timeframe.M5)

READY_COLUMN = "feat_ready"


def build_registry(cfg: FeaturesConfig) -> tuple[FeatureSpec, ...]:
    specs: list[FeatureSpec] = []
    for tf in BAR_TIMEFRAMES:
        specs += [f.spec for f in bar_features(tf, cfg)]
    specs += funding_specs(cfg)
    specs += oi_specs(cfg)
    specs += time_specs()
    specs.append(FeatureSpec(READY_COLUMN, "quality", "derived", 1, False,
                             "1 if every required feature is finite (warm-up complete, inputs fresh)"))
    names = [s.name for s in specs]
    if len(set(names)) != len(names):
        raise ValueError("duplicate feature names in registry")
    return tuple(specs)


def definition_hash(cfg: FeaturesConfig) -> str:
    """Fingerprint of the feature definitions: every spec plus the feature configuration."""
    payload = {"config": cfg.config_hash(), "specs": [asdict(s) for s in build_registry(cfg)]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

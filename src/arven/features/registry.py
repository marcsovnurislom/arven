"""The feature registry: the ordered list of every column the feature builder produces."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace

from arven.core.features_config import FeaturesConfig
from arven.core.timeframes import Timeframe
from arven.features.bars import bar_features
from arven.features.futures import funding_specs, oi_specs, time_specs
from arven.features.spec import FeatureSpec

# Timeframes in output-column order. Their source grid is joined onto the 1h decision grid.
BAR_TIMEFRAMES: tuple[Timeframe, ...] = (Timeframe.H1, Timeframe.H4, Timeframe.M15, Timeframe.M5)

READY_COLUMN = "feat_ready"


# Bar features that need exchange trade flow (trade counts, taker-buy volume); an OTC feed such as Dukascopy has none.
TRADE_FLOW_SUFFIXES: tuple[str, ...] = ("_taker_buy_ratio", "_rel_trades")


def build_registry(
    cfg: FeaturesConfig, funding_required: bool = True, trade_flow_required: bool = True
) -> tuple[FeatureSpec, ...]:
    """``funding_required=False`` for a market without meaningful funding (gold: a spot CFD, or a perpetual whose
    rate is always 0); ``trade_flow_required=False`` for a feed without trade counts / taker volume (Dukascopy). Those
    columns are still computed but no longer gate ``feat_ready``. The defaults are the BTC registry, unchanged."""
    specs: list[FeatureSpec] = []
    for tf in BAR_TIMEFRAMES:
        bar = [f.spec for f in bar_features(tf, cfg)]
        if not trade_flow_required:
            bar = [replace(s, required=False) if s.name.endswith(TRADE_FLOW_SUFFIXES) else s for s in bar]
        specs += bar
    specs += funding_specs(cfg) if funding_required else [replace(s, required=False) for s in funding_specs(cfg)]
    specs += oi_specs(cfg)
    specs += time_specs()
    specs.append(FeatureSpec(READY_COLUMN, "quality", "derived", 1, False,
                             "1 if every required feature is finite (warm-up complete, inputs fresh)"))
    names = [s.name for s in specs]
    if len(set(names)) != len(names):
        raise ValueError("duplicate feature names in registry")
    return tuple(specs)


def definition_hash(cfg: FeaturesConfig, funding_required: bool = True, trade_flow_required: bool = True) -> str:
    """Fingerprint of the feature definitions: every spec plus the feature configuration."""
    specs = build_registry(cfg, funding_required, trade_flow_required)
    payload = {"config": cfg.config_hash(), "specs": [asdict(s) for s in specs]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

"""``kind`` (config/live.yaml) -> the code that runs it. Adding a strategy to the live loop = write a class with
``strategy_id``, ``title``, ``scan`` and ``resolve`` (:class:`arven.live.base.LiveStrategy`), add one line here, and
one entry in ``config/live.yaml`` (docs/LIVE_SIGNALS.md walks through it)."""

from __future__ import annotations

from collections.abc import Callable

from arven.backtest.strategy_s4_provider import ImpulseRetestProvider
from arven.backtest.strategy_s5_provider import SqueezeBreakoutProvider
from arven.backtest.strategy_s6_provider import TrendPullbackProvider
from arven.core.live_config import LiveConfig, LiveStrategyConfig
from arven.live.base import LiveStrategy
from arven.live.strategies import CrowdedShortsStrategy, ProviderStrategy, S7Strategy

KINDS: dict[str, Callable[[LiveStrategyConfig], LiveStrategy]] = {
    "s4_impulse_retest": lambda c: ProviderStrategy(c, ImpulseRetestProvider),
    "s5_squeeze_breakout": lambda c: ProviderStrategy(c, SqueezeBreakoutProvider),
    "s6_trend_pullback": lambda c: ProviderStrategy(c, TrendPullbackProvider),
    "s7": S7Strategy,
    "crowded_shorts": CrowdedShortsStrategy,
}

NEEDS_FEATURES = frozenset({"crowded_shorts"})  # kinds that read the Stage 3 feature table (built only if one is enabled)


def build_strategies(cfg: LiveConfig) -> list[LiveStrategy]:
    """Every enabled strategy, in config order. An unknown kind or bad params fail loudly at start-up, not mid-run."""
    out = []
    for s in cfg.enabled():
        if s.kind not in KINDS:
            raise ValueError(f"strategy {s.id}: unknown kind {s.kind!r} (known: {sorted(KINDS)})")
        out.append(KINDS[s.kind](s))
    return out


def needs_features(cfg: LiveConfig) -> bool:
    return any(s.kind in NEEDS_FEATURES for s in cfg.enabled())


__all__ = ["KINDS", "NEEDS_FEATURES", "build_strategies", "needs_features"]

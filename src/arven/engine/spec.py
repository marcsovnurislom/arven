"""What one strategy declares about its own timeframes and readiness - read by the (later) event-driven
decision engine to know when to evaluate it and what context it may read. Not used by the legacy
``arven.strategies``/``arven.decision`` path (that path keeps its own ``RegimeGate``/``Strategy`` protocol
unchanged, see ``arven.strategies.base``).
"""

from __future__ import annotations

from dataclasses import dataclass

from arven.core.timeframes import Timeframe


@dataclass(frozen=True, slots=True)
class StrategySpec:
    strategy_id: str
    version: str
    context_tfs: tuple[Timeframe, ...]  # coarser-or-equal to setup_tf; () if the strategy reads no context
    setup_tf: Timeframe
    trigger_tf: Timeframe  # the strategy is evaluated only on this timeframe's BarCloseEvent
    warmup_bars: int  # trigger_tf bars needed before the strategy is considered ready
    allowed_regimes: frozenset[str] | None = None  # Regime.label strings; None = no regime gate

    def __post_init__(self) -> None:
        if not self.strategy_id:
            raise ValueError("strategy_id must not be empty")
        if not self.version:
            raise ValueError("version must not be empty")
        if self.trigger_tf.ms > self.setup_tf.ms:
            raise ValueError("trigger_tf must not be coarser than setup_tf")
        for tf in self.context_tfs:
            if tf.ms < self.setup_tf.ms:
                raise ValueError(f"context timeframe {tf} must not be finer than setup_tf {self.setup_tf}")
        if self.warmup_bars < 1:
            raise ValueError("warmup_bars must be positive")

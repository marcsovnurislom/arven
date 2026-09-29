"""The risk engine: a fixed, ordered pipeline of independent veto/reduce rules.

Each rule below is numbered to match ``docs/architecture.md`` section 14 (rule 2, the macro-event blackout,
is explicitly deferred there — "later stage" — and is not implemented). Position sizing reuses
:func:`arven.backtest.margin.liquidation_price` (a pure function, not the execution engine) so the
liquidation-distance formula has one source of truth with the backtester; nothing here calls into
``arven.backtest.engine``/``execution``/``accounting`` or bypasses the Stage 4 fill/accounting path.

Statefulness (daily loss, drawdown halt, loss-streak cooldown) is carried causally across sequential
``apply`` calls, exactly like :class:`arven.regime.detector.RegimeDetector` — it must be called once per
decision time, in order, and reset before reuse.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from arven.backtest.margin import liquidation_price
from arven.backtest.provider import PortfolioSnapshot
from arven.core.backtest_config import BacktestConfig
from arven.core.risk_config import RiskConfig
from arven.core.signal import Signal
from arven.core.types import Action
from arven.decision.engine import ProposedDecision

DAY_MS = 86_400_000


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """A full record of what the risk engine did at one decision time (for logging/explanation)."""

    t_ms: int
    outcome: Literal["signal", "no_proposal", "veto"]
    reason: str
    detail: dict[str, float | str | bool | None]


def _pass_through_reasons(proposed: ProposedDecision) -> RiskDecision:
    return RiskDecision(proposed.t_ms, "no_proposal", "decision layer proposed NO_TRADE", {})


class RiskEngine:
    def __init__(self, cfg: RiskConfig, bt_cfg: BacktestConfig) -> None:
        self.cfg = cfg
        self.leverage = bt_cfg.leverage
        self.maintenance_margin_rate = bt_cfg.maintenance_margin_rate
        self.reset()

    def reset(self) -> None:
        self._peak_equity: float | None = None
        self._drawdown_halted = False
        self._day: int | None = None
        self._day_start_equity: float | None = None
        self._daily_halted = False
        self._prev_side = 0
        self._entry_equity: float | None = None
        self._consecutive_losses = 0
        self._cooldown_remaining = 0
        self._last_t_ms: int | None = None

    def _update_state(self, t_ms: int, portfolio: PortfolioSnapshot) -> None:
        """Advance the stateful circuit breakers from the observed portfolio snapshot. Causal: uses only the
        current and previously observed equity, never anything from later in the run."""
        equity = portfolio.equity
        self._peak_equity = equity if self._peak_equity is None else max(self._peak_equity, equity)
        dd = 0.0 if not self._peak_equity else (self._peak_equity - equity) / self._peak_equity
        if dd >= self.cfg.max_drawdown_halt_pct:
            self._drawdown_halted = True
        elif self._drawdown_halted and dd <= self.cfg.drawdown_resume_pct:
            self._drawdown_halted = False

        day = t_ms // DAY_MS
        if day != self._day:
            self._day, self._day_start_equity, self._daily_halted = day, equity, False
        elif self._day_start_equity:
            loss = (self._day_start_equity - equity) / self._day_start_equity
            if loss >= self.cfg.max_daily_loss_pct:
                self._daily_halted = True

        if self._prev_side != 0 and portfolio.side == 0:
            pnl = equity - (self._entry_equity if self._entry_equity is not None else equity)
            self._consecutive_losses = self._consecutive_losses + 1 if pnl < 0 else 0
            if self._consecutive_losses >= self.cfg.cooldown_after_losses:
                self._cooldown_remaining = self.cfg.cooldown_bars
        elif self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
        self._prev_side = portfolio.side

    def _veto(self, t_ms: int, reason: str, **detail: float | str | bool | None) -> tuple[None, RiskDecision]:
        return None, RiskDecision(t_ms, "veto", reason, detail)

    def apply(
        self, proposed: ProposedDecision, portfolio: PortfolioSnapshot, t_ms: int, feat_ready: float, fund_z: float
    ) -> tuple[Signal | None, RiskDecision]:
        if self._last_t_ms is not None and t_ms <= self._last_t_ms:
            raise ValueError("RiskEngine.apply must be called in strictly increasing time order")
        self._last_t_ms = t_ms
        self._update_state(t_ms, portfolio)

        if proposed.action == Action.NO_TRADE:
            return None, _pass_through_reasons(proposed)

        # 1. data-quality gate
        if not (math.isfinite(feat_ready) and feat_ready == 1.0):
            return self._veto(t_ms, "stale_or_incomplete_data", feat_ready=feat_ready)

        # 7 (checked early: nothing downstream matters if any of these hold)
        if portfolio.side != 0 or portfolio.order_pending:
            return self._veto(t_ms, "position_already_open", side=portfolio.side, order_pending=portfolio.order_pending)
        if self._daily_halted:
            return self._veto(t_ms, "max_daily_loss_halt", day_start_equity=self._day_start_equity, equity=portfolio.equity)
        if self._drawdown_halted:
            peak = self._peak_equity or 0.0
            return self._veto(t_ms, "max_drawdown_halt", peak_equity=peak, equity=portfolio.equity)
        if self._cooldown_remaining > 0:
            return self._veto(t_ms, "loss_streak_cooldown", consecutive_losses=self._consecutive_losses, bars_remaining=self._cooldown_remaining)

        direction = 1 if proposed.action == Action.LONG else -1
        reduce = 1.0

        # 3. volatility guard
        if proposed.regime.stress and self.cfg.veto_on_stress:
            return self._veto(t_ms, "extreme_volatility_stress", regime=proposed.regime.label)
        if proposed.regime.vol.value == "HIGH":
            reduce *= self.cfg.high_vol_size_multiplier

        # 4. funding guard: entering the side that PAYS extreme funding (positive rate -> longs pay;
        # negative rate -> shorts pay; see arven.backtest.accounting).
        paying_z = direction * fund_z  # > 0 whenever this direction would be the paying side
        if math.isfinite(fund_z):
            if paying_z >= self.cfg.funding_guard_veto_z:
                return self._veto(t_ms, "extreme_funding", direction=direction, fund_z=fund_z)
            if paying_z >= self.cfg.funding_guard_reduce_z:
                reduce *= self.cfg.funding_guard_reduce_multiplier

        # 5. stop & target, bounded
        assert proposed.stop_pct is not None and proposed.take_profit_pct is not None
        stop_pct = min(max(proposed.stop_pct, self.cfg.min_stop_pct), self.cfg.max_stop_pct)
        take_profit_pct = max(proposed.take_profit_pct, stop_pct * self.cfg.min_reward_risk_ratio)

        # 6. position sizing: risk_fraction / stop_distance, then the reduce multipliers, then capped.
        notional_fraction = self.cfg.risk_fraction_per_trade / stop_pct * reduce
        notional_fraction = min(notional_fraction, self.cfg.max_notional_fraction, self.leverage)

        # 8. liquidation-distance check (a pure function of side/leverage/mmr, not of price - see module docstring)
        liq_distance_pct = abs(1.0 - liquidation_price(direction, 1.0, self.leverage, self.maintenance_margin_rate))
        if liq_distance_pct < self.cfg.liquidation_min_multiple * stop_pct:
            return self._veto(t_ms, "stop_too_close_to_liquidation", liq_distance_pct=liq_distance_pct, stop_pct=stop_pct)

        signal = Signal(
            t_ms, proposed.action, notional_fraction=notional_fraction, stop_pct=stop_pct,
            take_profit_pct=take_profit_pct, max_holding_minutes=proposed.max_holding_minutes,
            tag=f"{'+'.join(proposed.contributing)}|{proposed.regime.label}|score={proposed.score:.3f}",
        )
        self._entry_equity = portfolio.equity
        detail = {
            "notional_fraction": notional_fraction, "stop_pct": stop_pct, "take_profit_pct": take_profit_pct,
            "reduce_multiplier": reduce, "regime": proposed.regime.label, "score": proposed.score,
            "contributing": "+".join(proposed.contributing),
        }
        return signal, RiskDecision(t_ms, "signal", "signal issued", detail)

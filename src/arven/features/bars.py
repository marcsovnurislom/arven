"""Bar-based features (5m, 15m, 1h, 4h).

Each feature is defined once, next to its specification, as a :class:`BarFeature`. All are computed on a
*regularized* bar grid (missing / incomplete bars are NaN rows) with the causal primitives in
:mod:`arven.features.indicators`, and are then joined to the decision grid by
:func:`arven.features.asof.asof_join` (never by ``open_time``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from arven.core.features_config import FeaturesConfig
from arven.core.series import BarSeries
from arven.core.timeframes import Timeframe
from arven.features import indicators as ind
from arven.features.spec import FeatureSpec

_M5_PER_HOUR = 12
# Column-name prefixes: valid SQL identifiers (a name may not start with a digit).
PREFIX: dict[Timeframe, str] = {Timeframe.H1: "h1", Timeframe.H4: "h4", Timeframe.M15: "m15", Timeframe.M5: "m5"}


class BarContext:
    """A regularized bar series plus a memo for intermediates shared between features."""

    def __init__(self, bars: BarSeries) -> None:
        self.bars = bars
        self._memo: dict[str, np.ndarray] = {}

    def memo(self, key: str, fn: Callable[[], np.ndarray]) -> np.ndarray:
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]

    @property
    def o(self) -> np.ndarray:
        return self.bars.open

    @property
    def h(self) -> np.ndarray:
        return self.bars.high

    @property
    def l(self) -> np.ndarray:  # noqa: E743
        return self.bars.low

    @property
    def c(self) -> np.ndarray:
        return self.bars.close

    @property
    def v(self) -> np.ndarray:
        return self.bars.volume


@dataclass(frozen=True)
class BarFeature:
    spec: FeatureSpec
    compute: Callable[[BarContext], np.ndarray]


def _feat(
    out: list[BarFeature],
    tf: Timeframe,
    name: str,
    group: str,
    warmup: int,
    description: str,
    fn: Callable[[BarContext], np.ndarray],
) -> None:
    full = f"{PREFIX[tf]}_{name}"
    out.append(BarFeature(FeatureSpec(full, group, tf.value, warmup, True, description), fn))


def _returns(out: list[BarFeature], tf: Timeframe, horizons: tuple[int, ...]) -> None:
    for k in horizons:
        _feat(out, tf, f"ret_{k}", "returns", k + 1, f"log return over {k} {tf.value} bars",
              lambda x, k=k: ind.log_return(x.c, k))


def _atr_pct(out: list[BarFeature], tf: Timeframe, cfg: FeaturesConfig) -> None:
    p = cfg.volatility.atr_period
    _feat(out, tf, "atr_pct", "volatility", cfg.warmup(p) + 1, f"Wilder ATR({p}) / close",
          lambda x: ind.safe_divide(x.memo("atr", lambda: ind.atr(x.h, x.l, x.c, p, cfg.warmup(p))), x.c))


def _ema_block(out: list[BarFeature], tf: Timeframe, cfg: FeaturesConfig) -> None:
    t = cfg.trend

    def ema_of(x: BarContext, p: int) -> np.ndarray:
        return x.memo(f"ema_{p}", lambda: ind.ema(x.c, p, cfg.warmup(p)))

    for p in t.ema_periods:
        _feat(out, tf, f"ema_dist_{p}", "trend", cfg.warmup(p), f"log(close / EMA{p})",
              lambda x, p=p: ind.log_ratio(x.c, ema_of(x, p)))
    sp = t.slope_ema_period
    _feat(out, tf, "ema_slope", "trend", cfg.warmup(sp) + t.slope_bars,
          f"log(EMA{sp} / EMA{sp} {t.slope_bars} bars earlier)",
          lambda x: ind.log_ratio(ema_of(x, sp), ind.shift(ema_of(x, sp), t.slope_bars)))


def _adx(out: list[BarFeature], tf: Timeframe, cfg: FeaturesConfig) -> None:
    p = cfg.trend.adx_period
    _feat(out, tf, "adx", "trend", p + cfg.warmup(p), f"Wilder ADX({p})",
          lambda x: ind.adx(x.h, x.l, x.c, p, cfg.warmup(p)))


def _rsi(out: list[BarFeature], tf: Timeframe, cfg: FeaturesConfig) -> None:
    p = cfg.momentum.rsi_period
    _feat(out, tf, "rsi", "momentum", cfg.warmup(p) + 1, f"Wilder RSI({p})", lambda x: ind.rsi(x.c, p, cfg.warmup(p)))


def _taker_ratio(out: list[BarFeature], tf: Timeframe) -> None:
    _feat(out, tf, "taker_buy_ratio", "volume", 1, "taker-buy volume / volume (NaN when volume is 0)",
          lambda x: ind.safe_divide(x.bars.taker_buy_volume, x.v))


def _relative(x_series: Callable[[BarContext], np.ndarray], window: int) -> Callable[[BarContext], np.ndarray]:
    """value / mean of the previous ``window`` values (current bar excluded)."""

    def fn(x: BarContext) -> np.ndarray:
        s = x_series(x)
        return ind.safe_divide(s, ind.shift(ind.rolling_mean(s, window), 1))

    return fn


def _h1(cfg: FeaturesConfig) -> list[BarFeature]:
    tf = Timeframe.H1
    out: list[BarFeature] = []
    v, m = cfg.volatility, cfg.momentum
    _returns(out, tf, cfg.returns.h1_horizons)
    _atr_pct(out, tf, cfg)

    def ret1(x: BarContext) -> np.ndarray:
        return x.memo("ret1", lambda: ind.log_return(x.c, 1))

    for label, w in (("short", v.cc_vol_short_bars), ("long", v.cc_vol_long_bars)):
        _feat(out, tf, f"cc_vol_{w}", "volatility", w + 1, f"std of 1h log returns over {w} bars ({label})",
              lambda x, w=w: ind.rolling_std(ret1(x), w, ddof=1))
    s, lg = v.cc_vol_short_bars, v.cc_vol_long_bars
    _feat(out, tf, "vol_ratio", "volatility", lg + 1, f"cc_vol_{s} / cc_vol_{lg}",
          lambda x: ind.safe_divide(ind.rolling_std(ret1(x), s, ddof=1), ind.rolling_std(ret1(x), lg, ddof=1)))
    _feat(out, tf, f"parkinson_{v.parkinson_window}", "volatility", v.parkinson_window,
          f"Parkinson volatility over {v.parkinson_window} bars",
          lambda x: ind.parkinson_vol(x.h, x.l, v.parkinson_window))

    _ema_block(out, tf, cfg)
    _adx(out, tf, cfg)
    for n in cfg.trend.donchian_windows:
        _feat(out, tf, f"donchian_pos_{n}", "trend", n, f"close position in the {n}-bar high/low channel",
              lambda x, n=n: ind.donchian_position(x.h, x.l, x.c, n))

    _rsi(out, tf, cfg)
    wf, ws, wg = cfg.warmup(m.macd_fast), cfg.warmup(m.macd_slow), cfg.warmup(m.macd_signal)
    _feat(out, tf, "macd_hist", "momentum", ws + wg - 1,
          f"MACD({m.macd_fast},{m.macd_slow},{m.macd_signal}) histogram / close",
          lambda x: ind.safe_divide(
              ind.macd_histogram(x.c, m.macd_fast, m.macd_slow, m.macd_signal, wf, ws, wg), x.c))
    _feat(out, tf, "bb_z", "momentum", m.bollinger_window, "Bollinger z-score of close",
          lambda x: x.memo("bb", lambda: np.stack(ind.bollinger(x.c, m.bollinger_window, m.bollinger_k)))[0])
    _feat(out, tf, "bb_width", "momentum", m.bollinger_window, "Bollinger band width / SMA",
          lambda x: x.memo("bb", lambda: np.stack(ind.bollinger(x.c, m.bollinger_window, m.bollinger_k)))[1])

    rw = cfg.volume.relative_window
    _feat(out, tf, "rel_volume", "volume", rw + 1, f"volume / mean volume of the previous {rw} bars",
          _relative(lambda x: x.v, rw))
    _taker_ratio(out, tf)
    _feat(out, tf, "rel_trades", "volume", rw + 1, f"trade count / mean of the previous {rw} bars",
          _relative(lambda x: x.bars.trade_count, rw))

    def rng(x: BarContext) -> np.ndarray:
        return x.h - x.l

    _feat(out, tf, "body_ratio", "candle", 1, "(close - open) / (high - low)",
          lambda x: ind.safe_divide(x.c - x.o, rng(x)))
    _feat(out, tf, "upper_wick", "candle", 1, "(high - max(open, close)) / (high - low)",
          lambda x: ind.safe_divide(x.h - np.maximum(x.o, x.c), rng(x)))
    _feat(out, tf, "lower_wick", "candle", 1, "(min(open, close) - low) / (high - low)",
          lambda x: ind.safe_divide(np.minimum(x.o, x.c) - x.l, rng(x)))
    return out


def _h4(cfg: FeaturesConfig) -> list[BarFeature]:
    tf = Timeframe.H4
    out: list[BarFeature] = []
    _returns(out, tf, cfg.returns.h4_horizons)
    _atr_pct(out, tf, cfg)
    _ema_block(out, tf, cfg)
    _adx(out, tf, cfg)
    _rsi(out, tf, cfg)
    _taker_ratio(out, tf)
    return out


def _m15(cfg: FeaturesConfig) -> list[BarFeature]:
    tf = Timeframe.M15
    out: list[BarFeature] = []
    _returns(out, tf, cfg.returns.m15_horizons)
    _rsi(out, tf, cfg)
    return out


def _m5(cfg: FeaturesConfig) -> list[BarFeature]:
    tf = Timeframe.M5
    out: list[BarFeature] = []
    for hours in (cfg.volatility.rv5m_short_hours, cfg.volatility.rv5m_long_hours):
        n = _M5_PER_HOUR * hours

        def fn(x: BarContext, n=n, hours=hours) -> np.ndarray:
            r = x.memo("ret1", lambda: ind.log_return(x.c, 1))
            return np.sqrt(ind.rolling_sum(r * r, n) / hours)

        _feat(out, tf, f"rv_{hours}h", "volatility", n + 1,
              f"realized vol from 5m returns over {hours}h, per sqrt-hour", fn)
    return out


_BUILDERS = {Timeframe.H1: _h1, Timeframe.H4: _h4, Timeframe.M15: _m15, Timeframe.M5: _m5}


def bar_features(tf: Timeframe, cfg: FeaturesConfig) -> list[BarFeature]:
    return _BUILDERS[tf](cfg)


def compute_bar_features(tf: Timeframe, regular_bars: BarSeries, cfg: FeaturesConfig) -> dict[str, np.ndarray]:
    """Compute every feature of ``tf`` on its own (regularized) grid. Result arrays align with ``regular_bars``."""
    ctx = BarContext(regular_bars)
    return {f.spec.name: ind.finite_or_nan(f.compute(ctx)) for f in bar_features(tf, cfg)}


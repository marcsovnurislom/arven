"""Causal indicator primitives on float64 arrays.

Every function returns an array of the same length as its input, and **output[i] depends only on
input[:i+1]**. Conventions:

- NaN in, NaN out: a window containing a NaN yields NaN; recursive indicators restart after a NaN and
  need their warm-up again. Nothing is interpolated or filled.
- Rolling windows include the current bar and are computed by explicit shifted addition, so a value never
  depends on the length of the array (this makes truncated and full computations bit-identical).
- Recursive indicators (EMA, Wilder smoothing) are seeded at the first valid input and emit values only
  after ``min_count`` valid inputs (the warm-up).
- Outputs are never +/-inf: non-finite results are returned as NaN.
"""

from __future__ import annotations

import math

import numpy as np

_NAN = float("nan")


def finite_or_nan(x: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(x), x, np.nan)


def shift(x: np.ndarray, k: int) -> np.ndarray:
    """Lag by ``k >= 0`` bars: ``out[i] = x[i-k]`` (NaN for ``i < k``). Negative shifts would look ahead."""
    if k < 0:
        raise ValueError("shift must be non-negative (a negative shift looks into the future)")
    out = np.full(len(x), np.nan)
    if k < len(x):
        out[k:] = x[: len(x) - k]
    return out


def log_ratio(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """log(a / b), NaN where either is not strictly positive."""
    with np.errstate(all="ignore"):
        ok = (a > 0) & (b > 0)
        out = np.full(np.broadcast(a, b).shape, np.nan)
        out[ok] = np.log(a[ok] / b[ok])
    return out


def safe_divide(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """num / den, NaN where den == 0 (or either is NaN)."""
    with np.errstate(all="ignore"):
        out = np.where(den != 0, num / den, np.nan)
    return finite_or_nan(out)


def log_return(close: np.ndarray, k: int) -> np.ndarray:
    return log_ratio(close, shift(close, k))


# --- rolling windows (include the current bar) ----------------------------------------------------


def rolling_sum(x: np.ndarray, w: int) -> np.ndarray:
    n = len(x)
    out = np.full(n, np.nan)
    if w < 1:
        raise ValueError("window must be >= 1")
    if n < w:
        return out
    acc = np.zeros(n - w + 1)
    for j in range(w):
        acc += x[w - 1 - j : n - j]
    out[w - 1 :] = acc
    return out


def rolling_mean(x: np.ndarray, w: int) -> np.ndarray:
    return rolling_sum(x, w) / w


def rolling_std(x: np.ndarray, w: int, ddof: int = 0) -> np.ndarray:
    """Standard deviation over the trailing ``w`` values (two-pass, numerically stable)."""
    n = len(x)
    out = np.full(n, np.nan)
    if w - ddof < 1:
        raise ValueError("window too small for ddof")
    if n < w:
        return out
    mean = rolling_sum(x, w)[w - 1 :] / w
    acc = np.zeros(n - w + 1)
    for j in range(w):
        d = x[w - 1 - j : n - j] - mean
        acc += d * d
    out[w - 1 :] = np.sqrt(acc / (w - ddof))
    return out


def rolling_max(x: np.ndarray, w: int) -> np.ndarray:
    n = len(x)
    out = np.full(n, np.nan)
    if n < w:
        return out
    acc = x[w - 1 :].copy()
    for j in range(1, w):
        acc = np.maximum(acc, x[w - 1 - j : n - j])  # np.maximum propagates NaN
    out[w - 1 :] = acc
    return out


def rolling_min(x: np.ndarray, w: int) -> np.ndarray:
    n = len(x)
    out = np.full(n, np.nan)
    if n < w:
        return out
    acc = x[w - 1 :].copy()
    for j in range(1, w):
        acc = np.minimum(acc, x[w - 1 - j : n - j])
    out[w - 1 :] = acc
    return out


def rolling_nan_zscore(x: np.ndarray, w: int, min_count: int) -> np.ndarray:
    """Z-score of ``x[i]`` against the trailing window ``x[i-w+1 .. i]``, ignoring NaNs in the window.

    NaN if ``x[i]`` is NaN, fewer than ``min_count`` window values are valid, or the window has no spread.
    """
    n = len(x)
    out = np.full(n, np.nan)
    if n < w:
        return out
    valid = np.isfinite(x)
    xs = np.where(valid, x, 0.0)
    m = n - w + 1
    cnt = np.zeros(m)
    s = np.zeros(m)
    for j in range(w):
        cnt += valid[w - 1 - j : n - j]
        s += xs[w - 1 - j : n - j]
    with np.errstate(all="ignore"):
        mean = s / cnt
        acc = np.zeros(m)
        for j in range(w):
            seg = slice(w - 1 - j, n - j)
            d = np.where(valid[seg], xs[seg] - mean, 0.0)
            acc += d * d
        std = np.sqrt(acc / cnt)
        z = (x[w - 1 :] - mean) / std
    ok = valid[w - 1 :] & (cnt >= min_count) & (std > 0)
    out[w - 1 :] = np.where(ok, z, np.nan)
    return finite_or_nan(out)


# --- recursive indicators -------------------------------------------------------------------------


def ema(x: np.ndarray, span: int, min_count: int = 1) -> np.ndarray:
    """Exponential moving average, ``alpha = 2 / (span + 1)``, seeded with the first valid value.

    Emits a value once ``min_count`` consecutive valid inputs have been seen; a NaN resets the state.
    """
    if span < 1:
        raise ValueError("span must be >= 1")
    alpha = 2.0 / (span + 1.0)
    out = [_NAN] * len(x)
    state = _NAN
    count = 0
    for i, v in enumerate(x.tolist()):
        if not math.isfinite(v):
            count = 0
            continue
        count += 1
        state = v if count == 1 else alpha * v + (1.0 - alpha) * state
        if count >= min_count:
            out[i] = state
    return np.array(out)


def wilder_rma(x: np.ndarray, period: int, min_count: int | None = None) -> np.ndarray:
    """Wilder's smoothing: seeded with the SMA of the first ``period`` valid values, then
    ``rma = (rma_prev * (period - 1) + x) / period``. Emits after ``max(period, min_count)`` valid inputs."""
    if period < 1:
        raise ValueError("period must be >= 1")
    need = max(period, min_count or 0)
    out = [_NAN] * len(x)
    state = _NAN
    count = 0
    seed = 0.0
    for i, v in enumerate(x.tolist()):
        if not math.isfinite(v):
            count = 0
            seed = 0.0
            continue
        count += 1
        if count <= period:
            seed += v
            if count == period:
                state = seed / period
        else:
            state = (state * (period - 1) + v) / period
        if count >= need:
            out[i] = state
    return np.array(out)


# --- indicators -----------------------------------------------------------------------------------


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev_close = shift(close, 1)
    return np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int, min_count: int | None = None) -> np.ndarray:
    return wilder_rma(true_range(high, low, close), period, min_count)


def rsi(close: np.ndarray, period: int, min_count: int | None = None) -> np.ndarray:
    """Wilder RSI in [0, 100]. No losses and no gains => 50; no losses => 100."""
    diff = close - shift(close, 1)
    avg_gain = wilder_rma(np.maximum(diff, 0.0), period, min_count)
    avg_loss = wilder_rma(np.maximum(-diff, 0.0), period, min_count)
    with np.errstate(all="ignore"):
        rs = avg_gain / avg_loss
        value = 100.0 - 100.0 / (1.0 + rs)
    value = np.where(avg_loss == 0.0, np.where(avg_gain == 0.0, 50.0, 100.0), value)
    return np.where(np.isfinite(avg_gain) & np.isfinite(avg_loss), value, np.nan)


def adx(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int, min_count: int | None = None
) -> np.ndarray:
    """Wilder ADX. DI values are smoothed from the first ``period`` bars; ADX itself is masked until
    ``min_count`` DX values have been seen."""
    up = high - shift(high, 1)
    down = shift(low, 1) - low
    plus_dm = np.where(np.isnan(up) | np.isnan(down), np.nan, np.where((up > down) & (up > 0), up, 0.0))
    minus_dm = np.where(np.isnan(up) | np.isnan(down), np.nan, np.where((down > up) & (down > 0), down, 0.0))
    tr = true_range(high, low, close)
    s_tr = wilder_rma(tr, period)
    s_plus = wilder_rma(plus_dm, period)
    s_minus = wilder_rma(minus_dm, period)
    with np.errstate(all="ignore"):
        plus_di = 100.0 * s_plus / s_tr
        minus_di = 100.0 * s_minus / s_tr
        total = plus_di + minus_di
        dx = np.where(total == 0.0, 0.0, 100.0 * np.abs(plus_di - minus_di) / total)
    dx = np.where(np.isfinite(plus_di) & np.isfinite(minus_di), dx, np.nan)
    return finite_or_nan(wilder_rma(dx, period, min_count))


def macd_histogram(
    close: np.ndarray, fast: int, slow: int, signal: int, min_fast: int, min_slow: int, min_signal: int
) -> np.ndarray:
    macd = ema(close, fast, min_fast) - ema(close, slow, min_slow)
    return macd - ema(macd, signal, min_signal)


def bollinger(close: np.ndarray, window: int, k: float) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(z, width)``: z = (close - SMA) / std and width = 2 k std / SMA (population std)."""
    sma = rolling_mean(close, window)
    std = rolling_std(close, window, ddof=0)
    return safe_divide(close - sma, std), safe_divide(2.0 * k * std, sma)


def donchian_position(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int) -> np.ndarray:
    """Where the close sits in the trailing high/low channel: 0 = at the low, 1 = at the high."""
    hi = rolling_max(high, window)
    lo = rolling_min(low, window)
    return safe_divide(close - lo, hi - lo)


def parkinson_vol(high: np.ndarray, low: np.ndarray, window: int) -> np.ndarray:
    """Parkinson range-based volatility per bar: sqrt(mean(ln(h/l)^2) / (4 ln 2))."""
    hl = log_ratio(high, low)
    return np.sqrt(rolling_sum(hl * hl, window) / (window * 4.0 * math.log(2.0)))

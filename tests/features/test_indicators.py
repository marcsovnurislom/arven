"""Indicator primitives: hand-computed cases and independent naive-loop references."""

import math

import numpy as np
import pytest

from arven.features import indicators as ind

nan = float("nan")


def eq(actual, expected, tol=1e-12):
    actual, expected = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    assert actual.shape == expected.shape
    both_nan = np.isnan(actual) & np.isnan(expected)
    assert np.array_equal(np.isnan(actual), np.isnan(expected)), f"NaN pattern differs: {actual} vs {expected}"
    np.testing.assert_allclose(actual[~both_nan], expected[~both_nan], rtol=tol, atol=tol)


def random_walk(n=300, seed=5):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    return high, low, close


# --- primitives ---------------------------------------------------------------------------------


def test_shift_is_a_lag_and_rejects_negative():
    eq(ind.shift(np.array([1.0, 2.0, 3.0, 4.0]), 2), [nan, nan, 1.0, 2.0])
    eq(ind.shift(np.array([1.0, 2.0]), 5), [nan, nan])
    with pytest.raises(ValueError):
        ind.shift(np.array([1.0]), -1)


def test_log_ratio_and_divide_never_return_inf():
    eq(ind.log_ratio(np.array([1.0, 0.0, -1.0, 2.0]), np.array([1.0, 1.0, 1.0, 1.0])), [0.0, nan, nan, math.log(2)])
    eq(ind.safe_divide(np.array([1.0, 0.0, 1.0]), np.array([2.0, 0.0, 0.0])), [0.5, nan, nan])


def test_log_return_hand_case():
    eq(ind.log_return(np.array([100.0, 110.0, 99.0]), 1), [nan, math.log(1.1), math.log(0.9)])


@pytest.mark.parametrize("w", [1, 3, 7])
def test_rolling_sum_mean_std_max_min_match_naive(w):
    x = np.random.default_rng(1).normal(size=40)
    naive = lambda f: np.array([f(x[i - w + 1 : i + 1]) if i >= w - 1 else nan for i in range(len(x))])  # noqa: E731
    eq(ind.rolling_sum(x, w), naive(np.sum))
    eq(ind.rolling_mean(x, w), naive(np.mean))
    eq(ind.rolling_max(x, w), naive(np.max))
    eq(ind.rolling_min(x, w), naive(np.min))
    if w > 1:
        eq(ind.rolling_std(x, w, ddof=1), naive(lambda a: np.std(a, ddof=1)))
    eq(ind.rolling_std(x, w, ddof=0), naive(np.std))


def test_rolling_windows_propagate_nan_and_have_prefix_property():
    x = np.random.default_rng(2).normal(size=60)
    x[20] = nan
    for fn in (lambda a: ind.rolling_sum(a, 5), lambda a: ind.rolling_std(a, 5), lambda a: ind.rolling_max(a, 5)):
        full = fn(x)
        assert np.isnan(full[20:25]).all() and not np.isnan(full[25:]).any()
        for k in (10, 30, 59):
            np.testing.assert_array_equal(fn(x[: k + 1])[k], full[k])  # exact: value never depends on later data


def test_rolling_nan_zscore_matches_naive():
    rng = np.random.default_rng(3)
    x = rng.normal(size=50)
    x[[10, 11, 30]] = nan
    w, min_count = 8, 6
    expected = []
    for i in range(len(x)):
        if i < w - 1 or np.isnan(x[i]):
            expected.append(nan)
            continue
        win = x[i - w + 1 : i + 1]
        win = win[~np.isnan(win)]
        expected.append((x[i] - win.mean()) / win.std() if len(win) >= min_count and win.std() > 0 else nan)
    eq(ind.rolling_nan_zscore(x, w, min_count), expected)


# --- recursive ----------------------------------------------------------------------------------


def test_ema_hand_case_and_alpha():
    eq(ind.ema(np.array([1.0, 2.0, 3.0]), span=3), [1.0, 1.5, 2.25])  # alpha = 0.5


def test_ema_min_count_masks_warmup_and_nan_resets():
    x = np.array([1.0, 2.0, 3.0, nan, 4.0, 5.0, 6.0])
    out = ind.ema(x, span=3, min_count=2)
    eq(out, [nan, 1.5, 2.25, nan, nan, 4.5, 5.25])


def test_wilder_rma_hand_case():
    out = ind.wilder_rma(np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]), period=3)
    eq(out, [nan, nan, 2.0, 8 / 3, (8 / 3 * 2 + 5) / 3, ((8 / 3 * 2 + 5) / 3 * 2 + 6) / 3])


def test_wilder_rma_reset_after_nan_needs_new_seed():
    out = ind.wilder_rma(np.array([1.0, 2.0, 3.0, nan, 4.0, 5.0, 6.0]), period=3)
    eq(out, [nan, nan, 2.0, nan, nan, nan, 5.0])


def test_wilder_rma_min_count_extends_warmup():
    out = ind.wilder_rma(np.arange(1.0, 8.0), period=2, min_count=5)
    assert np.isnan(out[:4]).all() and not np.isnan(out[4:]).any()


# --- indicators ---------------------------------------------------------------------------------


def test_true_range_and_atr_hand_case():
    high, low, close = np.array([10.0, 12.0, 13.0]), np.array([8.0, 9.0, 11.0]), np.array([9.0, 11.0, 12.0])
    eq(ind.true_range(high, low, close), [nan, 3.0, 2.0])
    eq(ind.atr(high, low, close, 2), [nan, nan, 2.5])


def test_rsi_hand_cases():
    eq(ind.rsi(np.array([1.0, 2.0, 1.0, 2.0]), 2), [nan, nan, 50.0, 75.0])
    assert ind.rsi(np.arange(1.0, 20.0), 5)[-1] == 100.0  # no losses
    assert ind.rsi(np.full(20, 7.0), 5)[-1] == 50.0  # flat


def naive_rsi(close, p):
    out = [nan] * len(close)
    gains = [max(close[i] - close[i - 1], 0) for i in range(1, len(close))]
    losses = [max(close[i - 1] - close[i], 0) for i in range(1, len(close))]
    ag, al = sum(gains[:p]) / p, sum(losses[:p]) / p
    out[p] = 100 - 100 / (1 + ag / al)
    for j in range(p, len(gains)):
        ag, al = (ag * (p - 1) + gains[j]) / p, (al * (p - 1) + losses[j]) / p
        out[j + 1] = 100 - 100 / (1 + ag / al)
    return out


def test_rsi_matches_naive_reference():
    _, _, close = random_walk()
    eq(ind.rsi(close, 14), naive_rsi(list(close), 14))


def naive_adx(high, low, close, p):
    n = len(close)
    tr, pdm, mdm = [], [], []
    for i in range(1, n):
        tr.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
        up, down = high[i] - high[i - 1], low[i - 1] - low[i]
        pdm.append(up if up > down and up > 0 else 0.0)
        mdm.append(down if down > up and down > 0 else 0.0)
    s_tr, s_p, s_m = sum(tr[:p]), sum(pdm[:p]), sum(mdm[:p])  # Wilder's sum form
    dx = []
    for j in range(p - 1, len(tr)):
        if j >= p:
            s_tr, s_p, s_m = s_tr - s_tr / p + tr[j], s_p - s_p / p + pdm[j], s_m - s_m / p + mdm[j]
        pdi, mdi = 100 * s_p / s_tr, 100 * s_m / s_tr
        dx.append(0.0 if pdi + mdi == 0 else 100 * abs(pdi - mdi) / (pdi + mdi))
    out = [nan] * n
    adx = sum(dx[:p]) / p  # first DX is at bar p, so the ADX seed (mean of p DX values) is at bar 2p - 1
    out[2 * p - 1] = adx
    for k in range(p, len(dx)):
        adx = (adx * (p - 1) + dx[k]) / p
        out[p + k] = adx
    return out


def test_adx_matches_naive_reference_and_perfect_trend_is_100():
    high, low, close = random_walk()
    eq(ind.adx(high, low, close, 14), naive_adx(high, low, close, 14), tol=1e-9)
    up = np.arange(1.0, 60.0)
    assert ind.adx(up + 0.5, up - 0.5, up, 5)[-1] == pytest.approx(100.0)


def test_macd_histogram_matches_ema_definition():
    _, _, close = random_walk()
    macd = ind.ema(close, 12) - ind.ema(close, 26)
    eq(ind.macd_histogram(close, 12, 26, 9, 1, 1, 1), macd - ind.ema(macd, 9))


def test_bollinger_hand_case_and_zero_spread():
    z, width = ind.bollinger(np.array([1.0, 2.0, 3.0]), 3, 2.0)
    std = math.sqrt(2 / 3)
    eq(z, [nan, nan, 1.0 / std])
    eq(width, [nan, nan, 2 * 2.0 * std / 2.0])
    z, _ = ind.bollinger(np.full(5, 4.0), 3, 2.0)
    assert np.isnan(z).all()


def test_donchian_position_and_parkinson():
    high, low, close = np.array([2.0, 3.0, 4.0]), np.array([1.0, 1.5, 2.0]), np.array([1.5, 2.0, 4.0])
    eq(ind.donchian_position(high, low, close, 3), [nan, nan, (4.0 - 1.0) / (4.0 - 1.0)])
    eq(ind.donchian_position(high, low, np.array([1.5, 2.0, 2.5]), 3), [nan, nan, (2.5 - 1.0) / 3.0])
    hl = np.log(np.array([2.0, 3.0]) / np.array([1.0, 1.5]))
    expected = math.sqrt((hl**2).sum() / (2 * 4 * math.log(2)))
    eq(ind.parkinson_vol(np.array([2.0, 3.0]), np.array([1.0, 1.5]), 2), [nan, expected])


def test_indicators_are_prefix_causal():
    high, low, close = random_walk(120)
    funcs = {
        "ema": lambda h, l, c: ind.ema(c, 20, 30),
        "rsi": lambda h, l, c: ind.rsi(c, 14, 30),
        "atr": lambda h, l, c: ind.atr(h, l, c, 14, 30),
        "adx": lambda h, l, c: ind.adx(h, l, c, 14, 30),
        "macd": lambda h, l, c: ind.macd_histogram(c, 12, 26, 9, 30, 30, 30),
        "bb": lambda h, l, c: ind.bollinger(c, 20, 2.0)[0],
        "donchian": lambda h, l, c: ind.donchian_position(h, l, c, 24),
    }
    for name, fn in funcs.items():
        full = fn(high, low, close)
        for k in (50, 80, 119):
            part = fn(high[: k + 1], low[: k + 1], close[: k + 1])
            np.testing.assert_array_equal(part[k], full[k], err_msg=name)

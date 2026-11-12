"""Calibration: with no real effect, the test should call 'significant' about 5% of the time.

Uses the fast p-value routine directly (no interval building) on simulated weekly data:
a shared demand trend captured by one control, plus autocorrelated noise.
"""
import numpy as np

from impact_tool.conformal import _p_value


def gen(T0, h, eff, rng, rho=0.4):
    n = T0 + h
    d = np.cumsum(rng.normal(0, 0.03, n))
    e = np.zeros(n)
    for i in range(1, n):
        e[i] = rho * e[i - 1] + rng.normal(0, 0.04)
    x = d + rng.normal(0, 0.02, n)
    y = 0.2 + d + e
    y[T0:] += np.log1p(eff)
    return y, x[:, None]


def rate(T0, h, eff, reps, seed):
    rng = np.random.default_rng(seed)
    return np.mean([_p_value(*gen(T0, h, eff, rng), T0, h, 0.0, 0.0)[0] < 0.05 for _ in range(reps)])


def test_false_alarm_rate_near_5pct():
    for T0, h in [(20, 8), (52, 8), (52, 26)]:
        assert rate(T0, h, 0.0, 200, seed=T0 + h) <= 0.09


def test_detects_moderate_effect_with_a_year_of_history():
    assert rate(52, 8, 0.10, 100, seed=99) >= 0.6

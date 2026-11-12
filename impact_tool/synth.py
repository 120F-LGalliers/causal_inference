"""Blending control series into one 'comparison' line.

Plain English
-------------
Instead of asking a person to pick the single best control series, we let the
tool build a blend: "60% of series A + 40% of series B" (on a log scale, plus a
constant). It chooses the blend that best tracks the outcome *before* the change.

Two safety rails stop it from over-fitting:

* **Weights can't be negative.** A control can help predict the outcome or be
  ignored, but it can't be used "upside down". That keeps the blend sensible and
  explainable, the same idea as a synthetic control.
* **Ridge shrinkage.** Weights are pulled gently towards zero so the blend can't
  chase noise. How hard they're pulled is chosen by *backtesting*: we pretend the
  change happened at many earlier dates and pick the setting that forecast the
  following weeks most accurately.

Everything is done on logs, so a weight of 0.5 means "when the control rises 10%,
the outcome tends to rise about 5%".
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import nnls

LAMBDAS = (0.0, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0)   # ridge strengths tried (relative to data scale)


@dataclass
class Blend:
    intercept: float
    weights: np.ndarray          # one per control, >= 0
    lam: float

    def predict(self, X: np.ndarray | None) -> np.ndarray:
        if X is None or X.shape[1] == 0:
            n = 1 if X is None else X.shape[0]
            return np.full(n, self.intercept)
        return self.intercept + X @ self.weights


def fit_blend(y: np.ndarray, X: np.ndarray | None, lam: float = 0.0) -> Blend:
    """Non-negative ridge regression of y on X with a free intercept."""
    if X is None or X.shape[1] == 0:
        return Blend(float(np.mean(y)), np.zeros(0), lam)
    ym, Xm = y.mean(), X.mean(axis=0)
    yc, Xc = y - ym, X - Xm
    k = X.shape[1]
    scale = np.mean(np.sum(Xc ** 2, axis=0)) if np.any(Xc) else 1.0
    A = np.vstack([Xc, np.sqrt(lam * scale) * np.eye(k)]) if lam > 0 else Xc
    b = np.concatenate([yc, np.zeros(k)]) if lam > 0 else yc
    w, _ = nnls(A, b)
    return Blend(float(ym - Xm @ w), w, lam)


def backtest_errors(y: np.ndarray, X: np.ndarray | None, horizon: int, lam: float = 0.0,
                    min_train: int = 12) -> np.ndarray:
    """Rolling-origin backtest of the *average gap over the next `horizon` weeks*.

    For every possible fake change point in the pre-period, fit on the weeks before it,
    forecast the next `horizon` weeks, and record the error in their average (log scale).
    This is exactly the quantity the real analysis estimates, so the spread of these
    errors is an honest measure of how wrong the comparison line tends to be.
    """
    n = len(y)
    errs = []
    for origin in range(min_train, n - horizon + 1):
        Xtr = None if X is None else X[:origin]
        Xte = None if X is None else X[origin:origin + horizon]
        b = fit_blend(y[:origin], Xtr, lam)
        pred = b.predict(Xte) if Xte is not None else np.full(horizon, b.intercept)
        errs.append(float(np.mean(y[origin:origin + horizon] - pred)))
    return np.asarray(errs)


def choose_lambda(y: np.ndarray, X: np.ndarray | None, horizon: int = 8) -> float:
    """Pick the ridge strength with the smallest backtest error."""
    if X is None or X.shape[1] == 0:
        return 0.0
    h = max(2, min(horizon, len(y) // 4))
    best, best_err = 0.0, np.inf
    for lam in LAMBDAS:
        e = backtest_errors(y, X, h, lam)
        if len(e) == 0:
            return 0.0
        rmse = float(np.sqrt(np.mean(e ** 2)))
        if rmse < best_err - 1e-12:
            best, best_err = lam, rmse
    return best

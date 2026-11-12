"""Structural time-series impact model, placebo battery, detectable effect and verdict.

Method (CausalImpact-style):
  * Work on log(outcome) or log(outcome / denominator), weekly.
  * Fit a local-level state-space model with log(controls) as regressors on the
    pre-period only.
  * Simulate thousands of post-period paths from the end of the pre-period using
    the observed controls. These are the counterfactual: what would have
    happened without the change.
  * Effect = observed mean / counterfactual mean - 1, with intervals taken from
    the simulated paths.
  * Placebos re-run the whole thing on fake change dates inside the pre-period.
    If the model "finds" effects there, its real-date result can't be trusted.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.structural import UnobservedComponents

from .data import Spec, change_weeks, excluded_mask

MIN_PRE_WEEKS = 12          # real analysis
MIN_PLACEBO_PRE_WEEKS = 8   # placebo fits (pre-periods are often short)
MIN_PLACEBO_WINDOW = 4


@dataclass
class WindowEffect:
    label: str
    weeks: int
    observed: float
    predicted: float
    effect: float
    lo: float
    hi: float
    p_positive: float
    abs_effect: float | None = None   # counts only: observed - predicted, summed

    @property
    def significant(self) -> bool:
        return self.lo > 0 or self.hi < 0


@dataclass
class ImpactResult:
    weekly: pd.DataFrame              # observed, predicted, lo, hi, period
    windows: list[WindowEffect]
    n_pre: int
    n_post: int
    coefs: dict[str, float]
    pre_resid_sd: float
    null_halfwidth: dict[str, tuple[float, float]]  # (smallest detectable fall, smallest detectable rise)
    transition_week: pd.Timestamp | None
    first_post_week: pd.Timestamp


@dataclass
class PlaceboResult:
    date: pd.Timestamp
    effect: float
    lo: float
    hi: float

    @property
    def significant(self) -> bool:
        return self.lo > 0 or self.hi < 0


@dataclass
class Verdict:
    label: str            # Held / Faded / Reversed / Inconclusive / Unreliable / Changed
    colour: str           # green / amber / red / grey
    headline: str
    details: list[str] = field(default_factory=list)


def _fit(y: np.ndarray, X: np.ndarray | None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mod = UnobservedComponents(y, level="llevel", exog=X)
        return mod.fit(disp=False, maxiter=500)


def _simulate(res, X_post: np.ndarray | None, steps: int, n: int, seed: int,
              param_draws: int = 40) -> np.ndarray:
    """Simulate counterfactual paths, including uncertainty in the fitted parameters.

    Ignoring parameter uncertainty (e.g. how strongly the outcome follows the
    control) makes intervals too narrow, especially with short pre-periods, which
    shows up as false positives on placebo dates.
    """
    rng = np.random.default_rng(seed)
    np.random.seed(seed)
    names = list(res.model.param_names)
    var_idx = [i for i, nme in enumerate(names) if nme.startswith("sigma2")]
    try:
        cov = np.asarray(res.cov_params())
        ok = bool(np.all(np.isfinite(cov)) and np.all(np.diag(cov) >= 0))
    except Exception:  # noqa: BLE001
        ok = False
    draws = param_draws if ok else 1
    per = max(1, n // draws)
    out = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for k in range(draws):
            if k > 0:
                p = rng.multivariate_normal(np.asarray(res.params), cov, method="svd")
                p[var_idx] = np.maximum(np.abs(p[var_idx]), 1e-10)
                r_k = res.model.smooth(p)
            else:
                r_k = res
            s = r_k.simulate(steps, anchor="end", repetitions=per if ok else n, exog=X_post)
            out.append(np.asarray(s).reshape(steps, -1))
    return np.exp(np.concatenate(out, axis=1))   # weeks x reps, natural scale


def _split(frame: pd.DataFrame, spec: Spec, change_date, end=None):
    """Pre and post frames for a given change date (real or placebo)."""
    f = frame if end is None else frame[frame.index < end]
    trans, first_post = change_weeks(f.index, change_date)
    pre_end = trans if trans is not None else first_post
    keep = ~excluded_mask(f.index, spec.exclude)
    cols = ["y"] + spec.controls
    pre = f[(f.index < pre_end) & keep][cols + ["y_raw"]].dropna(subset=cols)
    post = f[f.index >= first_post][cols + ["y_raw"]].dropna(subset=cols)
    return pre, post, trans, first_post


def _effect(obs: np.ndarray, sims: np.ndarray, label: str, is_count: bool) -> WindowEffect:
    sim_means = sims.mean(axis=0)
    eff = obs.mean() / sim_means - 1
    abs_eff = float(obs.sum() - np.median(sims.sum(axis=0))) if is_count else None
    return WindowEffect(label=label, weeks=len(obs), observed=float(obs.mean()),
                        predicted=float(np.median(sim_means)), effect=float(np.median(eff)),
                        lo=float(np.percentile(eff, 2.5)), hi=float(np.percentile(eff, 97.5)),
                        p_positive=float((eff > 0).mean()), abs_effect=abs_eff)


def run_impact(frame: pd.DataFrame, spec: Spec, horizons=(8, 26), n_sims: int = 3000,
               seed: int = 7) -> ImpactResult:
    pre, post, trans, first_post = _split(frame, spec, spec.change_date)
    if len(pre) < MIN_PRE_WEEKS:
        raise ValueError(f"Only {len(pre)} usable pre-period weeks; at least {MIN_PRE_WEEKS} are needed.")
    if len(post) < 2:
        raise ValueError("Fewer than 2 post-period weeks of data.")
    Xpre = pre[spec.controls].values if spec.controls else None
    Xpost = post[spec.controls].values if spec.controls else None
    res = _fit(pre["y"].values, Xpre)
    sims = _simulate(res, Xpost, len(post), n_sims, seed)
    obs = post["y_raw"].values
    is_count = not spec.is_rate

    windows = []
    for h in horizons:
        if len(post) >= h:
            windows.append(_effect(obs[:h], sims[:h], f"First {h} weeks", is_count))
    windows.append(_effect(obs, sims, f"All {len(post)} weeks", is_count))

    # detectable effect: spread of the effect if reality matched the median forecast
    null_hw = {}
    for w in windows:
        s = sims[: w.weeks]
        m = s.mean(axis=0)
        e = np.median(m) / m - 1
        # smallest true change d that would make the interval exclude zero
        fall = 1 - 1 / (1 + np.percentile(e, 97.5))
        rise = 1 / (1 + np.percentile(e, 2.5)) - 1
        null_hw[w.label] = (float(abs(fall)), float(abs(rise)))

    weekly = pd.DataFrame(index=frame.index)
    weekly["observed"] = frame["y_raw"]
    weekly["predicted"] = np.nan
    weekly["lo"] = np.nan
    weekly["hi"] = np.nan
    weekly.loc[post.index, "predicted"] = np.median(sims, axis=1)
    weekly.loc[post.index, "lo"] = np.percentile(sims, 2.5, axis=1)
    weekly.loc[post.index, "hi"] = np.percentile(sims, 97.5, axis=1)
    # in-sample fit for the pre-period (one-step-ahead predictions)
    fitted = np.exp(res.fittedvalues)
    fitted[0] = np.nan
    weekly.loc[pre.index, "predicted"] = fitted
    period = pd.Series("excluded / gap", index=frame.index)
    period[pre.index] = "pre"
    period[post.index] = "post"
    if trans is not None:
        period[trans] = "transition"
    weekly["period"] = period

    exog_names = spec.controls
    coefs = {n: float(v) for n, v in zip(exog_names, res.params[-len(exog_names):])} if exog_names else {}
    return ImpactResult(weekly=weekly, windows=windows, n_pre=len(pre), n_post=len(post), coefs=coefs,
                        pre_resid_sd=float(np.std(res.resid[1:])), null_halfwidth=null_hw,
                        transition_week=trans, first_post_week=first_post)


def placebo_dates(frame: pd.DataFrame, spec: Spec, window: int = 8, n: int = 6) -> list[pd.Timestamp]:
    """Evenly spaced fake change dates with enough pre-period before and window after."""
    pre, _, trans, first_post = _split(frame, spec, spec.change_date)
    real_start = trans if trans is not None else first_post
    candidates = [w for w in pre.index
                  if (pre.index < w).sum() >= MIN_PLACEBO_PRE_WEEKS
                  and (w + pd.Timedelta(weeks=MIN_PLACEBO_WINDOW)) <= real_start]
    if not candidates:
        return []
    idx = np.linspace(0, len(candidates) - 1, min(n, len(candidates))).round().astype(int)
    return [candidates[i] for i in sorted(set(idx))]


def run_placebos(frame: pd.DataFrame, spec: Spec, window: int = 8, n: int = 6,
                 n_sims: int = 1500, seed: int = 11) -> list[PlaceboResult]:
    out = []
    pre_all, _, trans, first_post = _split(frame, spec, spec.change_date)
    real_start = trans if trans is not None else first_post
    for d in placebo_dates(frame, spec, window, n):
        pspec = Spec(spec.outcome, spec.denominator, spec.controls, d, spec.exclude, spec.controls_as_rate)
        pre, post, _, _ = _split(frame, pspec, d, end=real_start)
        post = post.iloc[:window]
        if len(pre) < MIN_PLACEBO_PRE_WEEKS or len(post) < MIN_PLACEBO_WINDOW:
            continue
        res = _fit(pre["y"].values, pre[spec.controls].values if spec.controls else None)
        sims = _simulate(res, post[spec.controls].values if spec.controls else None, len(post), n_sims, seed)
        e = _effect(post["y_raw"].values, sims, "placebo", False)
        out.append(PlaceboResult(d, e.effect, e.lo, e.hi))
    return out


def detectable_effect(result: ImpactResult, placebos: list[PlaceboResult], label: str,
                      direction: float | None = None) -> dict:
    """Smallest effect the analysis could reliably distinguish from noise.

    direction: sign of the expected effect (negative = a fall). If None, the
    average of the two directions is used.
    """
    fall, rise = result.null_halfwidth.get(label, (np.nan, np.nan))
    if direction is None or direction == 0:
        model_hw = (fall + rise) / 2
    else:
        model_hw = fall if direction < 0 else rise
    placebo_max = max((abs(p.effect) for p in placebos), default=np.nan)
    realistic = np.nanmax([model_hw, placebo_max])
    return {"model": model_hw, "placebo": placebo_max, "realistic": float(realistic)}


def make_verdict(window: WindowEffect, placebos: list[PlaceboResult], mde: float,
                 expected: float | None, early: WindowEffect | None = None) -> Verdict:
    """Translate the numbers into a plain-English verdict.

    expected: the effect we'd expect to see in this outcome if the test result held
    (test lift x share of the outcome exposed). None if no test result is known.
    """
    n_fp = sum(p.significant for p in placebos)
    det = [f"Primary window: {window.label.lower()}, effect {window.effect:+.1%} "
           f"(95% interval {window.lo:+.1%} to {window.hi:+.1%}).",
           f"Placebo checks: {n_fp} of {len(placebos)} fake dates showed a 'significant' effect.",
           f"Smallest reliably detectable effect: about ±{mde:.0%}."]
    if expected is not None:
        det.append(f"Effect expected if the test result held: {expected:+.1%}.")

    if len(placebos) < 3:
        return Verdict("Unreliable", "red", "Not enough pre-period to run placebo checks, so the result can't be validated.", det)
    if n_fp >= 2 or (n_fp / len(placebos)) > 0.25:
        return Verdict("Unreliable", "red",
                       "The model finds 'effects' on dates when nothing changed, so this result can't be trusted. "
                       "Try different control series or a cleaner outcome metric.", det)

    inside = lambda v: window.lo <= v <= window.hi
    if expected is None:
        if window.significant:
            return Verdict("Changed", "green" if window.effect > 0 else "amber",
                           f"The metric moved {window.effect:+.1%} after the change, beyond normal variation.", det)
        return Verdict("Inconclusive", "grey", "No change beyond normal variation was detected.", det)

    same_dir = np.sign(window.effect) == np.sign(expected)
    # Intervals widen the further we forecast, so a real, lasting effect can be clear
    # in the early weeks and only "consistent" later on. Treat that as held.
    if (early is not None and early is not window and not window.significant and early.significant
            and np.sign(early.effect) == np.sign(expected) and same_dir
            and early.lo <= window.effect <= early.hi):
        det.append(f"Early window ({early.label.lower()}): {early.effect:+.1%} "
                   f"(95% interval {early.lo:+.1%} to {early.hi:+.1%}).")
        return Verdict("Held", "green",
                       f"The effect is clear in the {early.label.lower()} after go-live ({early.effect:+.1%}). "
                       f"Over the {window.label.lower()} the estimate is similar ({window.effect:+.1%}) but less "
                       "certain, because the model's forecast widens the further it looks ahead.", det)
    if abs(expected) < mde and not window.significant:
        return Verdict("Inconclusive", "grey",
                       f"The expected effect ({expected:+.1%}) is smaller than this data can detect (±{mde:.0%}). "
                       "The result is consistent with the effect holding and with it having faded. "
                       "A holdout group is the only reliable way to check effects this small.", det)
    if window.significant and same_dir:
        tail = " and is consistent with the test result." if inside(expected) else \
            (" and is larger than the test result." if abs(window.effect) > abs(expected) else
             " but is smaller than the test result.")
        return Verdict("Held", "green", f"The effect is still visible after go-live ({window.effect:+.1%})" + tail, det)
    if window.significant and not same_dir:
        return Verdict("Reversed", "red",
                       f"The metric moved in the opposite direction to the test result ({window.effect:+.1%}).", det)
    if not inside(expected):
        return Verdict("Faded", "amber",
                       f"No significant change, and the interval rules out the test's effect size ({expected:+.1%}). "
                       "The benefit appears to have faded or not carried over to the built version.", det)
    return Verdict("Inconclusive", "grey",
                   "No significant change, but the interval is wide enough to include the test's effect.", det)

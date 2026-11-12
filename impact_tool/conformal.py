"""v2 engine: blended controls, a steady baseline, and permutation (conformal) inference.

Plain English
-------------
1. **Comparison line.** Blend the control series into one line that tracked the
   outcome closely before the change (see synth.py).
2. **The gap.** Each week, measure the gap between the outcome and the comparison
   line. Before the change the gap should wobble around zero.
3. **The effect.** The average gap after the change is the estimated effect.
4. **Is it real?** Compare the post-change average gap with the average gap over
   *every other stretch of the same number of weeks* in the data. If the real
   stretch stands out from almost all of them, the effect is real. This is the
   p-value: the share of stretches that look at least as extreme.
5. **Range of plausible effects (interval).** Repeat step 4 assuming different true
   effects (e.g. "suppose it was really -10%") and keep every value the data
   can't rule out.

Why this is more reliable than v1
---------------------------------
* The p-value comes from the data's own week-to-week wobble, not from model
  assumptions, so false alarms stay at about the 5% we ask for (method of
  Chernozhukov, Wüthrich & Zhu, 2021, "An exact and robust conformal inference
  method for counterfactual and synthetic controls", JASA).
* There's no random simulation, so the same data always gives the same answer.
* The baseline doesn't drift, so 26-week windows stay informative.

The key assumption: before the change, the gap behaves the same way throughout
(no steady drift). The tool checks this and warns if it's violated.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from .data import Spec, change_weeks, excluded_mask
from .synth import Blend, backtest_errors, choose_lambda, fit_blend

ALPHA = 0.05
MIN_PRE = 12
GRID = np.linspace(-1.6, 1.6, 641)   # log effects tested when building the interval (-80% .. +395%)
MDE_FACTOR = 1.43                     # (1.96 + 0.84) / 1.96: 80% power at the 5% level


# ---------------------------------------------------------------- data prep
@dataclass
class Prepared:
    index: pd.DatetimeIndex          # weeks used (pre then post), excluded/transition weeks removed
    y: np.ndarray                    # log outcome (or log rate)
    X: np.ndarray                    # log controls (n x k), k may be 0
    n_pre: int
    n_post: int
    controls: list[str]
    dropped: pd.DataFrame            # week, reason
    transition_week: pd.Timestamp | None
    first_post_week: pd.Timestamp
    frame: pd.DataFrame              # full model frame (for charts)


def prepare(frame: pd.DataFrame, spec: Spec) -> Prepared:
    trans, first_post = change_weeks(frame.index, spec.change_date)
    pre_end = trans if trans is not None else first_post
    excl = excluded_mask(frame.index, spec.exclude)
    cols = ["y"] + spec.controls
    bad = frame[cols].isna().any(axis=1)
    dropped = []
    for w in frame.index:
        if trans is not None and w == trans:
            dropped.append((w, "transition week (change went live mid-week)"))
        elif excl[frame.index.get_loc(w)] and w < pre_end:
            dropped.append((w, "excluded by you (test period / known issue)"))
        elif bad[w]:
            dropped.append((w, "missing or zero value in the outcome or a control"))
    pre_m = (frame.index < pre_end) & ~excl & ~bad
    post_m = (frame.index >= first_post) & ~bad
    pre, post = frame[pre_m], frame[post_m]
    both = pd.concat([pre, post])
    k = len(spec.controls)
    X = both[spec.controls].values if k else np.zeros((len(both), 0))
    return Prepared(both.index, both["y"].values, X, len(pre), len(post), list(spec.controls),
                    pd.DataFrame(dropped, columns=["week", "reason"]), trans, first_post, frame)


# ---------------------------------------------------------------- results
@dataclass
class WindowResult:
    label: str
    weeks: int
    effect: float            # relative effect, e.g. -0.25
    lo: float                # interval (relative); nan if unbounded on that side
    hi: float
    p_value: float
    observed: float          # average outcome (natural units) in the window
    predicted: float         # average comparison-line prediction (natural units)
    halfwidth: float         # half the width of the interval, on the log scale
    mde_rise: float          # smallest rise we'd detect ~80% of the time
    mde_fall: float          # smallest fall we'd detect ~80% of the time
    abs_effect: float | None = None
    n_total: int = 0
    lo_unbounded: bool = False
    hi_unbounded: bool = False
    n_pre: int = 0
    perm_means: np.ndarray | None = None   # signed average gap of every stretch under 'no effect' (element 0 = post)

    @property
    def length_ok(self) -> bool:
        """Windows longer than half the history can't be tested well (see docs/validation.md)."""
        return self.weeks <= self.n_pre / 2

    @property
    def significant(self) -> bool:
        return self.p_value < ALPHA

    def mde(self, direction: float | None = None) -> float:
        if direction is None or direction == 0:
            return (self.mde_rise + self.mde_fall) / 2
        return self.mde_fall if direction < 0 else self.mde_rise


@dataclass
class Diagnostics:
    backtest_error: float            # typical error of an 8-week (or window) average, relative
    backtest_error_no_controls: float
    fit_r2: float                    # share of weekly variation explained before the change
    drift_per_year: float            # trend in the pre-period gap (relative per 52 weeks)
    drift_p: float
    drift_flag: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class Analysis:
    prep: Prepared
    blend: Blend
    windows: list[WindowResult]
    primary: WindowResult
    weekly: pd.DataFrame
    diagnostics: Diagnostics
    block_history: pd.DataFrame      # start week, average gap, is_post (primary window length)
    leave_one_out: pd.DataFrame


@dataclass
class Verdict:
    label: str
    colour: str
    headline: str
    details: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- core maths
def _block_means(u: np.ndarray, start: int, h: int) -> np.ndarray:
    """Average of u over every circular block of length h; element 0 starts at `start`."""
    T = len(u)
    cs = np.concatenate([[0.0], np.cumsum(np.concatenate([u, u]))])
    starts = (start + np.arange(T)) % T
    return (cs[starts + h] - cs[starts]) / h


def _p_value(y: np.ndarray, X: np.ndarray, T0: int, h: int, theta: float, lam: float,
             signed: bool = False) -> tuple[float, np.ndarray]:
    ya = y.copy()
    ya[T0:] -= theta                      # remove the hypothesised effect
    b = fit_blend(ya, X if X.shape[1] else None, lam)   # fit on ALL weeks under the hypothesis
    u = ya - b.predict(X if X.shape[1] else np.zeros((len(ya), 0)))
    m = _block_means(u, T0, h)
    s = np.abs(m)
    return float(np.mean(s >= s[0] - 1e-12)), (m if signed else s)


def run_window(prep: Prepared, h: int, lam: float, label: str, is_count: bool) -> WindowResult:
    T0 = prep.n_pre
    y, X = prep.y[:T0 + h], prep.X[:T0 + h]
    Xn = X if X.shape[1] else None
    blend = fit_blend(y[:T0], None if Xn is None else Xn[:T0], lam)
    pred = blend.predict(X if X.shape[1] else np.zeros((len(y), 0)))
    gap = y - pred
    theta = float(np.mean(gap[T0:]))

    p0, perm = _p_value(y, X, T0, h, 0.0, lam, signed=True)
    grid = theta + GRID
    ps = np.array([_p_value(y, X, T0, h, t, lam)[0] for t in grid])
    keep = grid[ps > ALPHA]
    lo_l, hi_l = (keep.min(), keep.max()) if len(keep) else (theta, theta)
    hw = float((hi_l - lo_l) / 2)
    # An effect about 1.4x the interval half-width is detected ~80% of the time
    # (1.96 + 0.84 standard errors vs 1.96). Below that, a miss is likely.
    mde_log = MDE_FACTOR * hw

    obs_nat, pred_nat = np.exp(y[T0:]), np.exp(pred[T0:])
    return WindowResult(
        label=label, weeks=h, effect=float(np.exp(theta) - 1),
        lo=float(np.exp(lo_l) - 1), hi=float(np.exp(hi_l) - 1), p_value=p0,
        observed=float(obs_nat.mean()), predicted=float(pred_nat.mean()), halfwidth=hw,
        mde_rise=float(np.exp(mde_log) - 1), mde_fall=float(1 - np.exp(-mde_log)),
        abs_effect=float(obs_nat.sum() - pred_nat.sum()) if is_count else None,
        n_total=len(y), lo_unbounded=bool(np.isclose(lo_l, grid.min())),
        hi_unbounded=bool(np.isclose(hi_l, grid.max())), n_pre=T0, perm_means=perm)


def suggest_window(n_pre: int, n_post: int) -> int:
    """Longest standard window that is no more than half the history and has data."""
    ok = [h for h in (8, 13, 26, 52) if h <= n_pre / 2 and h <= n_post]
    return ok[-1] if ok else min(8, n_post)


def analyse(frame: pd.DataFrame, spec: Spec, primary: int | None = None) -> Analysis:
    """Run the full v2 analysis. `primary` is the window (weeks) used for the verdict;
    if None, suggest_window() picks one. Results are also given for the first 8 weeks
    and for all weeks after the change."""
    prep = prepare(frame, spec)
    if prep.n_pre < MIN_PRE:
        raise ValueError(f"Only {prep.n_pre} usable weeks before the change; at least {MIN_PRE} are needed "
                         "(a year is better).")
    if prep.n_post < 2:
        raise ValueError("Fewer than 2 usable weeks after the change.")
    T0 = prep.n_pre
    Xn = prep.X if prep.X.shape[1] else None
    lam = choose_lambda(prep.y[:T0], None if Xn is None else Xn[:T0], horizon=8)
    blend = fit_blend(prep.y[:T0], None if Xn is None else Xn[:T0], lam)
    is_count = not spec.is_rate

    primary = min(primary or suggest_window(prep.n_pre, prep.n_post), prep.n_post)
    hs = sorted({h for h in (8, primary) if h <= prep.n_post} | {prep.n_post})
    windows = [run_window(prep, h, lam, f"All {h} weeks" if h == prep.n_post else f"First {h} weeks", is_count)
               for h in hs]
    prim = next(w for w in windows if w.weeks == primary)

    # weekly series for charts (all weeks with usable controls, incl. excluded ones)
    f = prep.frame
    Xall = f[spec.controls].values if spec.controls else np.zeros((len(f), 0))
    pred_all = blend.predict(Xall)
    weekly = pd.DataFrame(index=f.index)
    weekly["observed"] = f["y_raw"]
    weekly["predicted"] = np.exp(pred_all)
    weekly["gap"] = np.exp(f["y"].values - pred_all) - 1
    period = pd.Series("left out", index=f.index)
    period[prep.index[:T0]] = "before"
    period[prep.index[T0:]] = "after"
    weekly["period"] = period

    # diagnostics
    h_bt = min(8, max(2, T0 // 4))
    e = backtest_errors(prep.y[:T0], None if Xn is None else Xn[:T0], h_bt, lam)
    e0 = backtest_errors(prep.y[:T0], None, h_bt, 0.0)
    rms = lambda a: float(np.exp(np.sqrt(np.mean(a ** 2))) - 1) if len(a) else np.nan
    gap_pre = prep.y[:T0] - blend.predict(prep.X[:T0])
    var_y = np.var(prep.y[:T0])
    r2 = float(1 - np.var(gap_pre) / var_y) if var_y > 0 else np.nan
    t = np.arange(T0)
    slope, _, _, p_slope, _ = stats.linregress(t, gap_pre)
    drift_at_post = slope * (T0 + (prim.weeks - 1) / 2 - (T0 - 1) / 2)
    drift_flag = bool(p_slope < 0.05 and abs(drift_at_post) > prim.halfwidth / 2)
    notes = []
    if prep.n_pre + prep.n_post < 20:
        notes.append("Fewer than 20 weeks in total, so the test can't reach the usual 5% significance level.")
    if drift_flag:
        notes.append("Before the change, the outcome was steadily drifting away from the comparison line "
                     f"(about {np.exp(slope * 52) - 1:+.0%} a year). Part of any 'effect' could be that drift.")
    diag = Diagnostics(rms(e), rms(e0), r2, float(np.exp(slope * 52) - 1), float(p_slope), drift_flag, notes)

    # the permutation distribution behind the p-value, for the "is it unusual?" chart
    h = prim.weeks
    Tw = prep.n_pre + h
    starts = [(T0 + j) % Tw for j in range(Tw)]
    bh = pd.DataFrame({"start": [prep.index[i] for i in starts],
                       "avg_gap": np.exp(prim.perm_means) - 1,
                       "is_post": [j == 0 for j in range(Tw)]})

    # leave-one-out sensitivity on the primary window (point estimate only)
    loo = []
    for i, c in enumerate(spec.controls):
        keep_idx = [j for j in range(len(spec.controls)) if j != i]
        Xk = prep.X[:, keep_idx]
        b = fit_blend(prep.y[:T0], Xk[:T0] if keep_idx else None, lam)
        g = prep.y[T0:T0 + h] - b.predict(Xk[T0:T0 + h] if keep_idx else np.zeros((h, 0)))
        loo.append({"Control removed": c, f"Effect ({prim.label.lower()})": f"{np.exp(g.mean()) - 1:+.1%}"})
    return Analysis(prep, blend, windows, prim, weekly, diag, bh, pd.DataFrame(loo))


# ---------------------------------------------------------------- verdict
def make_verdict(w: WindowResult, diag: Diagnostics, expected: float | None) -> Verdict:
    """Plain-English verdict. expected = effect we'd expect if the test result held."""
    mde = w.mde(expected)
    lo_txt = "no lower limit" if w.lo_unbounded else f"{w.lo:+.1%}"
    hi_txt = "no upper limit" if w.hi_unbounded else f"{w.hi:+.1%}"
    det = [f"Primary window: {w.label.lower()}. Estimated effect {w.effect:+.1%}; "
           f"plausible range {lo_txt} to {hi_txt}; p-value {w.p_value:.3f}.",
           f"Smallest change this data could reliably detect here: about {mde:.0%}.",
           f"Comparison line accuracy before the change: typically within ±{diag.backtest_error:.0%} "
           f"over a few weeks (±{diag.backtest_error_no_controls:.0%} without controls)."]
    if expected is not None:
        det.append(f"Effect expected if the test result held: {expected:+.1%}.")
    if not w.length_ok:
        det.append(f"This window ({w.weeks} weeks) is more than half the history before the change ({w.n_pre} weeks), "
                   "so the test has little power. A 'no clear effect' result here means very little.")
    det += diag.notes

    if w.n_total < 20:
        return Verdict("Unreliable", "red", "There aren't enough weeks of data to test this properly. "
                       "Add more history before the change.", det)
    if diag.drift_flag and abs(np.log1p(diag.drift_per_year)) * (w.weeks / 52) > w.halfwidth:
        return Verdict("Unreliable", "red", "The outcome was already drifting away from the comparison line before "
                       "the change, by enough to explain the result. Try different control series.", det)
    inside = lambda v: (w.lo_unbounded or v >= w.lo) and (w.hi_unbounded or v <= w.hi)
    caution = " (but see the drift warning)" if diag.drift_flag else ""

    if expected is None:
        if w.significant:
            return Verdict("Changed", "green", f"The metric moved {w.effect:+.1%} after the change, more than "
                           f"normal week-to-week variation explains{caution}.", det)
        return Verdict("No clear change", "grey", "No change beyond normal week-to-week variation.", det)

    same = np.sign(w.effect) == np.sign(expected)
    if w.significant and same:
        if inside(expected):
            tail = ", in line with the test result"
        elif abs(w.effect) < abs(expected):
            tail = ", though smaller than the test result"
        else:
            tail = ", and larger than the test result"
        return Verdict("Held", "green", f"The effect is still there after go-live ({w.effect:+.1%}){tail}{caution}.", det)
    if w.significant and not same:
        return Verdict("Reversed", "red", f"The metric moved the opposite way to the test result ({w.effect:+.1%}){caution}.", det)
    if not inside(expected):
        return Verdict("Faded", "amber", f"No clear effect, and the data rules out an effect as big as the test's "
                       f"({expected:+.1%}). The benefit seems to have faded or not carried over to the built version.", det)
    if abs(expected) < mde:
        return Verdict("Inconclusive", "grey", f"The expected effect ({expected:+.1%}) is smaller than this data can "
                       f"detect (about {mde:.0%}). It may have held or faded; the data can't tell. A holdout group is "
                       "the reliable way to check effects this small.", det)
    return Verdict("Inconclusive", "grey", "No clear effect, but the plausible range is wide enough to include the "
                   "test's result. More weeks of data, or better controls, may settle it.", det)

"""Data checks that catch the commonest ways of feeding the tool the wrong data.

1. reconcile()        Does the uploaded outcome match the test's own control-group figure?
                      If not, you're probably measuring a different metric from the test.
2. denominator_jump() Did the denominator itself change when the change went live? If so,
                      the rate is distorted and the raw count should be checked too.
3. hidden_break()     Was there a sudden step in the gap between outcome and comparison line
                      *before* the change? That usually means a tracking or definition change.
4. coverage()         Do all series cover the same weeks?
5. placebo_check()    (with verdict adjustment) Did a metric the change couldn't affect also
                      'move' at the change date? Then something else happened that week.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .conformal import Analysis, Verdict, WindowResult, _p_value, analyse
from .data import Spec, excluded_mask, model_frame

UNITS = {
    "rate_pct": "A rate in % (e.g. 2.3 for 2.3% conversion)",
    "ratio": "A ratio (e.g. 0.023, or 1.4 items per order)",
    "weekly_count": "A weekly count for the control group (e.g. 1,250 orders a week)",
}


@dataclass
class Check:
    name: str
    status: str            # ok / warn / fail / skipped
    message: str
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------- 1. reconciliation
def reconcile(weekly: pd.DataFrame, outcome: str, denom: str | None, test_window, entered: float | None,
              unit: str, control_share: float = 0.5) -> Check:
    """Compare the outcome over the test weeks with the test's control-group figure."""
    name = "Matches the test's control group"
    if entered is None or entered <= 0:
        return Check(name, "skipped", "No control-group figure entered, so the export couldn't be checked against "
                                      "the test. The report will say so.")
    if not test_window:
        return Check(name, "skipped", "Enter the test dates in step 1 to check the export against the test.")
    a, b = pd.Timestamp(test_window[0]), pd.Timestamp(test_window[1])
    m = (weekly.index >= a) & (weekly.index + pd.Timedelta(days=6) <= b)
    if m.sum() == 0:
        m = excluded_mask(weekly.index, [(a, b)])
    w = weekly[m]
    if len(w) == 0 or w[outcome].isna().all():
        return Check(name, "warn", "Your data doesn't cover the test period, so it couldn't be checked against the test.")
    if unit in ("rate_pct", "ratio"):
        if not denom:
            return Check(name, "warn", "You entered a rate, but no denominator is selected, so the two can't be compared.")
        obs = w[outcome].sum() / w[denom].sum() * (100 if unit == "rate_pct" else 1)
    else:
        obs = w[outcome].mean() * control_share
    diff = obs / entered - 1
    fmt = (lambda v: f"{v:.3g}%") if unit == "rate_pct" else (lambda v: f"{v:,.4g}")
    det = {"test_weeks": int(len(w)), "observed": float(obs), "entered": float(entered), "difference": float(diff)}
    base = (f"Over the test weeks, your export gives **{fmt(obs)}**; the test's control group had **{fmt(entered)}** "
            f"({diff:+.0%}).")
    if abs(diff) <= 0.15:
        return Check(name, "ok", base + " Close enough: the export looks like the same metric as the test.", det)
    if abs(diff) <= 0.40:
        return Check(name, "warn", base + " That's a noticeable difference. Common reasons: the test only targeted part "
                     "of the traffic, the export counts visits where the test counted visitors, or the definitions differ "
                     "slightly. Check before relying on the result.", det)
    return Check(name, "fail", base + " That's a big difference, so you're probably not measuring the same thing as "
                 "the test. Check the metric definition, segments and report suite against the test's primary metric.", det)


# ---------------------------------------------------------------- 2. denominator
def denominator_jump(weekly: pd.DataFrame, spec: Spec, n_pre: int, post_weeks: int = 8) -> Check:
    """Did the denominator itself shift at the change date, beyond what the controls explain?

    Uses the same permutation test as the main analysis, with the control series (as raw
    counts) to soak up normal traffic swings. Without controls, ordinary traffic trends
    can trigger the warning, and the message says so.
    """
    name = "Denominator unaffected by the change"
    if not spec.denominator:
        return Check(name, "skipped", "No denominator used.")
    from .conformal import prepare
    from .synth import choose_lambda
    s = Spec(spec.denominator, None, list(spec.controls), spec.change_date, spec.exclude, False)
    prep = prepare(model_frame(weekly, s), s)
    h = min(post_weeks, prep.n_post)
    if prep.n_pre < 12 or h < 2:
        return Check(name, "skipped", "Not enough data to check the denominator.")
    T0 = prep.n_pre
    y, X = prep.y[:T0 + h], prep.X[:T0 + h]
    lam = choose_lambda(prep.y[:T0], prep.X[:T0] if X.shape[1] else None)
    p, _ = _p_value(y, X, T0, h, 0.0, lam)
    from .synth import fit_blend
    b = fit_blend(prep.y[:T0], prep.X[:T0] if X.shape[1] else None, lam)
    gap = y - b.predict(X if X.shape[1] else np.zeros((len(y), 0)))
    jump = float(np.exp(gap[T0:].mean()) - 1)
    det = {"jump": jump, "p_value": p}
    caveat = "" if spec.controls else (" (No control series were used, so an ordinary traffic trend could also "
                                       "trigger this.)")
    if p < 0.05:
        return Check(name, "warn", f"The denominator ({spec.denominator}) itself moved **{jump:+.0%}** when the change "
                     f"went live, more than the controls explain (p = {p:.3f}). If the change affected how many people "
                     "reached the denominator, the rate is distorted: re-run with the raw count (no denominator) and "
                     "compare. If something else explains it (e.g. a marketing campaign), the rate is fine." + caveat, det)
    return Check(name, "ok", f"The denominator didn't change noticeably at the change date ({jump:+.0%}, p = {p:.2f}).", det)


# ---------------------------------------------------------------- 3. hidden break
def _sup_t(g: np.ndarray, trim: int) -> tuple[float, int]:
    """Largest standardised step in mean, scanning every split point.

    The noise level is estimated within the two segments (after removing each side's
    mean), so a real step doesn't inflate the noise estimate and hide itself.
    """
    n = len(g)
    best, at = 0.0, trim
    cs, cs2 = np.cumsum(g), np.cumsum(g ** 2)
    for k in range(trim, n - trim):
        s1, s2 = cs[k - 1], cs[-1] - cs[k - 1]
        q1, q2 = cs2[k - 1], cs2[-1] - cs2[k - 1]
        m1, m2 = s1 / k, s2 / (n - k)
        ssr = (q1 - k * m1 ** 2) + (q2 - (n - k) * m2 ** 2)
        sd = np.sqrt(max(ssr, 1e-18) / (n - 2))
        t = abs(m2 - m1) / (sd * np.sqrt(1 / k + 1 / (n - k)))
        if t > best:
            best, at = t, k
    return best, at


def hidden_break(a: Analysis, reps: int = 999, alpha: float = 0.004, seed: int = 0) -> Check:
    """Scan the pre-change gap for a sudden step, with a moving-block bootstrap for significance.

    The gap is autocorrelated, so naive t-tests flag too often. Resampling blocks of
    consecutive weeks keeps the week-to-week correlation but removes any real step,
    giving an honest reference distribution. A strict level (0.4%) keeps false warnings
    to about 2-3% of checks; in simulation it caught roughly half of 15-30% steps, so a
    clean result isn't proof that there was no break.
    """
    name = "No hidden break before the change"
    T0 = a.prep.n_pre
    if T0 < 16:
        return Check(name, "skipped", "Too few weeks before the change to check for breaks.")
    g = a.prep.y[:T0] - a.blend.predict(a.prep.X[:T0])
    trim = max(4, int(0.15 * T0))
    stat, k = _sup_t(g, trim)
    rng = np.random.default_rng(seed)
    L = max(2, int(round(T0 ** (1 / 3))))
    # resample from the gap with the detected step removed: same noise, no step
    gc = g.copy()
    gc[:k] -= g[:k].mean()
    gc[k:] -= g[k:].mean()
    nb = int(np.ceil(T0 / L))
    null = np.empty(reps)
    for r in range(reps):
        starts = rng.integers(0, T0 - L + 1, nb)
        sample = np.concatenate([gc[s:s + L] for s in starts])[:T0]
        null[r] = _sup_t(sample, trim)[0]
    p = float((1 + np.sum(null >= stat)) / (reps + 1))
    step = float(np.exp(g[k:].mean() - g[:k].mean()) - 1)
    week = a.prep.index[k]
    det = {"p_value": p, "week": str(week.date()), "step": step}
    if p < alpha and abs(step) > a.diagnostics.backtest_error:
        return Check(name, "warn", f"Around **{week:%d %b %Y}**, before the change you're checking, the outcome shifted "
                     f"**{step:+.0%}** relative to the comparison line and stayed there (p = {p:.3f}). That usually means a "
                     "tracking or definition change, or a lasting change in one of the controls. Find out what happened. "
                     "If it's a tracking change, start the data after it or leave the earlier weeks out.", det)
    return Check(name, "ok", "No sudden step in the gap before the change.", det)


# ---------------------------------------------------------------- 4. coverage
def coverage(weekly: pd.DataFrame, outcome: str) -> Check:
    name = "All series cover the same weeks"
    rows, issues = [], []
    ref = weekly[outcome]
    for c in weekly.columns:
        s = weekly[c]
        valid = s[s.notna() & (s > 0)]
        if len(valid) == 0:
            issues.append(f"{c} has no usable values")
            continue
        first, last, gaps = valid.index.min(), valid.index.max(), int(((s.isna()) | (s <= 0)).sum())
        rows.append({"series": c, "first week": first.date(), "last week": last.date(), "missing/zero weeks": gaps})
        if c != outcome and (first > ref.first_valid_index() or last < ref.last_valid_index()):
            issues.append(f"{c} covers {first:%d %b %Y} – {last:%d %b %Y}, shorter than the outcome")
        elif gaps:
            issues.append(f"{c} has {gaps} missing or zero week(s)")
    det = {"table": pd.DataFrame(rows)}
    if issues:
        return Check(name, "warn", "Some series don't cover the same weeks. Weeks where any selected series is missing "
                     "are left out of the analysis: " + "; ".join(issues) + ".", det)
    return Check(name, "ok", "All series cover the same weeks with no gaps.", det)


# ---------------------------------------------------------------- 5. placebo
@dataclass
class PlaceboResult:
    metric: str
    window: WindowResult


def placebo_check(weekly: pd.DataFrame, spec: Spec, placebo: str, per_denominator: bool,
                  primary: int) -> PlaceboResult:
    """Run the same analysis with the placebo metric as the outcome (same controls and dates)."""
    den = spec.denominator if per_denominator else None
    ps = Spec(placebo, den, list(spec.controls), spec.change_date, spec.exclude,
              spec.controls_as_rate and bool(den))
    a = analyse(model_frame(weekly, ps), ps, primary=primary)
    return PlaceboResult(placebo, a.primary)


def apply_placebo(verdict: Verdict, main: WindowResult, placebos: list[PlaceboResult]) -> Verdict:
    """Adjust the verdict using placebo results."""
    if not placebos:
        verdict.details.append("Not checked for same-week events: no placebo metric was used.")
        return verdict
    moved = [p for p in placebos if p.window.significant]
    for p in placebos:
        verdict.details.append(f"Placebo metric '{p.metric}': {p.window.effect:+.1%} "
                               f"(p = {p.window.p_value:.3f}){' ⚠️ moved' if p.window.significant else ', no clear change'}.")
    if not moved:
        return verdict
    worst = max(moved, key=lambda p: abs(p.window.effect))
    same_dir = np.sign(worst.window.effect) == np.sign(main.effect)
    if main.significant and same_dir and abs(worst.window.effect) >= 0.5 * abs(main.effect):
        return Verdict("Unreliable", "red",
                       f"A metric the change couldn't affect ('{worst.metric}') also moved {worst.window.effect:+.1%} at "
                       f"the change date. Something else probably happened that week, and it could explain the "
                       f"{main.effect:+.1%} result. Find out what changed before drawing conclusions.", verdict.details)
    verdict.details.append(f"⚠️ '{worst.metric}' moved at the change date, so something else may have happened that "
                           "week. It doesn't obviously explain the main result, but check what it was.")
    verdict.headline += " (Note: a placebo metric also moved; see details.)"
    return verdict

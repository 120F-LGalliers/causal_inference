"""Checking candidate control series (v2).

What the tool checks automatically, per candidate
-------------------------------------------------
* **Moves with the outcome?** Correlation before the change, both of the levels
  (shared trends and seasons) and of week-to-week changes (shared shocks).
* **Improves the forecast?** We backtest: at many earlier dates, forecast the next
  8 weeks of the outcome with and without this control, and compare the errors.
  This is the most important number, because forecasting the weeks after the
  change is exactly the job a control does.
* **Weight in the blend.** When all candidates are offered together, how much the
  blend leans on each one. Zero means the blend ignores it.
* **Did it move at the change date itself?** If a control jumps when the change
  went live, it may have been affected by the change. Using it would hide part of
  the effect. This check has limited power: "no jump detected" isn't proof it was
  unaffected, so the human checklist still matters.

What it can't check
-------------------
Whether the change could have reached the people in a control series. Only
someone who knows the site and the change can answer that, hence the checklist.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .conformal import _p_value, prepare
from .data import Spec
from .synth import backtest_errors, choose_lambda, fit_blend

CHECKLIST = [
    ("reach", "Could the change have reached the people or visits counted in this series? "
              "For example, they saw the changed page, or the change sent them here."),
    ("switch", "Could the change move customers between this series and the outcome? "
               "For example, from app to web, from one journey to another, or from one product to another."),
    ("drivers", "Is this series driven by the same things as the outcome? "
                "Think seasonality, promotions, product launches, marketing campaigns, price changes."),
    ("own_events", "Did something happen to only one of the two series around the change date? "
                   "For example, a separate launch, a tracking change, an outage, or a promotion on one channel only."),
    ("tracking", "Has this series been tracked the same way across the whole date range?"),
]
SAFE_ANSWER = {"reach": "No", "switch": "No", "drivers": "Yes", "own_events": "No", "tracking": "Yes"}


@dataclass
class ControlScore:
    name: str
    corr_level: float
    corr_change: float
    backtest_gain: float        # relative reduction in 8-week forecast error vs no controls
    weight: float               # weight in the blend of all candidates
    shift_effect: float         # the control's own jump at the change date (8 weeks)
    shift_p: float
    flags: list[str] = field(default_factory=list)
    suggested: bool = False

    @property
    def shifted(self) -> bool:
        return self.shift_p < 0.05


def _rmse(e: np.ndarray) -> float:
    return float(np.sqrt(np.mean(e ** 2))) if len(e) else np.nan


def screen(frame: pd.DataFrame, spec: Spec, candidates: list[str]) -> list[ControlScore]:
    all_spec = Spec(spec.outcome, spec.denominator, list(candidates), spec.change_date, spec.exclude,
                    spec.controls_as_rate)
    prep = prepare(frame, all_spec)
    T0 = prep.n_pre
    if T0 < 12:
        raise ValueError(f"Only {T0} usable weeks before the change; at least 12 are needed.")
    y = prep.y[:T0]
    h = min(8, max(2, T0 // 4))
    base = _rmse(backtest_errors(y, None, h))

    Xall = prep.X[:T0]
    lam = choose_lambda(y, Xall, horizon=h)
    w_all = fit_blend(y, Xall, lam).weights

    scores = []
    for i, c in enumerate(candidates):
        x = prep.X[:T0, i]
        cl = float(np.corrcoef(y, x)[0, 1]) if np.std(x) > 0 else np.nan
        cc = float(np.corrcoef(np.diff(y), np.diff(x))[0, 1]) if np.std(np.diff(x)) > 0 else np.nan
        e = backtest_errors(y, x[:, None], h, choose_lambda(y, x[:, None], h))
        gain = 1 - _rmse(e) / base if base > 0 else 0.0

        # the control's own jump at the change date: treat it as an outcome with no controls
        hpost = min(8, prep.n_post)
        xc = prep.X[:T0 + hpost, i]
        p_shift, _ = _p_value(xc, np.zeros((len(xc), 0)), T0, hpost, 0.0, 0.0)
        jump = float(np.exp(xc[T0:].mean() - xc[:T0].mean()) - 1)

        s = ControlScore(c, cl, cc, gain, float(w_all[i]), jump, p_shift)
        if gain <= 0:
            s.flags.append("Doesn't improve the forecast on its own")
        if s.weight == 0:
            s.flags.append("Blend gives it no weight when combined with the others")
        if not np.isnan(cl) and cl < 0 and (np.isnan(cc) or cc < 0):
            s.flags.append("Moves opposite to the outcome: check this makes sense")
        if s.shifted:
            s.flags.append(f"Itself jumped {jump:+.0%} when the change went live. It may have been affected by the "
                           "change, or something else happened that week. Find out before using it")
        s.suggested = gain > 0 and not s.shifted
        scores.append(s)
    return scores


def scores_table(scores: list[ControlScore]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Series": s.name,
        "Suggested": "✅" if s.suggested else "",
        "Forecast improvement": f"{s.backtest_gain:+.0%}",
        "Weight in blend": round(s.weight, 2),
        "Correlation: levels": None if np.isnan(s.corr_level) else round(s.corr_level, 2),
        "Correlation: weekly changes": None if np.isnan(s.corr_change) else round(s.corr_change, 2),
        "Own jump at change date": f"{s.shift_effect:+.0%}" + (" ⚠️" if s.shifted else ""),
        "Notes": "; ".join(s.flags),
    } for s in scores])

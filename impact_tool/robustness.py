"""Robustness panel: does the conclusion survive sensible alternative choices?

Plain English
-------------
Every analysis involves choices: which controls, which change date, which weeks to
include, rate or count. If the conclusion only holds for one particular set of choices,
it's fragile, and someone could (even unintentionally) have picked the one set that gives
the answer they hoped for.

So the tool re-runs the analysis under a **fixed, pre-defined list** of alternatives.
Users can't add, remove or pick alternatives, which prevents cherry-picking. Then it
reports whether the conclusion holds across them.

Scored alternatives (count towards the robustness rating):
  * each control series removed in turn
  * no control series at all
  * change date one week earlier, and one week later
  * peak trading weeks (mid-Nov to early Jan) left out of the 'before' period
  * raw count instead of the rate (if a denominator is used)
  * only the most recent 52 weeks of history (if there are more than 70)

Shown for context, not scored:
  * shorter windows (8 and 13 weeks). These have less data and so less power, and
    a 'no clear effect' over fewer weeks isn't really a disagreement.

Rating:
  * Robust: at least 80% of scored alternatives reach the same conclusion, and none
    finds a clear effect in the opposite direction.
  * Somewhat sensitive: 60-80% agree, none opposite.
  * Fragile: under 60% agree, or any alternative finds a clear effect in the opposite direction.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .conformal import analyse
from .data import Spec, model_frame


@dataclass
class Robustness:
    table: pd.DataFrame            # one row per alternative
    rating: str                    # Robust / Somewhat sensitive / Fragile / Not enough alternatives
    agreement: float               # share of scored alternatives with the same conclusion
    same_sign: float               # share of scored alternatives with the same direction of effect
    summary: str


def conclusion(effect: float, significant: bool) -> str:
    if not significant:
        return "No clear effect"
    return "Clear rise" if effect > 0 else "Clear fall"


def peak_windows(index: pd.DatetimeIndex) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    years = sorted(set(index.year))
    return [(pd.Timestamp(f"{y}-11-15"), pd.Timestamp(f"{y + 1}-01-05")) for y in [years[0] - 1] + years]


def _variants(weekly: pd.DataFrame, spec: Spec, n_pre: int, primary: int, n_post: int):
    """(name, scored, spec, primary window) for every alternative."""
    out = []
    for c in spec.controls:
        rest = [x for x in spec.controls if x != c]
        out.append((f"Without control '{c}'", True,
                    Spec(spec.outcome, spec.denominator, rest, spec.change_date, spec.exclude, spec.controls_as_rate),
                    primary))
    if spec.controls:
        out.append(("No control series", True,
                    Spec(spec.outcome, spec.denominator, [], spec.change_date, spec.exclude, spec.controls_as_rate),
                    primary))
    for wk, label in ((-1, "Change date one week earlier"), (1, "Change date one week later")):
        out.append((label, True, Spec(spec.outcome, spec.denominator, spec.controls,
                                      spec.change_date + pd.Timedelta(weeks=wk), spec.exclude, spec.controls_as_rate),
                    primary))
    pre_weeks = weekly.index[weekly.index < spec.change_date]
    peaks = [(a, b) for a, b in peak_windows(weekly.index) if ((pre_weeks >= a) & (pre_weeks <= b)).any()]
    if peaks:
        out.append(("Peak trading weeks left out (mid-Nov to early Jan)", True,
                    Spec(spec.outcome, spec.denominator, spec.controls, spec.change_date,
                         list(spec.exclude) + peaks, spec.controls_as_rate), primary))
    if spec.denominator:
        out.append(("Raw count instead of the rate", True,
                    Spec(spec.outcome, None, spec.controls, spec.change_date, spec.exclude, False), primary))
    if n_pre > 70:
        cutoff = spec.change_date - pd.Timedelta(weeks=53)
        out.append(("Only the most recent 52 weeks of history", True,
                    Spec(spec.outcome, spec.denominator, spec.controls, spec.change_date,
                         list(spec.exclude) + [(weekly.index.min() - pd.Timedelta(days=7), cutoff)],
                         spec.controls_as_rate), primary))
    for h in (8, 13):
        if h != primary and h <= n_post:
            out.append((f"Same analysis over the first {h} weeks", False, spec, h))
    return out


def run_robustness(weekly: pd.DataFrame, spec: Spec, main, n_pre: int, n_post: int) -> Robustness:
    """main = the primary WindowResult of the main analysis."""
    main_c = conclusion(main.effect, main.significant)
    rows = [{"Alternative": "Main analysis", "Scored": "—", "Effect": main.effect, "lo": main.lo, "hi": main.hi,
             "p-value": main.p_value, "Conclusion": main_c, "Agrees": "—", "note": ""}]
    for name, scored, s, h in _variants(weekly, spec, n_pre, main.weeks, n_post):
        try:
            a = analyse(model_frame(weekly, s), s, primary=h)
            w = a.primary
            c = conclusion(w.effect, w.significant)
            rows.append({"Alternative": name, "Scored": "Yes" if scored else "No (context)", "Effect": w.effect,
                         "lo": w.lo, "hi": w.hi, "p-value": w.p_value, "Conclusion": c,
                         "Agrees": ("Yes" if c == main_c else "No") if scored else "—", "note": ""})
        except ValueError as e:
            rows.append({"Alternative": name, "Scored": "Skipped", "Effect": np.nan, "lo": np.nan, "hi": np.nan,
                         "p-value": np.nan, "Conclusion": "Couldn't run", "Agrees": "—", "note": str(e)})
    t = pd.DataFrame(rows)
    sc = t[t["Scored"] == "Yes"]
    if len(sc) < 2:
        return Robustness(t, "Not enough alternatives", np.nan, np.nan,
                          "Too few alternatives could be run to judge robustness.")
    agree = float((sc["Conclusion"] == main_c).mean())
    same_sign = float((np.sign(sc["Effect"]) == np.sign(main.effect)).mean())
    opposite = {"Clear rise": "Clear fall", "Clear fall": "Clear rise"}.get(main_c)
    flipped = bool(opposite and (sc["Conclusion"] == opposite).any()) or \
        (main_c == "No clear effect" and sc["Conclusion"].isin(["Clear rise", "Clear fall"]).sum() >= 2 and
         sc["Conclusion"].nunique() > 2)
    if flipped or agree < 0.6:
        rating = "Fragile"
    elif agree < 0.8:
        rating = "Somewhat sensitive"
    else:
        rating = "Robust"
    disagree = sc[sc["Conclusion"] != main_c]["Alternative"].tolist()
    summary = (f"{agree:.0%} of the {len(sc)} scored alternatives reach the same conclusion as the main analysis "
               f"({main_c.lower()}), and {same_sign:.0%} point in the same direction.")
    if disagree:
        summary += " Different conclusion with: " + "; ".join(disagree) + "."
    if flipped and opposite:
        summary += " At least one alternative finds a clear effect in the opposite direction."
    return Robustness(t, rating, agree, same_sign, summary)


def robustness_display(r: Robustness) -> pd.DataFrame:
    t = r.table.copy()
    t["Effect"] = t["Effect"].map(lambda v: "" if pd.isna(v) else f"{v:+.1%}")
    t["Plausible range"] = [("" if pd.isna(lo) else f"{lo:+.1%} to {hi:+.1%}") for lo, hi in zip(r.table["lo"], r.table["hi"])]
    t["p-value"] = t["p-value"].map(lambda v: "" if pd.isna(v) else f"{v:.3f}")
    return t[["Alternative", "Effect", "Plausible range", "p-value", "Conclusion", "Scored", "Agrees"]]

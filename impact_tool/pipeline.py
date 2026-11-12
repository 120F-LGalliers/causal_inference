"""One function that runs the whole analysis from a settings dict and a CSV.

The app's Run tab and the Review tab both call run_pipeline(), so a reviewer who loads
the same settings and data gets exactly the same steps, and (because the engine is
deterministic) exactly the same numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import checks as chk
from . import recipes as rcp
from .conformal import Analysis, Verdict, analyse, make_verdict
from .data import Spec, model_frame, to_weekly
from .robustness import Robustness, run_robustness


@dataclass
class PipelineResult:
    weekly_full: pd.DataFrame
    weekly: pd.DataFrame
    notes: list[str]
    spec: Spec
    analysis: Analysis
    expected: float | None
    verdict: Verdict
    data_checks: list
    placebos: list
    robustness: Robustness | None
    out_label: str
    recipe_label: str | None
    warnings: list[str] = field(default_factory=list)


def numeric_columns(df: pd.DataFrame, date_col: str) -> list[str]:
    return [c for c in df.columns if c != date_col and pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.9]


def build_weekly(df: pd.DataFrame, date_col: str, settings: dict) -> tuple[pd.DataFrame, list[str]]:
    weekly_full, notes = to_weekly(df, date_col, numeric_columns(df, date_col), settings.get("convention", "auto"))
    for a, b in settings.get("ratios") or []:
        weekly_full[f"{a} / {b}"] = weekly_full[a] / weekly_full[b]
    return weekly_full, notes


def exclusions(settings: dict) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    ex = []
    if settings.get("test_window"):
        ex.append((pd.Timestamp(settings["test_window"][0]), pd.Timestamp(settings["test_window"][1])))
    for row in settings.get("extra_exclude") or []:
        ex.append((pd.Timestamp(row[0]), pd.Timestamp(row[1])))
    return ex


def run_pipeline(df: pd.DataFrame, date_col: str, settings: dict, with_robustness: bool = True) -> PipelineResult:
    s = settings
    weekly_full, notes = build_weekly(df, date_col, s)
    outcome, denom, controls = s["outcome"], s.get("denominator"), list(s.get("controls") or [])
    weekly = weekly_full[[outcome] + ([denom] if denom else []) + list(dict.fromkeys(controls + list(s.get("candidates") or [])))]
    exclude = exclusions(s)
    spec = Spec(outcome, denom, controls, pd.Timestamp(s["change_date"]), exclude, bool(s.get("controls_as_rate")))
    a = analyse(model_frame(weekly, spec), spec, primary=int(s["primary"]) if s.get("primary") else None)
    expected = (s["test_lift"] / 100) * (s.get("exposure", 100) / 100) if s.get("lift_known") else None
    verdict = make_verdict(a.primary, a.diagnostics, expected)
    w = a.primary

    # recipe context
    client_rec, recipe_label, recipe_id = None, None, s.get("recipe_id")
    if s.get("recipe_client"):
        try:
            client_rec = rcp.load_all().get(s["recipe_client"])
        except Exception:  # noqa: BLE001
            client_rec = None
        if client_rec and recipe_id:
            r = next((r for r in client_rec.get("recipes") or [] if r["id"] == recipe_id), None)
            recipe_label = f"{s['recipe_client']}: {r['name']} ({recipe_id})" if r else None
    recipe_warnings = rcp.date_warnings(client_rec, weekly[outcome].first_valid_index(),
                                        weekly[outcome].last_valid_index(), recipe_id) if client_rec else []

    # data checks
    recon = chk.reconcile(weekly, outcome, denom, s.get("test_window"), s.get("control_value") or None,
                          s.get("control_unit", "rate_pct"), (s.get("control_share") or 50) / 100)
    den_chk = chk.denominator_jump(weekly, spec, a.prep.n_pre)
    brk_chk = chk.hidden_break(a)
    cov = chk.coverage(weekly, outcome)
    data_checks = [recon, den_chk, brk_chk, cov] + [chk.Check("Known issue for this client", "warn", x)
                                                    for x in recipe_warnings]

    # placebo metrics
    placebos, warns = [], []
    for pc in s.get("placebo") or []:
        try:
            placebos.append(chk.placebo_check(weekly_full, spec, pc, bool(s.get("placebo_per_denominator")) and bool(denom),
                                              w.weeks))
        except (ValueError, KeyError) as e:
            warns.append(f"Placebo '{pc}' couldn't be analysed: {e}")
    verdict = chk.apply_placebo(verdict, w, placebos)

    # export vs test
    ack, why = bool(s.get("recon_ack")), s.get("recon_reason", "")
    if recon.status == "fail" and not ack and verdict.label != "Unreliable":
        verdict = Verdict("Unreliable", "red", "Your export doesn't match the test's own control-group figure, so it "
                          "probably isn't the same metric as the test. Fix the export, or confirm the difference is "
                          "expected in step 2.", verdict.details + [recon.message])
    elif recon.status in ("warn", "fail"):
        verdict.details.append("Export vs test: " + recon.message + (f" Acknowledged: {why}" if ack else ""))
    elif recon.status == "skipped":
        verdict.details.append("Export not checked against the test's control-group figure.")
    for c in (den_chk, brk_chk):
        if c.status == "warn":
            verdict.details.append(c.message)

    # robustness
    rob = run_robustness(weekly_full, spec, w, a.prep.n_pre, a.prep.n_post) if with_robustness else None
    if rob is not None:
        verdict.details.append(f"Robustness: {rob.rating}. {rob.summary}")
        if rob.rating == "Fragile" and verdict.label not in ("Unreliable",):
            verdict.headline += (" However, this result is fragile: it changes under reasonable alternative choices "
                                 "(see the robustness panel). Treat it with caution.")
            if verdict.colour == "green":
                verdict.colour = "amber"

    out_label = f"{outcome} / {denom}" if denom else outcome
    return PipelineResult(weekly_full, weekly, notes, spec, a, expected, verdict, data_checks, placebos, rob,
                          out_label, recipe_label, warns)


def result_summary(r: PipelineResult) -> dict:
    """The numbers a reviewer's re-run must reproduce."""
    w = r.analysis.primary
    return {"window_weeks": w.weeks, "effect": round(w.effect, 10), "lo": round(w.lo, 10), "hi": round(w.hi, 10),
            "p_value": round(w.p_value, 10), "verdict": r.verdict.label,
            "robustness": r.robustness.rating if r.robustness else None,
            "placebos": {p.metric: round(p.window.effect, 10) for p in r.placebos},
            "checks": {c.name: c.status for c in r.data_checks}}

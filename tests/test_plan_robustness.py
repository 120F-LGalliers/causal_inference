"""Tests for the robustness panel, the pipeline and plan/review packs."""
import json

import numpy as np
import pandas as pd

from impact_tool import Spec, analyse, load_csv, model_frame
from impact_tool import plan as pl
from impact_tool.pipeline import result_summary, run_pipeline
from impact_tool.robustness import conclusion, run_robustness

SETTINGS = {"outcome": "orders", "denominator": "visits", "controls": ["unexposed_orders / unexposed_visits"],
            "candidates": ["unexposed_orders / unexposed_visits"], "ratios": [["unexposed_orders", "unexposed_visits"]],
            "change_date": "2025-11-12", "test_window": ["2025-08-04", "2025-08-31"], "extra_exclude": [],
            "controls_as_rate": False, "primary": 26, "lift_known": True, "test_lift": 3.0, "exposure": 100,
            "control_value": 1.28, "control_unit": "rate_pct", "control_share": 50, "placebo": ["help_page_visits"],
            "placebo_per_denominator": False, "convention": "auto"}


def frame(effect, seed, n=110, change=80, ctrl_breaks=False):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="7D")
    d = np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    c1 = 1000 * d * np.exp(rng.normal(0, 0.02, n))
    c2 = 800 * d * np.exp(rng.normal(0, 0.02, n))
    if ctrl_breaks:
        c2[change - 1:] *= 1.6            # a control that jumps at the change date (contaminated)
    y = 500 * d * np.exp(rng.normal(0, 0.03, n))
    y[change:] *= 1 + effect
    return pd.DataFrame({"y": y, "c1": c1, "c2": c2}, index=idx), idx[change]


def test_conclusion_labels():
    assert conclusion(0.2, True) == "Clear rise" and conclusion(-0.2, True) == "Clear fall"
    assert conclusion(0.2, False) == "No clear effect"


def test_robust_when_effect_is_clear_and_controls_clean():
    w, cd = frame(0.3, 1)
    s = Spec("y", None, ["c1", "c2"], cd)
    a = analyse(model_frame(w, s), s)
    r = run_robustness(w, s, a.primary, a.prep.n_pre, a.prep.n_post)
    assert r.rating == "Robust"


def test_flags_a_control_contaminated_by_the_change():
    # real +30% effect, but control c2 was also pushed up by the change, hiding the effect
    w, cd = frame(0.3, 2)
    w.loc[w.index >= cd, "c2"] *= 1.3
    s = Spec("y", None, ["c1", "c2"], cd)
    a = analyse(model_frame(w, s), s)
    r = run_robustness(w, s, a.primary, a.prep.n_pre, a.prep.n_post)
    assert not a.primary.significant
    assert r.rating == "Fragile"
    row = r.table.set_index("Alternative").loc["Without control 'c2'"]
    assert row["Conclusion"] == "Clear rise"


def test_pipeline_reproducible_and_pack_verifies():
    df, dc = load_csv("sample_data/example_synthetic_small_effect.csv")
    r1 = run_pipeline(df, dc, SETTINGS)
    r2 = run_pipeline(df, dc, json.loads(json.dumps(SETTINGS)))
    assert result_summary(r1) == result_summary(r2)
    fp = pl.fingerprint(r1.weekly_full)
    pack = json.loads(json.dumps(pl.make_pack(pl.make_plan(SETTINGS, fp, "A", "Client-facing"),
                                              result_summary(r1), "md", []), default=str))
    assert all(ok for _, ok, _ in pl.verify(pack, pl.fingerprint(r2.weekly_full), result_summary(r2)))


def test_pack_tampering_and_wrong_data_detected():
    df, dc = load_csv("sample_data/example_synthetic_small_effect.csv")
    r = run_pipeline(df, dc, SETTINGS)
    fp = pl.fingerprint(r.weekly_full)
    pack = json.loads(json.dumps(pl.make_pack(pl.make_plan(SETTINGS, fp, "A", "Client-facing"),
                                              result_summary(r), "md", []), default=str))
    edited = json.loads(json.dumps(pack))
    edited["results"]["effect"] = 0.5
    names = {n: ok for n, ok, _ in pl.verify(edited, fp, result_summary(r))}
    assert not names["Pack unaltered"] and not names["Results reproduce"]
    df2 = df.copy()
    df2.loc[5, "orders"] *= 1.1
    r_bad = run_pipeline(df2, dc, SETTINGS)
    names = {n: ok for n, ok, _ in pl.verify(pack, pl.fingerprint(r_bad.weekly_full), result_summary(r_bad))}
    assert not names["Same data"]


def test_signing_records_review_and_changes_integrity():
    plan = pl.make_plan(SETTINGS, "fp", "A", "Client-facing")
    pack = pl.make_pack(plan, {"effect": 0.1}, "md", [])
    signed = pl.sign(pack, "B", "Approved", {k: "Yes" for k, _ in pl.REVIEW_CHECKLIST}, "")
    assert signed["review"]["reviewer"] == "B" and signed["integrity"] != pack["integrity"]
    assert "NOT REVIEWED" in pl.review_block_md(None, plan)
    assert "Approved" in pl.review_block_md(signed["review"], plan)


def test_html_report_works_offline():
    """Charts are embedded as SVG, so the report needs no CDN."""
    import pandas as pd
    from impact_tool.report import html_report, impact_chart, robustness_chart
    df, dc = load_csv("sample_data/example_synthetic_small_effect.csv")
    r = run_pipeline(df, dc, SETTINGS)
    h = html_report("# x", {"a": impact_chart(r.analysis, pd.Timestamp(SETTINGS["change_date"]), "rate", r.spec.exclude),
                            "b": robustness_chart(r.robustness)}, r.verdict)
    assert h.count("<svg") >= 2 and "jsdelivr" not in h

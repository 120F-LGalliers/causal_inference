"""Tests for the data checks, placebo handling and recipe library."""
import numpy as np
import pandas as pd
import pytest
import yaml

from impact_tool import Spec, analyse, make_verdict, model_frame
from impact_tool import checks as chk
from impact_tool import recipes as rcp


def weekly_frame(n=80, change=60, effect=0.0, den_jump=0.0, placebo_jump=0.0, step_at=None, step=0.0, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="7D")
    demand = np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    visits = 10000 * demand * np.exp(rng.normal(0, 0.03, n))
    visits[change:] *= 1 + den_jump
    rate = 0.02 * np.exp(rng.normal(0, 0.03, n))
    rate[change:] *= 1 + effect
    if step_at is not None:
        rate[step_at:] *= 1 + step
    ctrl = 5000 * demand * np.exp(rng.normal(0, 0.02, n))
    plac = 800 * demand * np.exp(rng.normal(0, 0.03, n))
    plac[change:] *= 1 + placebo_jump
    return pd.DataFrame({"orders": visits * rate, "visits": visits, "ctrl": ctrl, "plac": plac}, index=idx), idx[change]


def test_reconcile_statuses():
    w, _ = weekly_frame()
    win = [w.index[10], w.index[14] + pd.Timedelta(days=6)]
    true = w.orders.iloc[10:15].sum() / w.visits.iloc[10:15].sum() * 100
    assert chk.reconcile(w, "orders", "visits", win, true * 1.05, "rate_pct").status == "ok"
    assert chk.reconcile(w, "orders", "visits", win, true * 1.3, "rate_pct").status == "warn"
    assert chk.reconcile(w, "orders", "visits", win, true * 2.5, "rate_pct").status == "fail"
    assert chk.reconcile(w, "orders", "visits", win, None, "rate_pct").status == "skipped"
    cnt = w.orders.iloc[10:15].mean() * 0.5
    assert chk.reconcile(w, "orders", None, win, cnt, "weekly_count", 0.5).status == "ok"


def test_denominator_jump_flagged():
    w, cd = weekly_frame(den_jump=0.4)
    spec = Spec("orders", "visits", ["ctrl"], cd)
    assert chk.denominator_jump(w, spec, 59).status == "warn"
    w2, cd2 = weekly_frame(den_jump=0.0, seed=3)
    assert chk.denominator_jump(w2, Spec("orders", "visits", ["ctrl"], cd2), 59).status == "ok"


def test_hidden_break_flagged_and_quiet():
    w, cd = weekly_frame(step_at=30, step=0.5, seed=4)
    spec = Spec("orders", "visits", [], cd)
    a = analyse(model_frame(w, spec), spec)
    assert chk.hidden_break(a).status == "warn"
    w2, cd2 = weekly_frame(seed=5)
    a2 = analyse(model_frame(w2, Spec("orders", "visits", [], cd2)), Spec("orders", "visits", [], cd2))
    assert chk.hidden_break(a2).status == "ok"


def test_placebo_downgrades_when_it_explains_the_effect():
    w, cd = weekly_frame(effect=0.3, placebo_jump=0.3, seed=6)
    spec = Spec("orders", "visits", [], cd)
    a = analyse(model_frame(w, spec), spec)
    v = make_verdict(a.primary, a.diagnostics, 0.3)
    assert v.label == "Held"
    p = chk.placebo_check(w, spec, "plac", False, a.primary.weeks)
    assert p.window.significant
    assert chk.apply_placebo(v, a.primary, [p]).label == "Unreliable"


def test_placebo_quiet_keeps_verdict():
    w, cd = weekly_frame(effect=0.3, placebo_jump=0.0, seed=7)
    spec = Spec("orders", "visits", [], cd)
    a = analyse(model_frame(w, spec), spec)
    v = make_verdict(a.primary, a.diagnostics, 0.3)
    p = chk.placebo_check(w, spec, "plac", False, a.primary.weeks)
    assert chk.apply_placebo(v, a.primary, [p]).label == v.label
    assert "Not checked" in chk.apply_placebo(make_verdict(a.primary, a.diagnostics, 0.3), a.primary, []).details[-1]


def test_coverage_flags_short_series():
    w, _ = weekly_frame()
    w.loc[w.index[:10], "ctrl"] = np.nan
    assert chk.coverage(w, "orders").status == "warn"


def test_recipes_load_and_validate(tmp_path):
    all_ = rcp.load_all()
    assert "Tesco Mobile" in all_
    tm = all_["Tesco Mobile"]
    cols = rcp.recipe_columns(next(r for r in tm["recipes"] if r["id"] == "tm_ma_dashboard_new_lines"))
    assert cols["outcome"] == "ns_orders_dashboard_visits" and cols["placebo"] == ["login_visits"]
    w = rcp.date_warnings(tm, pd.Timestamp("2024-06-01"), pd.Timestamp("2026-10-01"), "tm_login_forgot_username")
    assert any("only reliable from" in x for x in w) and not any("Store-assisted" in x for x in w)
    w2 = rcp.date_warnings(tm, pd.Timestamp("2024-09-02"), pd.Timestamp("2026-10-01"), "tm_ma_dashboard_new_lines")
    assert any("Store-assisted" in x for x in w2)
    (tmp_path / "bad.yaml").write_text(yaml.safe_dump({"client": "X", "data_source": {}, "recipes": [{"id": "a"}]}))
    with pytest.raises(ValueError):
        rcp.load_all(tmp_path)

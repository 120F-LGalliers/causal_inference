"""Behaviour tests for the v2 engine, plus regression tests on the TM analyses (Nov 2026)."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from impact_tool import Spec, analyse, load_csv, make_verdict, model_frame, screen, to_weekly
from impact_tool.conformal import suggest_window
from impact_tool.data import change_weeks

FIX = Path(__file__).parent / "fixtures"


def synthetic(effect: float, seed: int = 1, n: int = 104, change_week: int = 70) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    w = pd.date_range("2024-01-01", periods=n, freq="7D")
    demand = np.exp(np.cumsum(rng.normal(0, 0.03, n)))
    ctrl = 1000 * demand * np.exp(rng.normal(0, 0.02, n))
    out = 500 * demand * np.exp(rng.normal(0, 0.03, n))
    out[change_week:] *= 1 + effect
    return pd.DataFrame({"week": w, "outcome": out, "control": ctrl})


def run(df, controls=("control",), primary=None):
    spec = Spec("outcome", None, list(controls), df.week[70])
    weekly, _ = to_weekly(df, "week", ["outcome", "control"])
    return analyse(model_frame(weekly, spec), spec, primary=primary)


@pytest.mark.parametrize("effect", [-0.3, 0.3])
def test_detects_large_effect(effect):
    a = run(synthetic(effect))
    assert a.primary.significant
    assert abs(a.primary.effect - effect) < 0.06
    assert a.primary.lo <= effect <= a.primary.hi


def test_null_not_significant():
    a = run(synthetic(0.0, seed=3))
    assert not a.primary.significant


def test_deterministic():
    df = synthetic(0.1, seed=4)
    a1, a2 = run(df), run(df)
    assert a1.primary.effect == a2.primary.effect and a1.primary.p_value == a2.primary.p_value


def test_control_gets_weight_and_helps():
    a = run(synthetic(0.0, seed=5))
    assert a.blend.weights[0] > 0.5
    assert a.diagnostics.backtest_error < a.diagnostics.backtest_error_no_controls


def test_screen_prefers_true_control():
    df = synthetic(0.1, seed=6)
    rng = np.random.default_rng(0)
    df["noise"] = 1000 * np.exp(rng.normal(0, 0.1, len(df)))
    spec = Spec("outcome", None, ["control", "noise"], df.week[70])
    weekly, _ = to_weekly(df, "week", ["outcome", "control", "noise"])
    sc = {s.name: s for s in screen(model_frame(weekly, spec), spec, ["control", "noise"])}
    assert sc["control"].suggested
    assert sc["control"].backtest_gain > sc["noise"].backtest_gain


def test_suggest_window():
    assert suggest_window(57, 49) == 26
    assert suggest_window(19, 92) == 8
    assert suggest_window(120, 60) == 52


def test_change_weeks_midweek_and_monday():
    idx = pd.date_range("2025-01-06", periods=10, freq="7D")
    assert change_weeks(idx, pd.Timestamp("2025-01-14")) == (pd.Timestamp("2025-01-13"), pd.Timestamp("2025-01-20"))
    assert change_weeks(idx, pd.Timestamp("2025-01-13")) == (None, pd.Timestamp("2025-01-13"))


def test_daily_data_summed_to_weeks():
    d = pd.DataFrame({"date": pd.date_range("2025-01-01", "2025-03-31"), "x": 1.0})
    weekly, _ = to_weekly(d, "date", ["x"], "daily")
    assert (weekly["x"] == 7).all() and weekly.index[0].dayofweek == 0


@pytest.mark.parametrize("conv,start", [("week_start_sunday", "2025-01-05"), ("week_end_sunday", "2025-01-12"),
                                        ("week_end_saturday", "2025-01-11"), ("week_start_monday", "2025-01-06")])
def test_week_conventions(conv, start):
    d = pd.DataFrame({"week": pd.date_range(start, periods=3, freq="7D"), "x": [1.0, 2.0, 3.0]})
    weekly, _ = to_weekly(d, "week", ["x"], conv)
    assert weekly.index[0] == pd.Timestamp("2025-01-06")


def test_tm_eaoa1541_forgot_username_held():
    df, dc = load_csv(FIX / "tm_eaoa1541_forgot_username.csv")
    spec = Spec("forgot_username_visits", "login_visits", [], pd.Timestamp("2025-01-14"),
                [(pd.Timestamp("2024-08-14"), pd.Timestamp("2024-09-11"))])
    weekly, _ = to_weekly(df, dc, ["forgot_username_visits", "login_visits"])
    a = analyse(model_frame(weekly, spec), spec)
    assert a.primary.weeks == 8
    assert -0.30 < a.primary.effect < -0.18 and a.primary.significant
    assert make_verdict(a.primary, a.diagnostics, -0.28).label == "Held"


def test_tm_eaoa2008_family_perks_inconclusive():
    df, dc = load_csv(FIX / "tm_eaoa2008_family_perks.csv")
    cols = ["ns_orders_dashboard_visits", "dashboard_visits", "ns_orders_non_dashboard", "new_customer_orders"]
    spec = Spec(cols[0], cols[1], cols[2:], pd.Timestamp("2025-11-13"),
                [(pd.Timestamp("2025-05-19"), pd.Timestamp("2025-06-19"))])
    weekly, _ = to_weekly(df, dc, cols)
    a = analyse(model_frame(weekly, spec), spec)
    assert a.primary.weeks == 26 and not a.primary.significant
    assert a.primary.mde(1) > 0.1
    assert make_verdict(a.primary, a.diagnostics, 0.024).label == "Inconclusive"

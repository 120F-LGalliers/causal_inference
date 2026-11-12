"""Validation study: how often does each engine raise false alarms, and how often
does it catch real effects, on *real* client series?

Method: take stretches of real weekly data where nothing changed, pick many fake
change dates, multiply the outcome after each date by a known amount (0%, 5%,
10%, 20%, 30%), and record whether each engine calls it significant.

  * At 0% injected, the significant rate is the false-alarm rate (target: 5%).
  * At other sizes, it's the detection rate (power).

Run:  python validation/run_validation.py           (writes validation/results.csv)
"""
from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from impact_tool.conformal import _p_value, prepare          # noqa: E402
from impact_tool.data import Spec, load_csv, model_frame, to_weekly   # noqa: E402
from impact_tool.model import run_impact                      # noqa: E402
from impact_tool.synth import choose_lambda                   # noqa: E402

EFFECTS = [0.0, 0.05, 0.10, 0.20, 0.30]
WINDOWS = [8, 26]


def pools():
    """Stretches of real data with no known change in them."""
    fx = ROOT / "tests" / "fixtures"
    out = []
    df, dc = load_csv(fx / "tm_eaoa2008_family_perks.csv")
    cols = ["ns_orders_dashboard_visits", "dashboard_visits", "ns_orders_non_dashboard", "new_customer_orders"]
    w, _ = to_weekly(df, dc, cols)
    w = w[(w.index < "2025-11-10") & ~((w.index >= "2025-05-19") & (w.index <= "2025-06-16"))]
    out.append(("TM multiline orders per dashboard visit (2024-25)", w, cols[0], cols[1], cols[2:], False))
    df, dc = load_csv(fx / "tm_eaoa1541_forgot_username.csv")
    cols = ["forgot_username_visits", "login_visits", "forgot_password_visits"]
    w, _ = to_weekly(df, dc, cols)
    w = w[w.index >= "2025-01-20"]
    out.append(("TM forgot-username rate (2025-26)", w, cols[0], cols[1], cols[2:], True))
    return out


def v2_sig(frame, spec, h):
    prep = prepare(frame, spec)
    T0 = prep.n_pre
    y, X = prep.y[:T0 + h], prep.X[:T0 + h]
    lam = choose_lambda(prep.y[:T0], prep.X[:T0] if X.shape[1] else None)
    p, _ = _p_value(y, X, T0, h, 0.0, lam)
    return p < 0.05


def v1_sig(frame, spec, h):
    r = run_impact(frame, spec, horizons=(h,), n_sims=800)
    return r.windows[0].significant


def main():
    rows = []
    t0 = time.time()
    for name, w, out, den, ctrls, as_rate in pools():
        n = len(w)
        for h in WINDOWS:
            dates = [w.index[i] for i in range(20, n - h + 1, 2)]
            for d in dates:
                sub = w[w.index < d + pd.Timedelta(weeks=h)]
                for eff in EFFECTS:
                    ww = sub.astype(float).copy()
                    ww.loc[ww.index >= d, out] *= 1 + eff
                    spec = Spec(out, den, ctrls, d, [], as_rate)
                    fr = model_frame(ww, spec)
                    rows.append({"pool": name, "window": h, "date": d.date(), "effect": eff,
                                 "v2": v2_sig(fr, spec, h), "v1": v1_sig(fr, spec, h)})
            print(f"{name} h={h}: {len(dates)} dates done ({time.time() - t0:.0f}s)")
    res = pd.DataFrame(rows)
    res.to_csv(Path(__file__).parent / "results.csv", index=False)
    summary = res.groupby(["pool", "window", "effect"])[["v1", "v2"]].mean().unstack("effect")
    pd.set_option("display.width", 200)
    print(summary.round(2))
    print("\nOverall false-alarm rate (0% injected):",
          res[res.effect == 0][["v1", "v2"]].mean().round(3).to_dict())


if __name__ == "__main__":
    main()

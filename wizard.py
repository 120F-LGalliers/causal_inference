"""'Run a check' as a step-by-step wizard.

Six steps, one per screen, then the results:

  1. Start        - what you're checking: client, recipe (or an example / saved settings)
  2. The test     - test name, result, dates, and the test's control figure
  3. Go-live date - when users first saw the change
  4. Your data    - upload the CSV and pick the outcome
  5. Comparison   - control series, checklist, placebo
  6. Check & run  - summary, purpose, lock and run
  -> Results

Every answer is kept in st.session_state["wz"], so moving between steps never loses anything.
Widgets read their starting value from there and write back to it.
"""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from impact_tool import (CHECKLIST, SAFE_ANSWER, WEEK_CONVENTIONS, Spec, load_csv, model_frame, quality_flags,
                         scores_table, screen, to_weekly)
from impact_tool import checks as chk
from impact_tool import plan as plan_mod
from impact_tool import recipes as rcp
from impact_tool.conformal import prepare, suggest_window
from impact_tool.data import detect_convention
from impact_tool.pipeline import result_summary, run_pipeline
from impact_tool.report import (blend_table, block_chart, gap_chart, html_report, impact_chart, markdown_report,
                                plain_english, robustness_chart, windows_table)
from impact_tool.robustness import robustness_display

ROOT = Path(__file__).parent
GUIDE = ROOT / "docs" / "guide"
ss = st.session_state

STEPS = ["Start", "The test", "Go-live date", "Your data", "Comparison", "Check & run"]
RESULTS = len(STEPS)          # step index of the results page

EXAMPLES = {
    "Tesco Mobile EAOA-1541: forgotten username copy (effect held)": {
        "file": "sample_data/example_forgot_username.csv", "client": "Tesco Mobile",
        "name": "Reduce forgotten username on login", "primary_metric": "Clicks on 'Forgotten username'",
        "test_ticket": "EAOA-1541", "release_ticket": "MAG-5274", "lift_known": True, "test_lift": -40.0,
        "exposure": 70, "release_date": "2025-01-14", "ran_100": "No", "test_window": ["2024-08-14", "2024-09-11"],
        "outcome": "forgot_username_visits", "denominator": "login_visits",
        "candidates": ["forgot_password_visits"], "controls_as_rate": True, "ratios": [],
        "recipe_client": "Tesco Mobile", "recipe_id": "tm_login_forgot_username", "placebo": [],
    },
    "Synthetic: small +3% conversion win (inconclusive)": {
        "file": "sample_data/example_synthetic_small_effect.csv", "client": "Demo", "name": "Synthetic example",
        "primary_metric": "Orders per visit", "test_ticket": "", "release_ticket": "", "lift_known": True,
        "test_lift": 3.0, "exposure": 100, "release_date": "2025-11-12", "ran_100": "No",
        "test_window": ["2025-08-04", "2025-08-31"], "control_value": 1.28, "control_unit": "rate_pct",
        "outcome": "orders", "denominator": "visits",
        "candidates": ["unexposed_orders / unexposed_visits", "brand_search_index"], "controls_as_rate": False,
        "ratios": [["unexposed_orders", "unexposed_visits"]], "placebo": ["help_page_visits"],
        "placebo_per_denominator": False,
    },
}


# ------------------------------------------------------------------ shared helpers (also used by app.py)
def explain(title: str, body: str, expanded: bool = False):
    with st.expander(f"ℹ️ {title}", expanded=expanded):
        st.markdown(body)


@st.cache_data(show_spinner=False)
def load_recipes():
    try:
        return rcp.load_all(), None
    except Exception as e:  # noqa: BLE001
        return {}, str(e)


@st.cache_data(show_spinner=False)
def cached_pipeline(df, date_col, settings_json):
    return run_pipeline(df, date_col, json.loads(settings_json))


@st.cache_data(show_spinner=False)
def cached_screen(frame, outcome, denom, candidates, change, exclude, as_rate):
    spec = Spec(outcome, denom, list(candidates), pd.Timestamp(change), list(exclude), as_rate)
    return screen(frame, spec, list(candidates))


@st.cache_data(show_spinner=False)
def _load_bytes(b: bytes):
    return load_csv(io.BytesIO(b))


# ------------------------------------------------------------------ state
def S() -> dict:
    return ss.setdefault("wz", {})


def key(name: str) -> str:
    return f"wz_{name}_{ss.get('wz_nonce', 0)}"


def go(step: int):
    if step != ss.get("wz_step", 0):
        ss["wz_visit"] = ss.get("wz_visit", 0) + 1
    ss["wz_step"] = step
    ss["wz_max"] = max(ss.get("wz_max", 0), min(step, RESULTS - 1))


def reset(values: dict | None = None):
    ss["wz"] = dict(values or {})
    ss["wz_nonce"] = ss.get("wz_nonce", 0) + 1
    for k_ in ("scores", "scores_key", "locked", "mon_table"):
        ss.pop(k_, None)
    ss["wz_step"], ss["wz_max"] = 0, 0


def _d(v, fallback: date) -> date:
    try:
        return pd.Timestamp(v).date() if v else fallback
    except Exception:  # noqa: BLE001
        return fallback


def current_recipe():
    recipes_all, _ = load_recipes()
    client_rec = recipes_all.get(S().get("recipe_client") or "")
    recipe = None
    if client_rec:
        recipe = next((r for r in client_rec.get("recipes") or [] if r["id"] == S().get("recipe_id")), None)
    return client_rec, recipe


def current_data():
    s = S()
    try:
        if s.get("csv_bytes"):
            return _load_bytes(s["csv_bytes"])
        if s.get("file"):
            return _load_bytes((ROOT / s["file"]).read_bytes())
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't read the data file: {e}")
    return None


def change_date_info():
    s = S()
    rel = _d(s.get("release_date"), date.today() - timedelta(days=180))
    if s.get("ran_100") == "Yes" and s.get("date_100"):
        return _d(s["date_100"], rel), "date the winner went to 100% in the testing tool"
    return rel, "release date"


def exclusions() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    s, ex = S(), []
    if s.get("lift_known", True) and s.get("test_window"):
        ex.append((pd.Timestamp(s["test_window"][0]), pd.Timestamp(s["test_window"][1])))
    for r in s.get("extra_exclude") or []:
        ex.append((pd.Timestamp(r[0]), pd.Timestamp(r[1])))
    return ex


def derived():
    """Everything computed from the data and the answers so far (None if no data yet)."""
    s, loaded = S(), current_data()
    if loaded is None:
        return None
    df, date_col = loaded
    numeric = [c for c in df.columns if c != date_col and pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.9]
    if not numeric:
        return {"df": df, "date_col": date_col, "numeric": [], "error": "No numeric columns found in the file."}
    detected = detect_convention(df[date_col])
    convention = s.get("convention") or detected
    if not s.get("ratios") and s.get("recipe_ratios"):
        auto = [p for p in s["recipe_ratios"] if p[0] in numeric and p[1] in numeric]
        if auto:
            s["ratios"] = auto[:5]
    ratios = [r for r in s.get("ratios") or [] if r[0] in numeric and r[1] in numeric and r[0] != r[1]]
    weekly_full, notes = to_weekly(df, date_col, numeric, convention)
    for a_, b_ in ratios:
        weekly_full[f"{a_} / {b_}"] = weekly_full[a_] / weekly_full[b_]
    outcome = s.get("outcome") if s.get("outcome") in numeric else numeric[0]
    denom = s.get("denominator") if s.get("denominator") in numeric and s.get("denominator") != outcome else None
    all_series = numeric + [f"{a} / {b}" for a, b in ratios]
    candidates = [c for c in s.get("candidates") or [] if c in all_series and c not in (outcome, denom)]
    controls = [c for c in s.get("controls") or [] if c in candidates]
    return {"df": df, "date_col": date_col, "numeric": numeric, "detected": detected, "convention": convention,
            "ratios": ratios, "weekly_full": weekly_full, "notes": notes, "outcome": outcome, "denom": denom,
            "all_series": all_series, "candidates": candidates, "controls": controls,
            "out_label": f"{outcome} / {denom}" if denom else outcome}


def build_settings(dv) -> dict:
    s = S()
    cd, reason = change_date_info()
    tw = s.get("test_window") if s.get("lift_known", True) else None
    return {"client": s.get("client", ""), "name": s.get("name", ""), "primary_metric": s.get("primary_metric", ""),
            "test_ticket": s.get("test_ticket", ""), "release_ticket": s.get("release_ticket", ""),
            "lift_known": bool(s.get("lift_known", True)), "test_lift": float(s.get("test_lift") or 0.0),
            "exposure": int(s.get("exposure", 100)), "release_date": str(_d(s.get("release_date"), cd)),
            "ran_100": s.get("ran_100", "No"), "change_date": str(cd), "change_date_reason": reason,
            "test_window": tw, "extra_exclude": s.get("extra_exclude") or [], "convention": dv["convention"],
            "outcome": dv["outcome"], "denominator": dv["denom"], "candidates": dv["candidates"],
            "controls": dv["controls"], "controls_as_rate": bool(s.get("controls_as_rate")) and dv["denom"] is not None,
            "ratios": dv["ratios"], "primary": int(s["primary"]) if s.get("primary") else None,
            "recipe_client": s.get("recipe_client"), "recipe_id": s.get("recipe_id"),
            "control_value": float(s.get("control_value") or 0), "control_unit": s.get("control_unit", "rate_pct"),
            "control_share": int(s.get("control_share", 50)), "recon_ack": bool(s.get("recon_ack")),
            "recon_reason": s.get("recon_reason", ""), "placebo": [p for p in s.get("placebo") or []
                                                                     if p in dv["weekly_full"].columns],
            "placebo_per_denominator": bool(s.get("placebo_per_denominator")) and dv["denom"] is not None,
            "checklist_answers": {c: (s.get("checklist") or {}).get(c, {}) for c in dv["controls"]}}


# ------------------------------------------------------------------ step completeness
def missing(step: int) -> list[str]:
    s, out = S(), []
    if step == 1:
        if not s.get("name", "").strip():
            out.append("a test name")
        if s.get("lift_known", True):
            if not s.get("test_lift"):
                out.append("the test result (% change)")
            if not s.get("test_window"):
                out.append("the test's start and end dates")
    elif step == 2:
        if s.get("ran_100") == "Yes" and not s.get("date_100"):
            out.append("the date it went to 100%")
    elif step == 3:
        dv = derived()
        if dv is None:
            out.append("a data file")
        elif dv.get("error"):
            out.append("a file with numeric columns")
    elif step == 4:
        dv = derived()
        if dv and not dv.get("error"):
            for c in dv["controls"]:
                answers = (s.get("checklist") or {}).get(c, {})
                n = sum(1 for qk, _ in CHECKLIST if not answers.get(qk))
                if n:
                    out.append(f"{n} checklist answer(s) for '{c}'")
    elif step == 5:
        if s.get("purpose") == "Client-facing" and not s.get("author", "").strip():
            out.append("your name (needed for client-facing checks)")
    return out


# ------------------------------------------------------------------ layout pieces
def progress():
    """A visual stepper: done steps ticked, current step highlighted, later steps grey."""
    step = ss.get("wz_step", 0)
    items = []
    for i, nm in enumerate(STEPS + ["Results"]):
        done = i < step
        cur = i == step
        bg = "#1E8449" if done else ("#C0392B" if cur else "transparent")
        fg = "#fff" if (done or cur) else "#8a939c"
        border = bg if (done or cur) else "#c8ced3"
        mark = "✓" if done else (str(i + 1) if i < RESULTS else "★")
        weight = "700" if cur else "400"
        items.append(
            f"<div style='flex:1;display:flex;flex-direction:column;align-items:center;min-width:0'>"
            f"<div style='width:30px;height:30px;border-radius:50%;background:{bg};color:{fg};border:2px solid {border};"
            f"display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px'>{mark}</div>"
            f"<div style='margin-top:6px;font-size:13px;font-weight:{weight};text-align:center;"
            f"color:{'inherit' if (done or cur) else '#8a939c'}'>{nm}</div></div>")
        if i < RESULTS:
            line = "#1E8449" if i < step else "#c8ced3"
            items.append(f"<div style='flex:0.6;height:2px;background:{line};margin-top:15px'></div>")
    st.markdown(f"<div style='display:flex;align-items:flex-start;margin:4px 0 14px'>{''.join(items)}</div>",
                unsafe_allow_html=True)


def scroll_to_top():
    """Jump back to the top when the step changes (Streamlit otherwise keeps the scroll position)."""
    import streamlit.components.v1 as components
    components.html("<script>(function(){const d=window.parent.document;"
                    "for(const sel of ['[data-testid=\"stMain\"]','section.main','[data-testid=\"stAppViewContainer\"]']){"
                    "const el=d.querySelector(sel); if(el){el.scrollTo(0,0);}} window.parent.scrollTo(0,0);})();"
                    f"/*{ss.get('wz_step', 0)}-{ss.get('wz_visit', 0)}*/</script>", height=0)


def step_header(n: int, title: str, purpose: str):
    st.subheader(f"Step {n + 1} of {len(STEPS)}: {title}")
    st.markdown(f"<div style='font-size:1.02rem;opacity:.85;margin:-.4rem 0 .8rem'>{purpose}</div>",
                unsafe_allow_html=True)


def nav_buttons(step: int):
    st.divider()
    gaps = missing(step)
    c1, c2, c3 = st.columns([1, 3, 1])
    if step > 0 and c1.button("← Back", use_container_width=True, key=f"back_{step}"):
        go(step - 1)
        st.rerun()
    if gaps:
        c2.info("Still needed before you continue: " + "; ".join(gaps) + ".")
    if step < RESULTS - 1:
        if c3.button("Next →", type="primary", disabled=bool(gaps), use_container_width=True, key=f"next_{step}"):
            go(step + 1)
            st.rerun()


def recipe_columns_table(recipe) -> pd.DataFrame:
    rows = [("Outcome", recipe.get("outcome"))]
    if recipe.get("denominator"):
        rows.append(("Denominator", recipe["denominator"]))
    rows += [("Control", c) for c in recipe.get("controls") or []]
    rows += [("Placebo", p) for p in recipe.get("placebo") or []]
    return pd.DataFrame([{"Role": r, "Column": d.get("column", ""), "What it is": d.get("definition", "")}
                         for r, d in rows if d])


def export_help(client_rec, recipe):
    """What to export for this recipe, plus the export query if the client has one."""
    if not recipe:
        return
    st.markdown("**Columns this recipe needs** (name them like this and the app fills everything in for you):")
    st.dataframe(recipe_columns_table(recipe), hide_index=True, use_container_width=True)
    q = (client_rec.get("data_source") or {}).get("export_query")
    if q and (ROOT / q).exists():
        st.download_button(f"Download the export query ({Path(q).name})", (ROOT / q).read_text(),
                           file_name=Path(q).name, key=key("dlq"))
        st.caption("Run it in BigQuery (edit the date range first), save the result as CSV and upload it in step 4.")


# ------------------------------------------------------------------ steps
def step_start():
    step_header(0, "What are you checking?",
                "This tool checks whether a test winner's effect is still there now it's live for everyone. "
                "Start by picking the client and the kind of change. That loads a <b>recipe</b>: the agreed metrics "
                "to use, so you don't have to work them out.")
    s = S()
    mode = st.radio("How would you like to start?",
                    ["A new check", "Try an example first", "Re-open saved settings"],
                    index=["A new check", "Try an example first", "Re-open saved settings"].index(s.get("_mode", "A new check")),
                    horizontal=True, key=key("mode"))
    s["_mode"] = mode
    if mode == "Try an example first":
        ex = st.selectbox("Example", list(EXAMPLES), key=key("ex"))
        st.caption("Examples fill in every step with real or realistic data, so you can click through a complete check.")
        if st.button("Load this example", type="primary", key=key("loadex")):
            reset({**EXAMPLES[ex], "_mode": mode})
            st.rerun()
        return
    if mode == "Re-open saved settings":
        f = st.file_uploader("Settings file (JSON, downloaded from a previous run)", type=["json"], key=key("cfg"))
        if f is not None and st.button("Load these settings", type="primary", key=key("loadcfg")):
            try:
                reset({**json.load(f), "_mode": mode})
                st.success("Settings loaded. You'll need to upload the same data file in step 4.")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Couldn't read the settings file: {e}")
        return

    recipes_all, err = load_recipes()
    if err:
        st.error(f"A recipe file couldn't be read, so recipes are unavailable: {err}")
    clients = ["(no recipe: I'll choose the metrics myself)"] + list(recipes_all)
    c1, c2 = st.columns(2)
    rc = c1.selectbox("Client", clients, index=clients.index(s["recipe_client"]) if s.get("recipe_client") in clients else 0,
                      key=key("rc"))
    if rc not in recipes_all:
        s["recipe_client"], s["recipe_id"] = None, None
        s["client"] = c2.text_input("Client name (for the report)", s.get("client", ""), key=key("client0"))
        st.info("Without a recipe you'll pick the outcome, controls and placebo yourself. The **Guide** tab explains how.")
        return
    client_rec = recipes_all[rc]
    rlist = client_rec.get("recipes") or []
    ids = [r["id"] for r in rlist]
    rid = c2.selectbox("Where on the site was the change?", ids,
                       index=ids.index(s["recipe_id"]) if s.get("recipe_id") in ids else 0,
                       format_func=lambda i: next(r["name"] for r in rlist if r["id"] == i), key=key("rid"))
    recipe = next(r for r in rlist if r["id"] == rid)
    if s.get("recipe_client") != rc or s.get("recipe_id") != rid:          # new recipe: load its defaults
        cols = rcp.recipe_columns(recipe)
        s.update({"recipe_client": rc, "recipe_id": rid, "client": client_rec["client"], "outcome": cols["outcome"],
                  "denominator": cols["denominator"], "candidates": cols["controls"], "placebo": cols["placebo"],
                  "controls": [], "ratios": [], "controls_as_rate": bool(recipe.get("controls_as_rate")),
                  "recipe_ratios": [c.split(" / ", 1) for c in cols["controls"] + cols["placebo"] if " / " in c]})
    if not recipe.get("verified"):
        st.caption("⚠️ This recipe hasn't been verified by the account team yet. Use it, but sense-check the results.")
    st.markdown(f"**Use this recipe for:** {recipe.get('use_when', '')}")
    export_help(client_rec, recipe)
    with st.expander("Full recipe details (why each series, cautions, known data issues)"):
        for label, d in [("Outcome", recipe.get("outcome")), ("Denominator", recipe.get("denominator"))] + \
                [("Control", c) for c in recipe.get("controls") or []] + [("Placebo", p) for p in recipe.get("placebo") or []]:
            if d:
                st.markdown(f"**{label}: `{d.get('column', '')}`**: {d.get('definition', '')}")
                for f_ in ("why", "cautions", "how_to_export"):
                    if d.get(f_):
                        st.markdown(f"&nbsp;&nbsp;&nbsp;*{f_.replace('_', ' ').capitalize()}:* {d[f_]}")
        for f_, lab in (("placebo_note", "Placebo"), ("typical_detectable_effect", "Typical detectable effect"),
                        ("notes", "Notes")):
            if recipe.get(f_):
                st.markdown(f"**{lab}:** {recipe[f_]}")
        ds = client_rec.get("data_source") or {}
        if ds.get("notes"):
            st.markdown(f"**Data source:** {ds.get('tool', '')}. {ds['notes']}")


def step_test():
    step_header(1, "About the test",
                "Tell the tool which test this was and what it found. The test result is what we'll compare the "
                "live performance against.")
    s = S()
    c1, c2 = st.columns(2)
    s["name"] = c1.text_input("Test name", s.get("name", ""), key=key("name"), placeholder="e.g. Basket stuffed crust upsell")
    s["client"] = c2.text_input("Client", s.get("client", ""), key=key("client"))
    c1, c2, c3 = st.columns(3)
    s["test_ticket"] = c1.text_input("Test ticket (optional)", s.get("test_ticket", ""), key=key("tt"), placeholder="e.g. EXP-255")
    s["release_ticket"] = c2.text_input("Release ticket (optional)", s.get("release_ticket", ""), key=key("rt"))
    s["primary_metric"] = c3.text_input("Test's primary metric (optional)", s.get("primary_metric", ""), key=key("pm"),
                                        help="As written in the test readout. Used in the report only.")

    st.markdown("##### What did the test find?")
    tested = st.radio("Was this change A/B tested?", ["Yes", "No, it was released without a test"],
                      index=0 if s.get("lift_known", True) else 1, horizontal=True, key=key("lk"))
    s["lift_known"] = tested == "Yes"
    if s["lift_known"]:
        c1, c2 = st.columns(2)
        s["test_lift"] = c1.number_input("Test result: % change in the primary metric (winner vs control)",
                                         value=float(s.get("test_lift") or 0.0), step=0.5, key=key("tl"),
                                         help="+2.4 for a 2.4% uplift, -40 for a 40% reduction.")
        tw = s.get("test_window")
        dflt = tuple(_d(x, date.today()) for x in tw) if tw else ()
        rng = c2.date_input("Test start and end dates", dflt, format="DD/MM/YYYY", key=key("tw"),
                            help="These weeks are left out of the 'before' period: during the test only some "
                                 "visitors saw the change.")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            s["test_window"] = [str(rng[0]), str(rng[1])]

        reach = st.radio("Does the outcome you'll analyse only count people who could see the change?",
                         ["Yes, everyone in it could see the change", "No, it includes people who couldn't"],
                         index=0 if int(s.get("exposure", 100)) == 100 else 1, horizontal=True, key=key("reach"))
        if reach.startswith("Yes"):
            s["exposure"] = 100
        else:
            s["exposure"] = st.slider("Roughly what share of it could see the change? (%)", 1, 99,
                                      min(int(s.get("exposure", 50)), 99), key=key("exp"))
            st.caption(f"The effect we'd expect is diluted: {s.get('test_lift', 0):+.1f}% × {s['exposure']}% = "
                       f"{float(s.get('test_lift') or 0) * s['exposure'] / 100:+.1f}%.")

        with st.expander("Recommended: the control group's figure from the test readout"):
            st.markdown("The tool compares your export with the test's own control-group figure over the test weeks. "
                        "This catches the commonest mistake: exporting a slightly different metric from the test's.")
            unit_keys = list(chk.UNITS)
            c1, c2, c3 = st.columns(3)
            s["control_unit"] = c1.selectbox("What kind of figure is it?", unit_keys, format_func=lambda u: chk.UNITS[u],
                                             index=unit_keys.index(s.get("control_unit", "rate_pct")), key=key("cu"))
            s["control_value"] = c2.number_input("Control group's figure", min_value=0.0,
                                                 value=float(s.get("control_value") or 0.0), step=0.01, format="%.4f",
                                                 key=key("cv"), help="e.g. 70.86 for a 70.86% conversion rate.")
            if s["control_unit"] == "weekly_count":
                s["control_share"] = c3.slider("Control group's share of traffic (%)", 1, 100,
                                               int(s.get("control_share", 50)), key=key("cs"))
    else:
        s["test_window"] = None
        st.info("Without a test result the tool still measures the change, but can't say whether it matches what "
                "was expected.")


def step_live():
    step_header(2, "When did users first see the change?",
                "This is the most important date in the check. If it's wrong, the tool looks for the effect in the "
                "wrong place.")
    s = S()
    client_rec, _ = current_recipe()
    ran = st.radio("After the test, did the winner run at 100% in the testing tool (Monetate, Target, WTO) before it "
                   "was built into the site?", ["Yes", "No", "Not sure"],
                   index=["Yes", "No", "Not sure"].index(s.get("ran_100", "No")), horizontal=True, key=key("r100"))
    s["ran_100"] = ran
    c1, c2 = st.columns(2)
    if ran == "Yes":
        s["date_100"] = str(c1.date_input("Date it went to 100% in the testing tool",
                                          _d(s.get("date_100") or s.get("release_date"), date.today() - timedelta(days=120)),
                                          format="DD/MM/YYYY", key=key("d100")))
        s["release_date"] = str(c2.date_input("Release date, if known (for the report)",
                                              _d(s.get("release_date"), _d(s["date_100"], date.today())),
                                              format="DD/MM/YYYY", key=key("rd")))
    else:
        s["release_date"] = str(c1.date_input("Release date (when it went live on the site)",
                                              _d(s.get("release_date"), date.today() - timedelta(days=120)),
                                              format="DD/MM/YYYY", key=key("rd")))
    if ran == "Not sure":
        st.warning("Please find out before relying on the result. Winners are often switched to 100% in the testing "
                   "tool while waiting for development. If so, users saw the change from that date, not the release.")
    cd, reason = change_date_info()
    st.success(f"**Change date used: {cd:%A %d %B %Y}** ({reason}).")

    mon_client = ((client_rec or {}).get("data_source") or {}).get("monetate_client")
    if mon_client:
        with st.expander("Look up the dates in Monetate"):
            from impact_tool import monetate as mon
            creds = mon.get_credentials(mon_client)
            if creds is None:
                st.info(f"Monetate isn't connected yet. An admin adds an API key to the app's Secrets under "
                        f"[monetate.{mon_client}] (see docs/monetate.md).")
            else:
                q = st.text_input("Experience name contains (e.g. 283)", key=key("monq"))
                if q and st.button("Search Monetate", key=key("mons")):
                    try:
                        ss["mon_table"] = mon.experiences_table(mon.fetch_experiences(creds, q))
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Couldn't read Monetate: {e}")
                if isinstance(ss.get("mon_table"), pd.DataFrame):
                    st.dataframe(ss["mon_table"], hide_index=True, use_container_width=True)
                    st.caption("A '100% experience' has one variant getting all traffic: its start date is usually the "
                               "date to enter above. If the test experience itself was edited to 100%, check 'View "
                               "Experience History' in Monetate.")
    if client_rec and client_rec.get("release_process"):
        with st.expander(f"How to find the date for {client_rec['client']}"):
            st.markdown(client_rec["release_process"])

    with st.expander("Advanced: leave out other weeks (outages, tracking breaks, peaks)"):
        st.caption("The test weeks are already left out. Add a row for each other period to ignore.")
        base = pd.DataFrame(s.get("extra_exclude") or [], columns=["start", "end", "reason"])
        base["start"], base["end"] = pd.to_datetime(base["start"]), pd.to_datetime(base["end"])
        ed = st.data_editor(base, num_rows="dynamic", use_container_width=True,
                            key=f"{key('xe')}_{ss.get('wz_visit', 0)}",
                            column_config={"start": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                           "end": st.column_config.DateColumn(format="DD/MM/YYYY")})
        s["extra_exclude"] = [[str(pd.Timestamp(r["start"]).date()), str(pd.Timestamp(r["end"]).date()),
                               r.get("reason") or ""] for _, r in ed.dropna(subset=["start", "end"]).iterrows()]


def step_data():
    step_header(3, "Upload your data",
                "One CSV with a date column and one column per series (daily or weekly rows). Then tell the tool "
                "which column is the metric to check.")
    s = S()
    client_rec, recipe = current_recipe()
    if recipe:
        with st.expander("What to export for this recipe", expanded=not (s.get("csv_bytes") or s.get("file"))):
            export_help(client_rec, recipe)
    else:
        explain("What should I export?", (GUIDE / "02_choosing_the_outcome.md").read_text())
    up = st.file_uploader("CSV file", type=["csv"], key=key("csv"))
    if up is not None and up.getvalue() != s.get("csv_bytes"):
        s["csv_bytes"], s["csv_name"], s["file"] = up.getvalue(), up.name, None
        ss.pop("scores", None)
    dv = derived()
    if dv is None:
        st.info("Upload a CSV to continue.")
        return
    if dv.get("error"):
        st.error(dv["error"])
        return
    wf = dv["weekly_full"]
    st.success(f"Using **{s.get('csv_name') or Path(s.get('file', '')).name}**: {len(wf)} weeks from "
               f"{wf.index.min():%d %b %Y} to {wf.index.max():%d %b %Y}, {len(dv['numeric'])} numeric columns.")

    numeric = dv["numeric"]
    c1, c2 = st.columns(2)
    s["outcome"] = c1.selectbox("Metric to check (the outcome)", numeric, index=numeric.index(dv["outcome"]),
                                key=key("out"), help="A count such as orders or clicks, as close to the change as possible.")
    den_opts = ["(none: analyse the count)"] + [c for c in numeric if c != s["outcome"]]
    cur = dv["denom"] if dv["denom"] in den_opts else den_opts[0]
    pick = c2.selectbox("Divide it by (recommended)", den_opts, index=den_opts.index(cur), key=key("den"),
                        help="The traffic the outcome comes from, e.g. visits to the page with the change. A rate "
                             "removes swings in traffic.")
    s["denominator"] = None if pick.startswith("(none") else pick
    dv = derived()

    with st.expander("Advanced: date labelling and ratio series"):
        conv_keys = list(WEEK_CONVENTIONS)
        s["convention"] = st.selectbox("How are the dates labelled?", conv_keys, index=conv_keys.index(dv["convention"]),
                                       format_func=lambda c: WEEK_CONVENTIONS[c] + (" (detected)" if c == dv["detected"] else ""),
                                       key=key("conv"), help="Getting this wrong shifts every week by up to 6 days.")
        if dv["ratios"]:
            st.caption("Ratio series created" + (" from the recipe" if s.get("recipe_ratios") else "") + ": "
                       + ", ".join(f"`{a} / {b}`" for a, b in dv["ratios"]))
        n_r = st.number_input("Ratio series (e.g. orders ÷ visits for a group that couldn't see the change)", 0, 5,
                              len(dv["ratios"]), key=key("nr"))
        ratios = []
        for i in range(int(n_r)):
            d0 = dv["ratios"][i] if i < len(dv["ratios"]) else [numeric[0], numeric[-1]]
            r1, r2 = st.columns(2)
            a_ = r1.selectbox(f"Ratio {i + 1}: top", numeric, index=numeric.index(d0[0]) if d0[0] in numeric else 0, key=key(f"rn{i}"))
            b_ = r2.selectbox(f"Ratio {i + 1}: bottom", numeric, index=numeric.index(d0[1]) if d0[1] in numeric else 0, key=key(f"rb{i}"))
            if a_ != b_:
                ratios.append([a_, b_])
        s["ratios"] = ratios
    dv = derived()

    st.markdown("##### Automatic data checks")
    weekly = dv["weekly_full"][[dv["outcome"]] + ([dv["denom"]] if dv["denom"] else [])]
    for n in dv["notes"]:
        st.caption("ℹ️ " + n)
    flags = quality_flags(weekly)
    if len(flags):
        with st.expander(f"⚠️ {len(flags)} sudden jump(s) in your data: check these aren't tracking breaks"):
            st.markdown("Jumps of more than 50% week to week are often tracking problems. If so, leave those weeks out "
                        "(step 3, Advanced) or fix the export.")
            st.dataframe(flags.assign(week=flags["week"].dt.strftime("%d %b %Y")), use_container_width=True, hide_index=True)
    if client_rec:
        warns = rcp.date_warnings(client_rec, weekly[dv["outcome"]].first_valid_index(),
                                  weekly[dv["outcome"]].last_valid_index(), s.get("recipe_id"))
        if warns:
            with st.expander(f"⚠️ {len(warns)} known data issue(s) for {client_rec['client']} in your date range"):
                for w_ in warns:
                    st.markdown("- " + w_)
    cov = chk.coverage(weekly, dv["outcome"])
    if cov.status != "ok":
        st.warning("**Coverage:** " + cov.message)
    tw = exclusions()[0] if (s.get("lift_known", True) and s.get("test_window")) else None
    recon = chk.reconcile(weekly, dv["outcome"], dv["denom"], list(tw) if tw else None, s.get("control_value") or None,
                          s.get("control_unit", "rate_pct"), int(s.get("control_share", 50)) / 100)
    {"ok": st.success, "warn": st.warning, "fail": st.error, "skipped": st.info}[recon.status](
        "**Matches the test?** " + recon.message)
    if recon.status in ("warn", "fail"):
        s["recon_ack"] = st.checkbox("I've checked this and the difference is expected", bool(s.get("recon_ack")),
                                     key=key("rack"))
        if s["recon_ack"]:
            s["recon_reason"] = st.text_input("Why is the difference expected?", s.get("recon_reason", ""), key=key("rwhy"))
    else:
        s["recon_ack"], s["recon_reason"] = False, ""


def step_compare():
    step_header(4, "Build the comparison",
                "The tool estimates what the outcome would have done without the change, using <b>control series</b>: "
                "metrics that normally move with it but that the change couldn't touch. Pick candidates, let the tool "
                "score them, then confirm the ones you use are safe.")
    s = S()
    dv = derived()
    if dv is None or dv.get("error"):
        st.warning("Upload your data in step 4 first.")
        return
    client_rec, recipe = current_recipe()
    opts = [c for c in dv["all_series"] if c not in (dv["outcome"], dv["denom"])]
    s["candidates"] = st.multiselect("Candidate control series" + (" (pre-filled from the recipe)" if recipe else ""),
                                     opts, default=dv["candidates"], key=key("cand"),
                                     help="Include every plausible one; the tool checks them next.")
    c1, c2 = st.columns(2)
    with c1:
        explain("How to choose control series", (GUIDE / "03_choosing_controls.md").read_text())
    if dv["denom"]:
        with c2.expander("Advanced: how the controls are compared"):
            s["controls_as_rate"] = st.toggle("Divide the controls by the same denominator as the outcome",
                                              bool(s.get("controls_as_rate")), key=key("asr"),
                                              help="Only when the controls are counts from the same traffic as the "
                                                   "outcome. Recipes set this for you.")
    dv = derived()
    cd, _ = change_date_info()
    ex = exclusions()
    as_rate = bool(s.get("controls_as_rate")) and dv["denom"] is not None
    weekly = dv["weekly_full"][[dv["outcome"]] + ([dv["denom"]] if dv["denom"] else []) + dv["candidates"]]
    frame = model_frame(weekly, Spec(dv["outcome"], dv["denom"], dv["candidates"], pd.Timestamp(cd), ex, as_rate))
    try:
        prep0 = prepare(frame, Spec(dv["outcome"], dv["denom"], dv["candidates"], pd.Timestamp(cd), ex, as_rate))
        s["_n_pre"], s["_n_post"] = prep0.n_pre, prep0.n_post
        msg = f"Usable weeks: **{prep0.n_pre} before** the change and **{prep0.n_post} after**."
        (st.warning if prep0.n_pre < 12 else st.caption)(msg + (" The tool needs at least 12 before." if prep0.n_pre < 12 else ""))
    except Exception as e:  # noqa: BLE001
        st.error(f"Can't use these dates and data together yet: {e}")
        return

    if dv["candidates"]:
        pdf = weekly.copy()
        if dv["denom"]:
            pdf[dv["out_label"]] = pdf[dv["outcome"]] / pdf[dv["denom"]]
        cols = [dv["out_label"]] + dv["candidates"]
        norm = (pdf[cols] / pdf[cols].iloc[:8].mean() * 100).reset_index().melt("week", var_name="series", value_name="index")
        chart_box = st.expander("See how the candidates move compared with the outcome", expanded=False)
        chart_box.altair_chart(alt.layer(
            alt.Chart(norm).mark_line().encode(x=alt.X("week:T", title=None), y=alt.Y("index:Q", title="Index (first 8 weeks = 100)"),
                                               color=alt.Color("series:N", legend=alt.Legend(orient="top", title=None))),
            alt.Chart(pd.DataFrame({"d": [pd.Timestamp(cd)]})).mark_rule(color="#C0392B", strokeWidth=2).encode(x="d:T"),
        ).properties(height=240), use_container_width=True)
        chart_box.caption("Good controls follow the outcome's ups and downs before the red line (the change date).")

        skey = (dv["outcome"], dv["denom"], tuple(dv["candidates"]), str(cd), tuple(map(str, ex)), as_rate, dv["convention"])
        if st.button("Score the candidates", type="primary", key=key("score")):
            with st.spinner("Backtesting each candidate…"):
                try:
                    ss["scores"] = cached_screen(frame, dv["outcome"], dv["denom"], tuple(dv["candidates"]),
                                                 pd.Timestamp(cd), tuple(ex), as_rate)
                    ss["scores_key"] = skey
                    s["controls"] = [x.name for x in ss["scores"] if x.suggested]
                except ValueError as e:
                    st.error(str(e))
        scores = ss.get("scores") if ss.get("scores_key") == skey else None
        if scores:
            st.dataframe(scores_table(scores), use_container_width=True, hide_index=True)
            st.caption("✅ Suggested = makes the forecast better and didn't jump at the change date. Forecast improvement "
                       "is the key column.")
        s["controls"] = st.multiselect("Control series to use", dv["candidates"],
                                       default=[c for c in s.get("controls") or [] if c in dv["candidates"]],
                                       key=f"{key('ctrl')}_{len(s.get('controls') or [])}_{bool(scores)}",
                                       help="Usually 1–3 good ones. The tool blends them automatically.")
    controls = [c for c in s.get("controls") or [] if c in dv["candidates"]]
    if not controls:
        st.info("No controls selected: the comparison line will just be the outcome's average before the change. "
                "That's much weaker, so only do this if no reasonable control exists.")
    else:
        st.markdown("##### Is each control safe? (required)")
        st.caption("The tool can't know how the site works, so it needs your judgement. Answers go in the report.")
        s.setdefault("checklist", {})
        problems = []
        for c in controls:
            ans = s["checklist"].setdefault(c, {})
            with st.container(border=True):
                st.markdown(f"**{c}**")
                for qk, q in CHECKLIST:
                    opts_ = ["Yes", "No", "Not sure"]
                    a_ = st.radio(q, opts_, index=opts_.index(ans[qk]) if ans.get(qk) in opts_ else None,
                                  horizontal=True, key=key(f"chk_{c}_{qk}"))
                    if a_:
                        ans[qk] = a_
                        if a_ != SAFE_ANSWER[qk]:
                            problems.append(f"**{c}**: {q.split('?')[0]}? (*{a_}*)")
        if problems:
            st.warning("These answers suggest a control may not be safe. Consider removing it:\n\n"
                       + "\n".join(f"- {p}" for p in problems))

    st.markdown("##### Placebo check (optional)")
    if recipe and recipe.get("placebo_note"):
        st.caption("Recipe advice: " + recipe["placebo_note"])
    st.caption("A metric the change couldn't affect, but that would move if something else happened the same week. "
               "Leave it empty if nothing fits; the report will say it wasn't checked.")
    popts = [c for c in dv["weekly_full"].columns if c not in [dv["outcome"], dv["denom"]] + controls]
    s["placebo"] = st.multiselect("Placebo metric(s)", popts, default=[p for p in s.get("placebo") or [] if p in popts],
                                  key=key("plc"))
    if s["placebo"] and dv["denom"]:
        s["placebo_per_denominator"] = st.toggle("Divide the placebo by the same denominator",
                                                 bool(s.get("placebo_per_denominator")), key=key("ppd"))


def step_run():
    step_header(5, "Check and run",
                "Check the summary, then lock the plan and run. Locking records every setting, so anyone reviewing "
                "later can see exactly what was decided before the result was known.")
    s = S()
    dv = derived()
    if dv is None or dv.get("error"):
        st.warning("Upload your data in step 4 first.")
        return
    cd, reason = change_date_info()
    exp_txt = (f"{float(s.get('test_lift') or 0):+.1f}%" + (f" × {s.get('exposure')}% reach" if int(s.get('exposure', 100)) < 100 else "")
               if s.get("lift_known", True) else "not tested")
    rows = [("Test", f"{s.get('name', '')} {('· ' + s['test_ticket']) if s.get('test_ticket') else ''}", 1),
            ("Test result", exp_txt, 1),
            ("Change date", f"{cd:%d %b %Y} ({reason})", 2),
            ("Data", f"{s.get('csv_name') or Path(s.get('file', '') or '').name}", 3),
            ("Outcome", dv["out_label"], 3),
            ("Controls", ", ".join(dv["controls"]) or "none", 4),
            ("Placebo", ", ".join(s.get("placebo") or []) or "none", 4)]
    for label, val, stp in rows:
        c1, c2, c3 = st.columns([1.2, 4, 0.8])
        c1.markdown(f"**{label}**")
        c2.markdown(val or "—")
        if c3.button("Edit", key=f"edit_{label}"):
            go(stp)
            st.rerun()

    with st.expander("Advanced: length of the window after the change"):
        n_pre, n_post = s.get("_n_pre", 0), s.get("_n_post", 0)
        sug = suggest_window(n_pre, n_post) if n_pre and n_post else 8
        win_opts = sorted({h for h in (8, 13, 26, 52) if h <= max(n_post, 8)} | {sug})
        cur = int(s.get("primary") or sug)
        s["primary"] = st.select_slider("Weeks after the change used for the verdict", options=win_opts,
                                        value=cur if cur in win_opts else sug, key=key("win"))
        st.caption(f"Suggested: {sug} weeks (the longest that's no more than half the {n_pre} weeks of history).")

    st.markdown("##### Who's it for?")
    c1, c2 = st.columns(2)
    purposes = ["Internal check", "Client-facing"]
    s["purpose"] = c1.radio("Purpose", purposes, index=purposes.index(s.get("purpose", "Internal check")), horizontal=True,
                            key=key("purpose"), help="Client-facing results need a second person to review them.")
    s["author"] = c2.text_input("Your name", s.get("author", ""), key=key("author"))
    if s["purpose"] == "Client-facing":
        st.caption("After the run you'll download a review pack for a colleague to check in the **Review** tab.")

    gaps = missing(5) + [g for i in range(1, 5) for g in missing(i)]
    if gaps:
        st.info("Still needed: " + "; ".join(gaps) + ".")
    if st.button("🔒 Lock plan and run", type="primary", disabled=bool(gaps), key=key("run")):
        settings = build_settings(dv)
        ss["locked"] = {"settings_json": json.dumps(settings, sort_keys=True, default=str), "author": s["author"].strip(),
                        "purpose": s["purpose"], "locked_at": datetime.now().isoformat(timespec="seconds"), "logged": False}
        go(RESULTS)
        st.rerun()


def results_page():
    lk = ss.get("locked")
    dv = derived()
    if not lk or dv is None:
        st.info("Run a check first.")
        return
    settings = json.loads(lk["settings_json"])
    if json.dumps(build_settings(dv), sort_keys=True, default=str) != lk["settings_json"]:
        st.warning("You've changed some answers since this run. These results are for the locked plan; go to "
                   "**Check & run** to run again with your changes.")
    try:
        with st.spinner("Running the analysis, data checks, placebo and robustness alternatives…"):
            res = cached_pipeline(dv["df"], dv["date_col"], lk["settings_json"])
    except (ValueError, KeyError) as e:
        st.error(str(e))
        return
    fp = plan_mod.fingerprint(res.weekly_full)
    plan = plan_mod.make_plan(settings, fp, lk["author"], lk["purpose"])
    plan["locked_at"] = lk["locked_at"]
    a, verdict, expected, w = res.analysis, res.verdict, res.expected, res.analysis.primary
    rob = res.robustness
    out_label = res.out_label
    if not lk["logged"]:
        lk["logged"] = True
        ss.setdefault("run_log", []).append({
            "time": lk["locked_at"][11:], "plan ID": plan["plan_id"], "outcome": out_label,
            "controls": ", ".join(settings["controls"]) or "none", "placebo": ", ".join(settings["placebo"]) or "none",
            "change date": settings["change_date"], "window": w.weeks, "effect": f"{w.effect:+.1%}",
            "p-value": f"{w.p_value:.3f}", "robustness": rob.rating if rob else "", "verdict": verdict.label})
    for msg in res.warnings:
        st.warning(msg)

    st.subheader(f"Result: {settings.get('name') or 'Untitled'}")
    box = {"green": st.success, "amber": st.warning, "red": st.error, "grey": st.info}[verdict.colour]
    box(f"### Verdict: {verdict.label}\n{verdict.headline}")
    st.caption(f"Plan ID **{plan['plan_id']}** · {lk['purpose']} · analyst: {lk['author'] or 'not given'} · locked {plan['locked_at']}")
    if lk["purpose"] == "Client-facing":
        st.warning("**Not yet reviewed: not for client use.** Download the review pack below and ask a colleague to "
                   "review it in the Review tab.")
    m1, m2, m3 = st.columns(3)
    m1.metric("Expected if the test held", "n/a" if expected is None else f"{expected:+.1%}")
    m2.metric(f"Measured ({w.label.lower()})", f"{w.effect:+.1%}",
              help="Plausible range: " + ("no lower limit" if w.lo_unbounded else f"{w.lo:+.1%}") + " to "
                   + ("no upper limit" if w.hi_unbounded else f"{w.hi:+.1%}") + f" · p-value {w.p_value:.3f}")
    m3.metric("Smallest detectable effect", f"±{w.mde(expected):.0%}",
              help="Changes smaller than this would usually be missed with this data.")
    summary = plain_english(a, verdict, expected, out_label)
    st.markdown(summary)

    icon = {"ok": "✅", "warn": "⚠️", "fail": "❌", "skipped": "➖"}
    rob_icon = {"Robust": "✅", "Somewhat sensitive": "⚠️", "Fragile": "❌"}.get(rob.rating if rob else "", "➖")
    with st.container(border=True):
        st.markdown("**Checks:** " + "  ".join(f"{icon[c_.status]} {c_.name}" for c_ in res.data_checks)
                    + ("  ·  " + "  ".join(f"{'⚠️' if p_.window.significant else '✅'} Placebo '{p_.metric}'" for p_ in res.placebos)
                       if res.placebos else "  ·  ➖ Placebo not checked")
                    + f"  ·  {rob_icon} Robustness: {rob.rating if rob else 'n/a'}")
        with st.expander("Details of the checks and why this verdict"):
            for c_ in res.data_checks:
                st.markdown(f"{icon[c_.status]} **{c_.name}.** {c_.message}")
            for p_ in res.placebos:
                st.markdown(f"{'⚠️' if p_.window.significant else '✅'} **Placebo '{p_.metric}'.** {p_.window.effect:+.1%} "
                            f"(p = {p_.window.p_value:.3f})")
            st.markdown("**Why this verdict**")
            for d_ in verdict.details:
                st.markdown(f"- {d_}")

    c_imp = impact_chart(a, pd.Timestamp(settings["change_date"]), out_label, res.spec.exclude)
    st.altair_chart(c_imp, use_container_width=True)
    st.caption("Navy: what happened. Orange dashed: what we'd expect without the change. Before the red line they "
               "should move together; after it, a lasting gap is the effect.")

    # downloads up front
    meta = {"name": settings["name"], "client": settings["client"], "test_ticket": settings["test_ticket"],
            "release_ticket": settings["release_ticket"], "primary_metric": settings["primary_metric"],
            "test_lift_text": f"{settings['test_lift']:+.1f}%" if settings["lift_known"] else "not provided",
            "change_date": pd.Timestamp(settings["change_date"]).strftime("%d %b %Y"),
            "change_date_reason": settings["change_date_reason"], "outcome_desc": out_label,
            "exposure": f"{settings['exposure']}%"}
    c_gap, c_blk = gap_chart(a, pd.Timestamp(settings["change_date"])), block_chart(a)
    c_rob = robustness_chart(rob) if rob else None
    md = markdown_report(meta, verdict, a, expected, settings["checklist_answers"], res.notes, ss["run_log"], summary,
                         data_checks=res.data_checks, placebos=res.placebos, recipe=res.recipe_label,
                         plan_block=plan_mod.review_block_md(None, plan), robustness=rob)
    charts = {"Actual vs comparison line": c_imp, "Weekly gap": c_gap, "Is the post-change stretch unusual?": c_blk}
    if c_rob is not None:
        charts["Robustness"] = c_rob
    fname = (settings["test_ticket"] or settings["name"] or "impact").replace(" ", "_")
    pack = plan_mod.make_pack(plan, result_summary(res), md, ss["run_log"])
    st.markdown("##### Download")
    d1, d2, d3, d4 = st.columns(4)
    d1.download_button("Report (HTML)", html_report(md, charts, verdict), file_name=f"{fname}_post_release_impact.html",
                       mime="text/html", type="primary", use_container_width=True)
    d2.download_button("Review pack (for a colleague)", json.dumps(pack, indent=2, default=str),
                       file_name=f"{fname}_review_pack_{plan['plan_id']}.json", use_container_width=True)
    d3.download_button("Settings (to re-open later)", json.dumps({**settings, "purpose": lk["purpose"], "author": lk["author"]},
                                                                 indent=2, default=str),
                       file_name=f"{fname}_settings.json", use_container_width=True)
    d4.download_button("Weekly data (CSV)", a.weekly.to_csv(), file_name=f"{fname}_weekly.csv", use_container_width=True)
    with st.expander("More downloads"):
        st.download_button("Report (Markdown)", md, file_name=f"{fname}_post_release_impact.md")

    st.markdown("##### More detail")
    with st.expander("Robustness: does the conclusion survive other reasonable choices?"):
        if rob:
            {"Robust": st.success, "Somewhat sensitive": st.warning, "Fragile": st.error}.get(rob.rating, st.info)(
                f"**{rob.rating}.** {rob.summary}")
            st.altair_chart(c_rob, use_container_width=True)
            st.dataframe(robustness_display(rob), use_container_width=True, hide_index=True)
    with st.expander("Weekly gap and how unusual the post-change stretch is"):
        st.altair_chart(c_gap, use_container_width=True)
        st.caption("Bars: % gap between actual and comparison each week. Before the change they should wobble around zero.")
        st.altair_chart(c_blk, use_container_width=True)
        st.caption(f"The p-value ({w.p_value:.3f}) is the share of grey dots (every other {w.weeks}-week stretch) at least "
                   "as far from zero as the orange one (after the change).")
    with st.expander("Results by window"):
        st.dataframe(windows_table(a, expected), use_container_width=True, hide_index=True)
    with st.expander("How good is the comparison line?"):
        d = a.diagnostics
        c1, c2, c3 = st.columns(3)
        c1.metric("Typical forecast error", f"±{d.backtest_error:.1%}", f"vs ±{d.backtest_error_no_controls:.1%} without controls",
                  delta_color="off")
        c2.metric("Weekly variation explained", "n/a" if np.isnan(d.fit_r2) else f"{max(d.fit_r2, 0):.0%}")
        c3.metric("Drift before the change", f"{d.drift_per_year:+.1%} / year", "⚠️ check" if d.drift_flag else "OK",
                  delta_color="off")
        for n in d.notes:
            st.warning(n)
        bt = blend_table(a)
        if len(bt):
            st.dataframe(bt, use_container_width=True, hide_index=True)
        if len(a.leave_one_out):
            st.dataframe(a.leave_one_out, use_container_width=True, hide_index=True)
        if len(a.prep.dropped):
            st.dataframe(a.prep.dropped.assign(week=a.prep.dropped["week"].dt.strftime("%d %b %Y")),
                         use_container_width=True, hide_index=True)
    with st.expander("Analysis history (this session)"):
        st.dataframe(pd.DataFrame(ss["run_log"]), use_container_width=True, hide_index=True)
        st.caption("Every run is logged and included in the report, so reviewers can see if settings changed after "
                   "seeing results.")

    st.divider()
    c1, c2 = st.columns(2)
    if c1.button("← Change settings and re-run", use_container_width=True, key="res_back"):
        go(5)
        st.rerun()
    if c2.button("Start a new check", use_container_width=True, key="res_new"):
        reset()
        st.rerun()


# ------------------------------------------------------------------ entry point
def render():
    ss.setdefault("wz_step", 0)
    ss.setdefault("wz_max", 0)
    step = ss["wz_step"]
    scroll_to_top()
    if step == 0:
        st.title("📈 Post-release impact checker")
        st.markdown("**Did a test winner's benefit hold once it was built into the site?** Answer six short steps "
                    "and the tool tells you in plain English.")
        explain("New to this? Read this first (2 minutes)", (GUIDE / "01_start_here.md").read_text())
    else:
        name = S().get("name") or "New check"
        st.markdown(f"<div style='font-size:1.35rem;font-weight:700;margin:.2rem 0 .4rem'>📈 Post-release impact "
                    f"checker <span style='font-weight:400;opacity:.65'>· {name}</span></div>", unsafe_allow_html=True)
    progress()
    with st.container(border=True):
        [step_start, step_test, step_live, step_data, step_compare, step_run, results_page][step]()
    if step < RESULTS:
        nav_buttons(step)

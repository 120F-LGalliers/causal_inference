"""120Feet post-release impact checker (Streamlit), v2.

Did a test winner's effect hold once it was built into the site?
Run with:  streamlit run app.py
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from impact_tool import (CHECKLIST, SAFE_ANSWER, WEEK_CONVENTIONS, Spec, analyse, load_csv, make_verdict,
                         model_frame, quality_flags, scores_table, screen, to_weekly)
from impact_tool.conformal import prepare, suggest_window
from impact_tool.data import detect_convention
from impact_tool.report import (blend_table, block_chart, gap_chart, html_report, impact_chart, markdown_report,
                                plain_english, windows_table)
from impact_tool import checks as chk
from impact_tool import plan as plan_mod
from impact_tool import recipes as rcp
from impact_tool.pipeline import result_summary, run_pipeline
from impact_tool.report import robustness_chart
from impact_tool.robustness import robustness_display

ROOT = Path(__file__).parent
GUIDE = ROOT / "docs" / "guide"
ss = st.session_state

EXAMPLES = {
    "TM EAOA-1541: forgotten username copy (effect held)": {
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

st.set_page_config(page_title="Post-release impact checker", page_icon="📈", layout="wide")


def explain(title: str, body: str, expanded: bool = False):
    with st.expander(f"ℹ️ {title}", expanded=expanded):
        st.markdown(body)


@st.cache_data(show_spinner=False)
def cached_screen(frame, outcome, denom, candidates, change, exclude, as_rate):
    spec = Spec(outcome, denom, list(candidates), pd.Timestamp(change), list(exclude), as_rate)
    return screen(frame, spec, list(candidates))


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
def cached_analyse(frame, outcome, denom, controls, change, exclude, as_rate, primary):
    spec = Spec(outcome, denom, list(controls), pd.Timestamp(change), list(exclude), as_rate)
    return analyse(frame, spec, primary=primary)


tab_run, tab_review, tab_guide, tab_recipes, tab_valid = st.tabs(
    ["▶️ Run a check", "🔍 Review", "📘 Guide", "🧾 Data recipes", "✅ How reliable is it?"])

# =============================================================== GUIDE TABS
with tab_guide:
    pages = sorted(GUIDE.glob("*.md"))
    names = {p: p.stem.split("_", 1)[1].replace("_", " ").capitalize() for p in pages}
    pick = st.radio("Guide sections", pages, format_func=lambda p: names[p], horizontal=True)
    st.markdown(pick.read_text())
with tab_valid:
    st.markdown((ROOT / "docs" / "validation.md").read_text())
with tab_recipes:
    st.markdown((ROOT / "recipes" / "README.md").read_text())
    _all, _err = load_recipes()
    if _err:
        st.error(f"A recipe file couldn't be read: {_err}")
    for _c, _d in _all.items():
        with st.expander(f"{_c}: {len(_d.get('recipes') or [])} recipe(s) · owner: {_d.get('owner') or 'not set'} · "
                         f"last reviewed: {_d.get('last_reviewed') or 'never'}"):
            st.code(open(ROOT / "recipes" / _d["_file"]).read(), language="yaml")

# =============================================================== REVIEW TAB
with tab_review:
    st.title("🔍 Review a check")
    st.markdown("Client-facing results need a **second person** to review them before they're shared. Upload the "
                "analyst's **review pack** and the **same CSV** they used. The tool will:\n\n"
                "1. confirm the pack hasn't been edited and the CSV is exactly the data the analyst used;\n"
                "2. re-run the analysis from the locked plan and confirm the results match exactly;\n"
                "3. show you the results and checks, and walk you through a short review checklist.")
    explain("What should a reviewer look for?", (GUIDE / "08_robustness_and_review.md").read_text())
    c1, c2 = st.columns(2)
    pack_file = c1.file_uploader("Review pack (JSON)", type=["json"], key="rv_pack")
    rv_csv = c2.file_uploader("The analyst's CSV", type=["csv"], key="rv_csv")
    if pack_file is None or rv_csv is None:
        st.info("Upload both files to start the review.")
    else:
        rres = None
        try:
            pack = json.load(pack_file)
            rdf, rdate = load_csv(rv_csv)
            rres = cached_pipeline(rdf, rdate, json.dumps(pack["settings"], sort_keys=True, default=str))
        except Exception as e:  # noqa: BLE001
            st.error(f"Couldn't run the review: {e}")
    if pack_file is not None and rv_csv is not None and rres is not None:
        stg = pack["settings"]
        st.subheader(f"{stg.get('name') or 'Untitled'} · {stg.get('client', '')}")
        st.caption(f"Plan ID {pack.get('plan_id')} · {pack.get('purpose')} · analyst: {pack.get('author') or 'not given'} · "
                   f"locked {pack.get('locked_at')}")
        if pack.get("review"):
            st.info(f"This pack was already reviewed: **{pack['review']['decision']}** by {pack['review']['reviewer']} on "
                    f"{pack['review']['reviewed_at']}.")
        checks_v = plan_mod.verify(pack, plan_mod.fingerprint(rres.weekly_full), result_summary(rres))
        for nm, ok, msg in checks_v:
            (st.success if ok else st.error)(f"{'✅' if ok else '❌'} **{nm}.** {msg}")
        verified = all(ok for _, ok, _ in checks_v)

        rv = rres.verdict
        {"green": st.success, "amber": st.warning, "red": st.error, "grey": st.info}[rv.colour](
            f"### Verdict: {rv.label}\n{rv.headline}")
        rw = rres.analysis.primary
        st.markdown(f"**Effect ({rw.label.lower()}):** {rw.effect:+.1%} · plausible range {rw.lo:+.1%} to {rw.hi:+.1%} · "
                    f"p-value {rw.p_value:.3f} · robustness: **{rres.robustness.rating if rres.robustness else 'n/a'}**")
        with st.expander("Key settings in the plan", expanded=True):
            st.markdown(
                f"- **Outcome:** {rres.out_label}\n- **Controls:** {', '.join(stg.get('controls') or []) or 'none'}\n"
                f"- **Placebo:** {', '.join(stg.get('placebo') or []) or 'none'}\n"
                f"- **Change date:** {stg.get('change_date')} ({stg.get('change_date_reason', '')}); release date "
                f"{stg.get('release_date')}; ran at 100% first: {stg.get('ran_100')}\n"
                f"- **Primary window:** {stg.get('primary')} weeks · **Test result:** "
                f"{stg.get('test_lift') if stg.get('lift_known') else 'n/a'}% · **Share exposed:** {stg.get('exposure')}%\n"
                f"- **Recipe:** {rres.recipe_label or 'none'}\n"
                f"- **Export vs test acknowledged:** {stg.get('recon_ack')} {stg.get('recon_reason') or ''}")
            st.markdown("**Analyst's control checklist answers**")
            st.json(stg.get("checklist_answers") or {})
        with st.expander("Data checks, placebo and robustness", expanded=True):
            icon = {"ok": "✅", "warn": "⚠️", "fail": "❌", "skipped": "➖"}
            for c_ in rres.data_checks:
                st.markdown(f"{icon[c_.status]} **{c_.name}.** {c_.message}")
            for p_ in rres.placebos:
                st.markdown(f"{'⚠️' if p_.window.significant else '✅'} **Placebo '{p_.metric}'.** {p_.window.effect:+.1%} "
                            f"(p = {p_.window.p_value:.3f})")
            if rres.robustness:
                st.markdown(f"**Robustness: {rres.robustness.rating}.** {rres.robustness.summary}")
                st.dataframe(robustness_display(rres.robustness), width="stretch", hide_index=True)
        with st.expander("Analyst's analysis history"):
            st.dataframe(pd.DataFrame(pack.get("run_log") or []), width="stretch", hide_index=True)
            st.caption("Several runs with different settings before the locked plan? Ask why.")
        with st.expander("Full report"):
            st.markdown(pack.get("report_markdown", ""))
        st.altair_chart(impact_chart(rres.analysis, pd.Timestamp(stg["change_date"]), rres.out_label, rres.spec.exclude),
                        width="stretch")

        st.subheader("Your review")
        reviewer = st.text_input("Your name", key="rv_name")
        answers, missing = {}, 0
        for kq, q in plan_mod.REVIEW_CHECKLIST:
            ans = st.radio(q, ["Yes", "No", "Not sure"], index=None, horizontal=True, key=f"rv_{kq}")
            answers[kq] = ans or "unanswered"
            missing += ans is None
        comments = st.text_area("Comments (required if anything is 'No' or 'Not sure')", key="rv_comments")
        decisions = ["Approved", "Changes needed"] if verified else ["Changes needed"]
        decision = st.radio("Decision", decisions, horizontal=True, key="rv_decision")
        if not verified:
            st.error("The pack couldn't be verified, so it can't be approved. Ask the analyst for the exact CSV and an "
                     "unedited pack.")
        problems = []
        if not reviewer.strip():
            problems.append("Add your name.")
        elif reviewer.strip().lower() == (pack.get("author") or "").strip().lower():
            problems.append("The reviewer must be a different person from the analyst.")
        if missing:
            problems.append(f"Answer every checklist question ({missing} left).")
        if any(v in ("No", "Not sure") for v in answers.values()) and not comments.strip():
            problems.append("Add a comment explaining the 'No' or 'Not sure' answers.")
        if decision == "Approved" and any(v == "No" for v in answers.values()):
            problems.append("You can't approve with a 'No' answer. Choose 'Changes needed', or revisit the answer.")
        for pr in problems:
            st.info(pr)
        sig_key = f"signed_{pack.get('plan_id')}"
        if not problems and st.button("Sign review", type="primary"):
            ss[sig_key] = plan_mod.sign(pack, reviewer.strip(), decision, answers, comments.strip())
        if ss.get(sig_key):
            signed = ss[sig_key]
            decision = signed["review"]["decision"]
            plan_view = {k_: pack[k_] for k_ in ("plan_id", "purpose", "author", "locked_at")}
            md_signed = pack.get("report_markdown", "").replace(
                plan_mod.review_block_md(None, plan_view), plan_mod.review_block_md(signed["review"], plan_view))
            ra = rres.analysis
            charts_rv = {"Actual vs comparison line": impact_chart(ra, pd.Timestamp(stg["change_date"]), rres.out_label,
                                                                   rres.spec.exclude),
                         "Weekly gap": gap_chart(ra, pd.Timestamp(stg["change_date"])),
                         "Is the post-change stretch unusual?": block_chart(ra)}
            if rres.robustness:
                charts_rv["Robustness"] = robustness_chart(rres.robustness)
            (st.success if decision == "Approved" else st.warning)(
                f"Review signed: **{decision}**. Download the signed pack and report below and send them back to the analyst.")
            base_name = (stg.get("test_ticket") or stg.get("name") or "impact").replace(" ", "_")
            c1, c2, c3 = st.columns(3)
            c1.download_button("Signed review pack (JSON)", json.dumps(signed, indent=2, default=str),
                               file_name=f"{base_name}_review_pack_{pack['plan_id']}_signed.json")
            c2.download_button("Signed report (HTML)", html_report(md_signed, charts_rv, rv),
                               file_name=f"{base_name}_post_release_impact_reviewed.html", mime="text/html")
            c3.download_button("Signed report (Markdown)", md_signed, file_name=f"{base_name}_post_release_impact_reviewed.md")

# =============================================================== RUN TAB
with tab_run:
    st.title("📈 Post-release impact checker")
    st.markdown("**Did a test winner's benefit hold once it was built into the site?** This tool estimates what your "
                "metric would have done without the change, compares that with what actually happened, and tells you "
                "in plain English whether the effect is still there.")
    explain("New to this? Read this first (2 minutes)", (GUIDE / "01_start_here.md").read_text())

    c1, c2 = st.columns([2, 1])
    example = c1.selectbox("Start from an example (optional)", ["None"] + list(EXAMPLES),
                           help="Examples fill every field so you can see a complete run before using your own data.")
    cfg_file = c2.file_uploader("…or load saved settings (JSON)", type=["json"],
                                help="Settings saved from a previous run (download them at the bottom of the results).")
    cfg: dict = dict(EXAMPLES.get(example, {}))
    if cfg_file is not None:
        try:
            cfg = json.load(cfg_file)
            st.success("Settings loaded. You still need to upload the data file.")
        except Exception as e:  # noqa: BLE001
            st.error(f"Couldn't read the settings file: {e}")
    sig = example + (cfg_file.name if cfg_file else "")
    k = lambda name: f"{name}__{sig}"          # widget keys reset when the example/config changes

    # ------------------------------------------------ step 1
    st.header("1. Client, recipe and test details")
    recipes_all, recipe_err = load_recipes()
    if recipe_err:
        st.error(f"A recipe file couldn't be read, so recipes are unavailable: {recipe_err}")
    st.markdown("**Data recipe** (recommended). A recipe is the agreed way to measure this kind of change for this "
                "client: which metrics to export, which controls and placebo metrics are safe, and known data issues.")
    c1, c2 = st.columns(2)
    r_clients = ["(no recipe)"] + list(recipes_all)
    r_client = c1.selectbox("Client recipes", r_clients,
                            index=r_clients.index(cfg.get("recipe_client")) if cfg.get("recipe_client") in r_clients else 0,
                            key=k("rc"))
    client_rec, recipe = (recipes_all.get(r_client), None)
    if client_rec:
        rlist = client_rec.get("recipes") or []
        ids = [r["id"] for r in rlist]
        rid = c2.selectbox("Recipe", ids, format_func=lambda i: next(r["name"] for r in rlist if r["id"] == i),
                           index=ids.index(cfg["recipe_id"]) if cfg.get("recipe_id") in ids else 0, key=k("rid"))
        recipe = next(r for r in rlist if r["id"] == rid)
        cols_r = rcp.recipe_columns(recipe)
        for key_, val in (("outcome", cols_r["outcome"]), ("denominator", cols_r["denominator"]),
                          ("candidates", cols_r["controls"]), ("placebo", cols_r["placebo"])):
            cfg.setdefault(key_, val)
        cfg.setdefault("client", client_rec["client"])
        cfg.setdefault("recipe_ratios", [c.split(" / ", 1) for c in cols_r["controls"] + cols_r["placebo"] if " / " in c])
        with st.expander(f"Recipe card: {recipe['name']}"
                         + ("" if recipe.get("verified") else "  (⚠️ not yet verified by the account team)"), expanded=True):
            st.markdown(f"**Use when:** {recipe.get('use_when', '')}")
            ds = client_rec.get("data_source") or {}
            st.markdown(f"**Data source:** {ds.get('tool', '')} · {ds.get('report_suite_name') or ds.get('report_suite', '')}"
                        f"  \n{ds.get('notes', '')}")
            def _item(label, d):
                if not d:
                    return
                st.markdown(f"**{label}: `{d.get('column', '')}`** – {d.get('definition', '')}")
                for f_ in ("why", "cautions", "how_to_export"):
                    if d.get(f_):
                        st.markdown(f"&nbsp;&nbsp;&nbsp;*{f_.replace('_', ' ').capitalize()}:* {d[f_]}")
            _item("Outcome", recipe.get("outcome"))
            _item("Denominator", recipe.get("denominator"))
            for c_ in recipe.get("controls") or []:
                _item("Control", c_)
            for p_ in recipe.get("placebo") or []:
                _item("Placebo metric", p_)
            if recipe.get("placebo_note"):
                st.markdown(f"**Placebo:** {recipe['placebo_note']}")
            if recipe.get("typical_detectable_effect"):
                st.markdown(f"**Typical detectable effect:** {recipe['typical_detectable_effect']}")
            if recipe.get("notes"):
                st.markdown(f"**Notes:** {recipe['notes']}")
            if client_rec.get("release_process"):
                st.markdown(f"**Finding the change date:** {client_rec['release_process']}")
            st.caption("Export these series with the suggested column names and the app will pre-fill steps 2 and 3.")
    st.subheader("Test details")
    st.caption("These tell the tool when the change happened and what effect to look for.")
    c1, c2, c3 = st.columns(3)
    client = c1.text_input("Client", cfg.get("client", ""), key=k("client"))
    name = c2.text_input("Test name", cfg.get("name", ""), key=k("name"))
    primary_metric = c3.text_input("Test's primary metric", cfg.get("primary_metric", ""), key=k("pm"),
                                   help="As written on the test ticket. Used in the report only.")
    c1, c2 = st.columns(2)
    test_ticket = c1.text_input("Test ticket (e.g. EAOA-1234)", cfg.get("test_ticket", ""), key=k("tt"))
    release_ticket = c2.text_input("Release ticket (e.g. MAG-1234)", cfg.get("release_ticket", ""), key=k("rt"))

    c1, c2, c3 = st.columns(3)
    lift_known = c1.checkbox("I know the test's result", cfg.get("lift_known", True), key=k("lk"),
                             help="Untick for changes that were never A/B tested.")
    test_lift = c2.number_input("Test result: % change in the primary metric", value=float(cfg.get("test_lift", 0.0)),
                                step=0.5, disabled=not lift_known, key=k("tl"),
                                help="+2.4 for a 2.4% uplift; -40 for a 40% reduction. Use the winning variant vs control.")
    exposure = c3.slider("Share of the analysed outcome the change could reach (%)", 1, 100,
                         int(cfg.get("exposure", 100)), key=k("exp"))
    explain("What's 'share the change could reach'?",
            "If the change only affected part of what you're measuring, its effect is diluted.\n\n"
            "*Example:* the test found **+10%** for visitors who saw a new product-page banner. You analyse **all "
            "orders**, but only **40%** of orders come from visitors who saw that page. The effect you'd expect in all "
            "orders is about 10% × 40% = **+4%**.\n\nIf your outcome only counts people who could see the change, "
            "leave this at 100%. When unsure, a narrower outcome is better than a guess here.")

    st.markdown("**The test's control-group figure** for the primary metric (from the test readout). The tool checks your "
                "export against it, to catch the commonest mistake: exporting a slightly different metric from the test's.")
    c1, c2, c3 = st.columns(3)
    unit_keys = list(chk.UNITS)
    control_unit = c1.selectbox("What kind of figure is it?", unit_keys, format_func=lambda u: chk.UNITS[u],
                                index=unit_keys.index(cfg.get("control_unit", "rate_pct")), key=k("cu"))
    control_value = c2.number_input("Control group's figure during the test (leave 0 if unknown)", min_value=0.0,
                                    value=float(cfg.get("control_value") or 0.0), step=0.01, format="%.4f", key=k("cv"),
                                    help="e.g. control conversion 2.30 (%). Find it in the test readout, Adobe Target / A4T, "
                                         "Monetate or WTO reports.")
    control_share = c3.slider("Control group's share of traffic during the test (%)", 1, 100,
                              int(cfg.get("control_share", 50)), key=k("cs"), disabled=control_unit != "weekly_count",
                              help="Only needed for weekly counts: the control group only saw part of the traffic.")

    st.subheader("When did users first see the change?")
    c1, c2 = st.columns(2)
    rel_default = pd.Timestamp(cfg["release_date"]).date() if cfg.get("release_date") else date.today() - timedelta(days=180)
    release_date = c1.date_input("Release date (from the release ticket's fix version)", rel_default,
                                 format="DD/MM/YYYY", key=k("rd"))
    ran_opts = ["No", "Yes", "Not sure"]
    ran_100 = c2.radio("Did the winner run at 100% in a testing tool (Target, Monetate, WTO) before the release?",
                       ran_opts, index=ran_opts.index(cfg.get("ran_100", "No")), horizontal=True, key=k("r100"))
    change_date, change_reason = release_date, "release date"
    mon_client = ((client_rec or {}).get("data_source") or {}).get("monetate_client")
    if mon_client:
        with st.expander("Look up the test and 100% dates in Monetate"):
            from impact_tool import monetate as mon
            creds = mon.get_credentials(mon_client)
            if creds is None:
                st.info(f"Monetate isn't connected for this client yet. An admin adds an API key to the app's secrets "
                        f"under [monetate.{mon_client}] (see .streamlit/secrets.toml.example).")
            else:
                q = st.text_input("Experience name contains (e.g. EXP283 or 283)", key=k("monq"))
                if q and st.button("Search Monetate", key=k("mons")):
                    try:
                        ss[k("mont")] = mon.experiences_table(mon.fetch_experiences(creds, q))
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Couldn't read Monetate: {e}")
                if isinstance(ss.get(k("mont")), pd.DataFrame):
                    t_ = ss[k("mont")]
                    st.dataframe(t_, hide_index=True, use_container_width=True)
                    st.caption("A '100% experience' has one variant getting all traffic: its start date is usually the "
                               "change date to use below. If the winner was set to 100% by editing the test experience "
                               "instead, Monetate's API only shows today's split: check 'View Experience History' in "
                               "Monetate for the date.")
    if ran_100 == "Yes":
        d100 = st.date_input("Date it went to 100% in the testing tool",
                             pd.Timestamp(cfg.get("date_100", release_date)).date(), format="DD/MM/YYYY", key=k("d100"))
        change_date, change_reason = d100, "date the winner went to 100% in the testing tool"
    elif ran_100 == "Not sure":
        st.warning("Please check before relying on the result. Winners are often switched to 100% in the testing tool "
                   "while waiting for development. If so, users saw the change from that date, and nothing changed "
                   "at release, so the tool would look for an effect on the wrong date.")

    st.subheader("Weeks to leave out of the 'before' period")
    tw = cfg.get("test_window")
    excl_test = st.checkbox("Leave out the original test period", bool(tw), key=k("xt"),
                            help="During the test only some visitors saw the variant, so those weeks are neither "
                                 "'before' nor 'after'.")
    exclude: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    if excl_test:
        dflt = tuple(pd.Timestamp(x).date() for x in tw) if tw else (release_date - timedelta(days=120),
                                                                     release_date - timedelta(days=90))
        rng = st.date_input("Test start and end", dflt, format="DD/MM/YYYY", key=k("tw"))
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            exclude.append((pd.Timestamp(rng[0]), pd.Timestamp(rng[1])))
    st.caption("Optional: other weeks to leave out, such as tracking outages, or peak trading weeks your controls "
               "don't capture. Add a row per period.")
    extra = pd.DataFrame(cfg.get("extra_exclude", []), columns=["start", "end", "reason"])
    extra["start"] = pd.to_datetime(extra["start"])
    extra["end"] = pd.to_datetime(extra["end"])
    other = st.data_editor(extra, num_rows="dynamic", width="stretch", key=k("xe"),
                           column_config={"start": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                          "end": st.column_config.DateColumn(format="DD/MM/YYYY")})
    extra_exclude = []
    for _, r in other.dropna(subset=["start", "end"]).iterrows():
        exclude.append((pd.Timestamp(r["start"]), pd.Timestamp(r["end"])))
        extra_exclude.append([str(pd.Timestamp(r["start"]).date()), str(pd.Timestamp(r["end"]).date()),
                              r.get("reason") or ""])

    # ------------------------------------------------ step 2
    st.header("2. Data")
    st.markdown("Upload **one CSV** with a date column and **one column per series**: the outcome, the denominator "
                "(optional) and every candidate control series. Daily or weekly rows both work.")
    explain("What should I export?", (GUIDE / "02_choosing_the_outcome.md").read_text())
    up = st.file_uploader("CSV file", type=["csv"], key=k("csv"))
    src = up if up is not None else (ROOT / cfg["file"] if cfg.get("file") else None)
    if src is None:
        st.info("Upload a CSV, or pick an example at the top, to continue.")
        st.stop()
    try:
        df, date_col = load_csv(src)
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't read the file: {e}")
        st.stop()

    conv_keys = list(WEEK_CONVENTIONS)
    detected = detect_convention(df[date_col])
    convention = st.selectbox("How are the dates labelled?", conv_keys,
                              index=conv_keys.index(cfg.get("convention", detected)),
                              format_func=lambda c: WEEK_CONVENTIONS[c] + (" (detected)" if c == detected else ""),
                              key=k("conv"),
                              help="Getting this wrong shifts every week by up to 6 days. Adobe Analytics weekly "
                                   "reports usually label weeks by their start date.")

    numeric = [c for c in df.columns if c != date_col and pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.9]
    if not numeric:
        st.error("No numeric columns found.")
        st.stop()
    c1, c2 = st.columns(2)
    outcome = c1.selectbox("Outcome (the metric to check)", numeric,
                           index=numeric.index(cfg["outcome"]) if cfg.get("outcome") in numeric else 0, key=k("out"),
                           help="A count, e.g. orders, clicks, or visits to a page. Ideally as close to the change as possible.")
    den_opts = ["(none, analyse the count)"] + [c for c in numeric if c != outcome]
    denom_sel = c2.selectbox("Denominator (optional, recommended)", den_opts,
                             index=den_opts.index(cfg["denominator"]) if cfg.get("denominator") in den_opts else 0,
                             key=k("den"), help="The traffic the outcome comes from, e.g. visits to the page where the "
                                                "change lives. Turns the outcome into a rate, which removes traffic swings.")
    denom = None if denom_sel.startswith("(none") else denom_sel

    if not cfg.get("ratios") and cfg.get("recipe_ratios"):
        auto = [p for p in cfg["recipe_ratios"] if p[0] in numeric and p[1] in numeric]
        if auto:
            cfg["ratios"] = auto[:5]
            st.caption("Ratio series from the recipe were created automatically: " + ", ".join(f"{a} / {b}" for a, b in auto[:5]))
    with st.expander("Optional: create ratio series (e.g. conversion rate of a group that couldn't see the change)",
                     expanded=bool(cfg.get("ratios"))):
        st.caption("Controls often work best as rates, such as orders ÷ visits for visitors who never saw the change. "
                   "Ratios are calculated after daily data is summed into weeks.")
        n_r = st.number_input("Number of ratio series", 0, 5, len(cfg.get("ratios", [])), key=k("nr"))
        ratios = []
        for i in range(int(n_r)):
            d0 = cfg["ratios"][i] if i < len(cfg.get("ratios", [])) else [numeric[0], numeric[-1]]
            r1, r2 = st.columns(2)
            a_ = r1.selectbox(f"Ratio {i + 1}: top", numeric, index=numeric.index(d0[0]) if d0[0] in numeric else 0,
                              key=k(f"rn{i}"))
            b_ = r2.selectbox(f"Ratio {i + 1}: bottom", numeric, index=numeric.index(d0[1]) if d0[1] in numeric else 0,
                              key=k(f"rd{i}"))
            if a_ != b_:
                ratios.append([a_, b_])
    ratio_names = [f"{a} / {b}" for a, b in ratios]
    cand_opts = [c for c in numeric + ratio_names if c not in (outcome, denom)]
    candidates = st.multiselect("Candidate control series (the tool will check each one)", cand_opts,
                                default=[c for c in cfg.get("candidates", []) if c in cand_opts], key=k("cand"),
                                help="Metrics that move with the outcome but couldn't be affected by the change. "
                                     "Include every plausible one; the tool checks them in step 3.")
    as_rate = st.checkbox("Express control series per the same denominator", bool(cfg.get("controls_as_rate")),
                          disabled=denom is None, key=k("asr"),
                          help="Tick when the controls are counts from the same traffic as the outcome, e.g. "
                               "forgot-password visits per login visit as a control for forgot-username visits per login visit.")

    weekly_full, notes = to_weekly(df, date_col, numeric, convention)
    for (a_, b_), nm in zip(ratios, ratio_names):
        weekly_full[nm] = weekly_full[a_] / weekly_full[b_]
    weekly = weekly_full[[outcome] + ([denom] if denom else []) + candidates]
    for n in notes:
        st.caption("ℹ️ " + n)
    flags = quality_flags(weekly)
    if len(flags):
        with st.expander(f"⚠️ {len(flags)} possible data issue(s): check these aren't tracking breaks"):
            st.markdown("Sudden jumps or drops of more than 50% from one week to the next are often tracking problems "
                        "(a tag broke, a definition changed). If they are, leave those weeks out in step 1 or fix the export.")
            st.dataframe(flags.assign(week=flags["week"].dt.strftime("%d %b %Y")), width="stretch", hide_index=True)

    first_wk = weekly[outcome].first_valid_index()
    last_wk = weekly[outcome].last_valid_index()
    recipe_warnings = rcp.date_warnings(client_rec, first_wk, last_wk, recipe["id"] if recipe else None) if client_rec else []
    if recipe_warnings:
        with st.expander(f"⚠️ {len(recipe_warnings)} known data issue(s) for {client_rec['client']} in your date range",
                         expanded=True):
            for rw in recipe_warnings:
                st.markdown("- " + rw)
    cov = chk.coverage(weekly, outcome)
    if cov.status != "ok":
        st.warning("**Coverage:** " + cov.message)

    st.markdown("**Check against the test**")
    tw_check = [exclude[0][0], exclude[0][1]] if excl_test and exclude else None
    recon = chk.reconcile(weekly, outcome, denom, tw_check, control_value or None, control_unit, control_share / 100)
    recon_ack, recon_reason = False, ""
    {"ok": st.success, "warn": st.warning, "fail": st.error, "skipped": st.info}[recon.status](recon.message)
    if recon.status in ("warn", "fail"):
        recon_ack = st.checkbox("I've checked this and the difference is expected", key=k("rack"),
                                help="For example, the test only targeted part of the traffic. Your reason goes in the report.")
        if recon_ack:
            recon_reason = st.text_input("Why is the difference expected?", key=k("rwhy"))

    plot_df = weekly.copy()
    out_label = f"{outcome} / {denom}" if denom else outcome
    if denom:
        plot_df[out_label] = plot_df[outcome] / plot_df[denom]
    cols_plot = [out_label] + candidates
    base = plot_df[cols_plot].iloc[:8].mean()
    norm = (plot_df[cols_plot] / base * 100).reset_index().melt("week", var_name="series", value_name="index")
    st.markdown("**Your series, indexed** (each line starts at about 100, so you can compare their shapes)")
    st.altair_chart(alt.layer(
        alt.Chart(norm).mark_line().encode(x=alt.X("week:T", title=None),
                                           y=alt.Y("index:Q", title="Index (first 8 weeks = 100)"),
                                           color=alt.Color("series:N", legend=alt.Legend(orient="top", title=None)),
                                           tooltip=["week:T", "series:N", alt.Tooltip("index:Q", format=".0f")]),
        alt.Chart(pd.DataFrame({"d": [pd.Timestamp(change_date)]})).mark_rule(color="#C0392B", strokeWidth=2).encode(x="d:T"),
    ).properties(height=280), width="stretch")
    st.caption("Good controls follow the outcome's ups and downs before the red line. After it, only the outcome should move away.")

    # ------------------------------------------------ step 3
    st.header("3. Control series")
    st.markdown("The tool builds a **comparison line** from your control series: its best estimate of what the outcome "
                "would have done without the change. This step decides how good that estimate is.")
    explain("How to choose control series (read this the first few times)", (GUIDE / "03_choosing_controls.md").read_text())

    frame_all = model_frame(weekly, Spec(outcome, denom, candidates, pd.Timestamp(change_date), exclude, as_rate))
    try:
        prep0 = prepare(frame_all, Spec(outcome, denom, candidates, pd.Timestamp(change_date), exclude, as_rate))
        st.caption(f"Usable weeks: **{prep0.n_pre} before** the change and **{prep0.n_post} after**."
                   + (" ⚠️ Fewer than 12 weeks before the change; the tool needs at least 12." if prep0.n_pre < 12 else "")
                   + (" A year or more before the change is ideal." if 12 <= prep0.n_pre < 52 else ""))
    except Exception:  # noqa: BLE001
        prep0 = None

    skey = (outcome, denom, tuple(candidates), str(change_date), tuple(map(str, exclude)), as_rate, convention)
    if candidates and st.button("Check candidate series", type="primary"):
        with st.spinner("Backtesting each candidate and checking for jumps at the change date…"):
            try:
                ss["scores"] = cached_screen(frame_all, outcome, denom, tuple(candidates), pd.Timestamp(change_date),
                                             tuple(exclude), as_rate)
                ss["scores_key"] = skey
            except ValueError as e:
                st.error(str(e))
    scores = ss.get("scores") if ss.get("scores_key") == skey else None
    if scores:
        st.dataframe(scores_table(scores), width="stretch", hide_index=True)
        explain("How to read this table",
                "- **Forecast improvement** (the key column): at many earlier dates the tool predicted the next 8 weeks "
                "of the outcome with and without this control. Positive = the control made predictions better.\n"
                "- **Weight in blend**: how much the comparison line leans on this control when all candidates are combined. 0 = ignored.\n"
                "- **Correlations**: whether it shares the outcome's trends and seasons (levels) and its week-to-week bumps (weekly changes).\n"
                "- **Own jump at change date**: ⚠️ means this control itself jumped when the change went live. Either "
                "the change affected it (don't use it) or something else happened that week (find out what).\n"
                "- ✅ **Suggested** = improves the forecast and didn't jump. Your knowledge of the site overrides this.")
    elif candidates:
        st.caption("Click **Check candidate series** to score each candidate.")
    default_controls = [s.name for s in scores if s.suggested] if scores else []
    controls = st.multiselect("Control series to use", candidates, default=default_controls, key=k(f"ctrl{len(default_controls)}"),
                              help="Usually 1–3 good ones. The tool blends them automatically.")

    st.markdown("**Checklist for each control** (required). The tool can't know how your site works, so it needs your judgement here.")
    checklist_answers: dict[str, dict[str, str]] = {}
    problems, unanswered = [], 0
    for c in controls:
        with st.expander(f"Checklist: {c}", expanded=True):
            ans = {}
            for qk, q in CHECKLIST:
                a_ = st.radio(q, ["Yes", "No", "Not sure"], index=None, horizontal=True, key=k(f"chk_{c}_{qk}"))
                ans[qk] = a_ or "unanswered"
                if a_ is None:
                    unanswered += 1
                elif a_ != SAFE_ANSWER[qk]:
                    problems.append(f"**{c}**: {q.split('?')[0]}? You answered *{a_}*.")
            checklist_answers[c] = ans
    if problems:
        st.warning("These answers suggest a control may not be safe to use. Consider removing it, or note your reasoning:\n\n"
                   + "\n".join(f"- {p}" for p in problems))
    if not controls:
        st.info("No control series selected. The comparison line will be the outcome's average level before the change. "
                "That's much weaker, especially for seasonal metrics, so only do this if no reasonable control exists.")

    st.subheader("Placebo metric (strongly encouraged)")
    st.markdown("A **placebo metric** is something the change **couldn't possibly affect**. The tool runs the same "
                "analysis on it. If it also 'moves' when the change went live, something else happened that week (a "
                "promotion, a release, a tracking change), and the main result can't be trusted.")
    explain("How to pick a placebo metric",
            "- It must be **impossible for the change to affect**. Example: login-page visits for a change on the "
            "dashboard (people log in before they see the dashboard).\n"
            "- It should be exposed to the **same kinds of events** as the outcome: the same site, promotions, "
            "releases and tracking. Then, if something else happened that week, the placebo shows it.\n"
            "- It doesn't need to move closely with the outcome (that's what controls are for).\n"
            "- Don't reuse a control series as the placebo.\n\nIf the recipe suggests one, it's pre-selected.")
    plac_opts = [c for c in list(weekly_full.columns) if c not in [outcome, denom] + controls]
    placebos_sel = st.multiselect("Placebo metric(s)", plac_opts,
                                  default=[c for c in cfg.get("placebo", []) if c in plac_opts], key=k("plc"))
    placebo_per_den = st.checkbox("Express placebo metrics per the same denominator",
                                  bool(cfg.get("placebo_per_denominator", False)), disabled=denom is None, key=k("ppd"))
    if not placebos_sel:
        st.warning("No placebo metric selected. The result won't be checked for other events in the same week, and the "
                   "report will say so.")

    # ------------------------------------------------ step 4
    st.header("4. Results")
    n_pre_est = prep0.n_pre if prep0 else 0
    n_post_est = prep0.n_post if prep0 else 0
    sug = suggest_window(n_pre_est, n_post_est) if n_pre_est and n_post_est else 8
    win_opts = sorted({h for h in (8, 13, 26, 52) if h <= max(n_post_est, 8)} | {sug})
    primary_h = st.select_slider("Primary window for the verdict (weeks after the change)", options=win_opts,
                                 value=int(cfg.get("primary", sug)) if int(cfg.get("primary", sug)) in win_opts else sug,
                                 key=k("win"))
    st.caption(f"Suggested: **{sug} weeks**, the longest standard window that's no more than half the history before "
               f"the change ({n_pre_est} weeks). Longer windows can't be tested reliably with this much history.")
    if primary_h > n_pre_est / 2:
        st.warning(f"A {primary_h}-week window is more than half the history ({n_pre_est} weeks). The test will have very "
                   "little power, so a 'no clear effect' result will mean very little.")

    st.subheader("Lock the plan")
    st.markdown("Decide your outcome, controls, placebo and window **before** seeing the result, then lock them. The tool "
                "records every setting and a fingerprint of the exact data, and gives the plan an ID. Change anything "
                "afterwards and you get a new plan ID, and the change shows in the analysis history.")
    c1, c2 = st.columns(2)
    purposes = ["Internal check", "Client-facing"]
    purpose = c1.radio("What's this check for?", purposes, horizontal=True,
                       index=purposes.index(cfg.get("purpose", "Internal check")), key=k("purpose"),
                       help="Client-facing results need a second person to review them in the Review tab before they're shared.")
    author = c2.text_input("Your name", cfg.get("author", ""), key=k("author"))
    if purpose == "Client-facing":
        st.info("**Client-facing:** after the run, download the **review pack** and send it, with your CSV, to a colleague. "
                "They review it in the **Review** tab. Until then the report is marked *not for client use*.")

    settings = {"client": client, "name": name, "primary_metric": primary_metric, "test_ticket": test_ticket,
                "release_ticket": release_ticket, "lift_known": lift_known, "test_lift": float(test_lift),
                "exposure": int(exposure), "release_date": str(release_date), "ran_100": ran_100,
                "change_date": str(change_date), "change_date_reason": change_reason,
                "test_window": [str(exclude[0][0].date()), str(exclude[0][1].date())] if excl_test and exclude else None,
                "extra_exclude": extra_exclude, "convention": convention, "outcome": outcome, "denominator": denom,
                "candidates": candidates, "controls": controls, "controls_as_rate": as_rate, "ratios": ratios,
                "primary": int(primary_h), "recipe_client": r_client if client_rec else None,
                "recipe_id": recipe["id"] if recipe else None, "control_value": float(control_value or 0),
                "control_unit": control_unit, "control_share": int(control_share), "recon_ack": recon_ack,
                "recon_reason": recon_reason, "placebo": placebos_sel, "placebo_per_denominator": placebo_per_den,
                "checklist_answers": checklist_answers}

    if unanswered:
        st.info(f"Answer the checklist for every control first ({unanswered} question(s) left).")
        st.stop()
    if purpose == "Client-facing" and not author.strip():
        st.info("Add your name before running a client-facing check.")
        st.stop()
    settings_json = json.dumps(settings, sort_keys=True, default=str)
    run_clicked = st.button("Lock plan and run analysis", type="primary")
    if run_clicked:
        ss["locked"] = {"settings_json": settings_json, "author": author.strip(), "purpose": purpose,
                        "locked_at": datetime.now().isoformat(timespec="seconds"), "logged": False}
    lk = ss.get("locked")
    if not lk or lk["settings_json"] != settings_json or lk["author"] != author.strip() or lk["purpose"] != purpose:
        if lk:
            st.info("Settings have changed since the last run. Lock the plan and run again to see results.")
        st.stop()

    try:
        with st.spinner("Running the analysis, data checks, placebo metrics and robustness alternatives…"):
            res = cached_pipeline(df, date_col, settings_json)
    except (ValueError, KeyError) as e:
        st.error(str(e))
        st.stop()
    fp = plan_mod.fingerprint(res.weekly_full)
    plan = plan_mod.make_plan(settings, fp, author.strip(), purpose)
    plan["locked_at"] = lk["locked_at"]
    a, verdict, expected, w = res.analysis, res.verdict, res.expected, res.analysis.primary
    data_checks, plac_results, rob = res.data_checks, res.placebos, res.robustness
    for msg in res.warnings:
        st.warning(msg)

    if not lk["logged"]:
        lk["logged"] = True
        ss.setdefault("run_log", []).append({
            "time": lk["locked_at"][11:], "plan ID": plan["plan_id"], "outcome": out_label,
            "controls": ", ".join(controls) or "none", "placebo": ", ".join(placebos_sel) or "none",
            "change date": str(change_date), "window": w.weeks, "effect": f"{w.effect:+.1%}",
            "p-value": f"{w.p_value:.3f}", "robustness": rob.rating if rob else "", "verdict": verdict.label})

    box = {"green": st.success, "amber": st.warning, "red": st.error, "grey": st.info}[verdict.colour]
    box(f"### Verdict: {verdict.label}\n{verdict.headline}")
    st.caption(f"Plan ID **{plan['plan_id']}** · {purpose} · analyst: {author or 'not given'} · locked {plan['locked_at']}")
    if purpose == "Client-facing":
        st.warning("**Not yet reviewed: not for client use.** Download the review pack below and ask a colleague to review "
                   "it in the Review tab.")

    icon = {"ok": "✅", "warn": "⚠️", "fail": "❌", "skipped": "➖"}
    rob_icon = {"Robust": "✅", "Somewhat sensitive": "⚠️", "Fragile": "❌"}.get(rob.rating if rob else "", "➖")
    with st.expander("Data checks: " + " ".join(icon[c_.status] for c_ in data_checks)
                     + ("  ·  placebo: " + " ".join("⚠️" if p_.window.significant else "✅" for p_ in plac_results)
                        if plac_results else "  ·  placebo: not checked") + f"  ·  robustness: {rob_icon}",
                     expanded=any(c_.status in ("warn", "fail") for c_ in data_checks)
                     or any(p_.window.significant for p_ in plac_results)):
        for c_ in data_checks:
            st.markdown(f"{icon[c_.status]} **{c_.name}.** {c_.message}")
        for p_ in plac_results:
            st.markdown(f"{'⚠️' if p_.window.significant else '✅'} **Placebo '{p_.metric}'.** "
                        f"{p_.window.effect:+.1%} (p = {p_.window.p_value:.3f}): "
                        + ("it moved at the change date, so something else may have happened that week."
                           if p_.window.significant else "no clear change, as expected."))
        if not plac_results:
            st.markdown("➖ **Placebo.** Not checked: no placebo metric selected.")
        if rob:
            st.markdown(f"{rob_icon} **Robustness: {rob.rating}.** {rob.summary}")

    m1, m2, m3 = st.columns(3)
    m1.metric("Smallest detectable effect", f"±{w.mde(expected):.0%}",
              help="Changes smaller than this would usually be missed with this data (80% detection).")
    m2.metric("Expected if the test held", "n/a" if expected is None else f"{expected:+.1%}",
              help="Test result × share of the outcome the change could reach.")
    m3.metric(f"Measured effect ({w.label.lower()})", f"{w.effect:+.1%}")
    m3.caption("Plausible range: " + ("no lower limit" if w.lo_unbounded else f"{w.lo:+.1%}") + " to "
               + ("no upper limit" if w.hi_unbounded else f"{w.hi:+.1%}") + f" · p-value {w.p_value:.3f}")
    summary = plain_english(a, verdict, expected, out_label)
    st.markdown("#### What this means")
    st.markdown(summary)
    with st.expander("Why this verdict"):
        for d in verdict.details:
            st.markdown(f"- {d}")
    if expected is not None and abs(expected) < w.mde(expected):
        st.warning(f"The expected effect ({expected:+.1%}) is smaller than this data can reliably detect "
                   f"(±{w.mde(expected):.0%}). Whatever the verdict says, this check can't settle whether a "
                   "small effect held. A holdout group is the reliable way to measure effects this size.")

    st.markdown("#### Chart 1: actual vs the comparison line")
    c_imp = impact_chart(a, change_date, out_label, res.spec.exclude)
    st.altair_chart(c_imp, width="stretch")
    st.caption("Navy: what actually happened. Orange dashed: the comparison line (what we'd expect without the change). "
               "Before the red line they should move together; after it, any lasting gap is the effect. Grey bands: weeks left out.")

    st.markdown("#### Chart 2: the weekly gap")
    c_gap = gap_chart(a, change_date)
    st.altair_chart(c_gap, width="stretch")
    st.caption(f"Each bar is the % gap between actual and comparison in one week. Before the change (grey) the bars should "
               f"wobble around zero, mostly inside the shaded band (±{a.diagnostics.backtest_error:.0%}, the typical forecast "
               "error). After it (navy), bars sitting consistently away from zero show the effect. Orange line: the average gap "
               "in the primary window.")

    st.markdown("#### Chart 3: is the post-change stretch unusual?")
    c_blk = block_chart(a)
    st.altair_chart(c_blk, width="stretch")
    st.caption(f"This is exactly what the p-value is calculated from. Assuming no effect, the tool fits the comparison line "
               f"on all weeks, then takes the average gap over every {w.weeks}-week stretch (wrapping round from the end of "
               "the data to the start). Grey dots: every other stretch. Orange dot: the stretch after the change. "
               f"The p-value ({w.p_value:.3f}) is the share of dots at least as far from zero as the orange one. If the "
               "orange dot sits well outside the grey cloud, the effect is real.")

    st.markdown("#### Robustness: does the conclusion survive other reasonable choices?")
    c_rob = None
    if rob:
        {"Robust": st.success, "Somewhat sensitive": st.warning, "Fragile": st.error}.get(rob.rating, st.info)(
            f"**{rob.rating}.** {rob.summary}")
        c_rob = robustness_chart(rob)
        st.altair_chart(c_rob, width="stretch")
        st.dataframe(robustness_display(rob), width="stretch", hide_index=True)
        explain("What is this and how is it rated?",
                "Every analysis involves choices. The tool re-runs yours under a **fixed list** of reasonable alternatives "
                "(you can't pick them, which stops cherry-picking): each control removed, no controls, the change date a "
                "week earlier or later, peak trading weeks left out, the raw count instead of the rate, and only the most "
                "recent year of history.\n\n"
                "- **Robust:** at least 80% of the alternatives reach the same conclusion, and none finds a clear effect "
                "the other way.\n- **Somewhat sensitive:** 60–80% agree.\n- **Fragile:** fewer than 60% agree, or one "
                "finds a clear effect in the opposite direction.\n\nShorter windows are shown for context but not "
                "scored, because fewer weeks means less power. A **fragile** result shouldn't be presented to a client "
                "without saying so. If the date-shift alternatives give a clearly *bigger* effect, check the change date.")

    st.markdown("#### Results by window")
    st.dataframe(windows_table(a, expected), width="stretch", hide_index=True)
    explain("How to read this table",
            "- **Estimated effect**: average % gap after the change.\n"
            "- **Plausible range (95%)**: effects the data can't rule out. If it excludes 0, the effect is clear.\n"
            "- **p-value**: share of comparable stretches with a gap at least this big. Below 0.05 = clear effect.\n"
            "- **Smallest detectable**: effects smaller than this would usually be missed.\n"
            "- **Window length OK?**: windows longer than half the history can't be tested reliably.")

    st.markdown("#### Checks on the comparison line")
    d = a.diagnostics
    c1, c2, c3 = st.columns(3)
    c1.metric("Typical forecast error", f"±{d.backtest_error:.1%}",
              f"vs ±{d.backtest_error_no_controls:.1%} without controls", delta_color="off",
              help="How far off the comparison line typically was when forecasting a few weeks ahead, before the change.")
    c2.metric("Weekly variation explained", "n/a" if np.isnan(d.fit_r2) else f"{max(d.fit_r2, 0):.0%}",
              help="Share of the outcome's week-to-week ups and downs that the comparison line follows, before the change.")
    c3.metric("Drift before the change", f"{d.drift_per_year:+.1%} / year", "⚠️ check" if d.drift_flag else "OK",
              delta_color="off", help="A steady trend in the gap before the change. Large drift can masquerade as an effect.")
    for n in d.notes:
        st.warning(n)
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**Control weights**")
        bt = blend_table(a)
        if len(bt):
            st.dataframe(bt, width="stretch", hide_index=True)
        else:
            st.caption("No controls used.")
    with cc2:
        st.markdown("**Effect with each control removed**")
        if len(a.leave_one_out):
            st.dataframe(a.leave_one_out, width="stretch", hide_index=True)
        else:
            st.caption("Needs at least one control.")
    if len(a.prep.dropped):
        with st.expander(f"Weeks left out ({len(a.prep.dropped)})"):
            st.dataframe(a.prep.dropped.assign(week=a.prep.dropped["week"].dt.strftime("%d %b %Y")),
                         width="stretch", hide_index=True)

    st.markdown("#### Analysis history (this session)")
    st.dataframe(pd.DataFrame(ss["run_log"]), width="stretch", hide_index=True)
    st.caption("Every run is logged with its plan ID and included in the report and review pack, so reviewers can see if "
               "settings were changed after seeing results.")

    with st.expander("Compare with the v1 engine (CausalImpact-style, for reference only)"):
        st.markdown("v1 is the original engine. In validation it raised false alarms in up to 20% of cases (v2: about 5% "
                    "or less), so use it only as a sense-check.")
        if st.button("Run v1 engine"):
            from impact_tool.model import run_impact, run_placebos
            frame = model_frame(res.weekly, res.spec)
            with st.spinner("Running v1…"):
                r1 = run_impact(frame, res.spec, horizons=(8, int(primary_h)))
                p1 = run_placebos(frame, res.spec)
            st.dataframe(pd.DataFrame([{"Window": x.label, "Effect": f"{x.effect:+.1%}",
                                        "95% interval": f"{x.lo:+.1%} to {x.hi:+.1%}",
                                        "Significant": "Yes" if x.significant else "No"} for x in r1.windows]),
                         width="stretch", hide_index=True)
            st.caption(f"v1 placebo checks: {sum(p.significant for p in p1)} of {len(p1)} fake dates flagged.")

    # ------------------------------------------------ downloads
    st.markdown("#### Download")
    meta = {"name": name, "client": client, "test_ticket": test_ticket, "release_ticket": release_ticket,
            "primary_metric": primary_metric, "test_lift_text": f"{test_lift:+.1f}%" if lift_known else "not provided",
            "change_date": pd.Timestamp(change_date).strftime("%d %b %Y"), "change_date_reason": change_reason,
            "outcome_desc": out_label, "exposure": f"{exposure}%"}
    md = markdown_report(meta, verdict, a, expected, checklist_answers, res.notes, ss["run_log"], summary,
                         data_checks=data_checks, placebos=plac_results, recipe=res.recipe_label,
                         plan_block=plan_mod.review_block_md(None, plan), robustness=rob)
    charts = {"Actual vs comparison line": c_imp, "Weekly gap": c_gap, "Is the post-change stretch unusual?": c_blk}
    if c_rob is not None:
        charts["Robustness"] = c_rob
    html_doc = html_report(md, charts, verdict)
    pack = plan_mod.make_pack(plan, result_summary(res), md, ss["run_log"])
    fname = (test_ticket or name or "impact").replace(" ", "_")
    d1, d2, d3, d4, d5 = st.columns(5)
    d1.download_button("Review pack (JSON)", json.dumps(pack, indent=2, default=str),
                       file_name=f"{fname}_review_pack_{plan['plan_id']}.json", type="primary" if purpose == "Client-facing" else "secondary",
                       help="Send this and your CSV to a colleague to review in the Review tab.")
    d2.download_button("Report (HTML)", html_doc, file_name=f"{fname}_post_release_impact.html", mime="text/html")
    d3.download_button("Report (Markdown)", md, file_name=f"{fname}_post_release_impact.md")
    d4.download_button("Weekly data (CSV)", a.weekly.to_csv(), file_name=f"{fname}_weekly.csv")
    d5.download_button("Settings (JSON)", json.dumps({**settings, "purpose": purpose, "author": author}, indent=2, default=str),
                       file_name=f"{fname}_settings.json",
                       help="Load these next time to re-run with the same settings (you'll need the data file too).")

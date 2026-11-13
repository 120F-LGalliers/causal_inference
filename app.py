"""120Feet post-release impact checker (Streamlit), v2.

Did a test winner's effect hold once it was built into the site?
Run with:  streamlit run app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from impact_tool import load_csv
from impact_tool import plan as plan_mod
from impact_tool.pipeline import result_summary
from impact_tool.report import block_chart, gap_chart, html_report, impact_chart, robustness_chart
from impact_tool.robustness import robustness_display

st.set_page_config(page_title="Post-release impact checker", page_icon="📈", layout="wide")

import wizard  # noqa: E402  (after set_page_config)
from wizard import cached_pipeline, explain, load_recipes  # noqa: E402

ROOT = Path(__file__).parent
GUIDE = ROOT / "docs" / "guide"
ss = st.session_state

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
    wizard.render()

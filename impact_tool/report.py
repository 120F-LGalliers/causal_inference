"""Charts, tables and downloadable reports for the v2 engine."""
from __future__ import annotations

import html
import json
from datetime import datetime

import altair as alt
import numpy as np
import pandas as pd

from .conformal import Analysis, Verdict, WindowResult

NAVY, ORANGE, RED, GREY = "#1F3A5F", "#E8743B", "#C0392B", "#9AA5B1"


def _weekly_df(a: Analysis) -> pd.DataFrame:
    d = a.weekly.reset_index()
    return d.rename(columns={d.columns[0]: "week"})


def _rule(change_date) -> alt.Chart:
    return alt.Chart(pd.DataFrame({"d": [pd.Timestamp(change_date)], "label": ["Change went live"]})).mark_rule(
        color=RED, strokeWidth=2).encode(x="d:T", tooltip=["label:N", alt.Tooltip("d:T", title="Date")])


def _excluded(exclude) -> list[alt.Chart]:
    if not exclude:
        return []
    ex = pd.DataFrame([{"a": pd.Timestamp(a), "b": pd.Timestamp(b)} for a, b in exclude])
    return [alt.Chart(ex).mark_rect(opacity=0.12, color="grey").encode(x="a:T", x2="b:T")]


def impact_chart(a: Analysis, change_date, y_title: str, exclude=()) -> alt.Chart:
    """Outcome vs the comparison line."""
    d = _weekly_df(a)
    long = d.melt(id_vars=["week", "period"], value_vars=["observed", "predicted"], var_name="series", value_name="value")
    long["series"] = long["series"].map({"observed": "Actual outcome", "predicted": "Comparison line (expected without the change)"})
    lines = alt.Chart(long).mark_line(point=alt.OverlayMarkDef(size=14)).encode(
        x=alt.X("week:T", title=None),
        y=alt.Y("value:Q", title=y_title, scale=alt.Scale(zero=False)),
        color=alt.Color("series:N", scale=alt.Scale(range=[NAVY, ORANGE]), legend=alt.Legend(orient="top", title=None, labelLimit=400)),
        strokeDash=alt.StrokeDash("series:N", scale=alt.Scale(range=[[1, 0], [5, 4]]), legend=None),
        tooltip=[alt.Tooltip("week:T", title="Week"), "series:N", alt.Tooltip("value:Q", format=",.4~f"), "period:N"])
    return alt.layer(*_excluded(exclude), lines, _rule(change_date)).properties(height=340)


def gap_chart(a: Analysis, change_date) -> alt.Chart:
    """Weekly gap between outcome and comparison line, with the typical pre-change wobble shaded."""
    d = _weekly_df(a)
    d = d[d["period"] != "left out"]
    band = a.diagnostics.backtest_error
    base = alt.Chart(d).encode(x=alt.X("week:T", title=None))
    zone = alt.Chart(pd.DataFrame({"lo": [-band], "hi": [band]})).mark_rect(opacity=0.12, color=GREY).encode(
        y="lo:Q", y2="hi:Q")
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="black", strokeDash=[2, 2]).encode(y="y:Q")
    bars = base.mark_bar(opacity=0.85).encode(
        y=alt.Y("gap:Q", title="Gap: actual vs comparison", axis=alt.Axis(format="%")),
        color=alt.Color("period:N", scale=alt.Scale(domain=["before", "after"], range=[GREY, NAVY]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=[alt.Tooltip("week:T", title="Week"), alt.Tooltip("gap:Q", format="+.1%"), "period:N"])
    eff = a.primary.effect
    post_line = alt.Chart(pd.DataFrame({"start": [a.prep.index[a.prep.n_pre]],
                                        "end": [a.prep.index[min(a.prep.n_pre + a.primary.weeks, len(a.prep.index)) - 1]],
                                        "y": [eff]})).mark_rule(color=ORANGE, strokeWidth=3).encode(
        x="start:T", x2="end:T", y="y:Q", tooltip=[alt.Tooltip("y:Q", title="Average gap (primary window)", format="+.1%")])
    return alt.layer(zone, zero, bars, post_line, _rule(change_date)).properties(height=260)


def block_chart(a: Analysis) -> alt.Chart:
    """Average gap of every earlier stretch of the same length vs the post-change stretch."""
    d = a.block_history.copy()
    d["Stretch"] = np.where(d["is_post"], "After the change", "Every other stretch")
    return alt.Chart(d).mark_circle(size=90, opacity=0.8).encode(
        x=alt.X("avg_gap:Q", title=f"Average gap over {a.primary.weeks} weeks (comparison line fitted assuming no effect)",
                axis=alt.Axis(format="%")),
        y=alt.Y("Stretch:N", title=None, sort=["Every other stretch", "After the change"],
                axis=alt.Axis(labelLimit=200)),
        color=alt.Color("Stretch:N", scale=alt.Scale(domain=["After the change", "Every other stretch"],
                                                     range=[ORANGE, GREY]), legend=None),
        tooltip=[alt.Tooltip("start:T", title="Stretch starting"), alt.Tooltip("avg_gap:Q", format="+.1%")],
    ).properties(height=140)


def robustness_chart(r) -> alt.Chart:
    """Effect and plausible range under each alternative, main analysis highlighted."""
    d = r.table.dropna(subset=["Effect"]).copy()
    d["kind"] = np.where(d["Alternative"] == "Main analysis", "Main analysis",
                         np.where(d["Scored"] == "Yes", "Scored alternative", "Context only"))
    order = list(d["Alternative"])
    base = alt.Chart(d).encode(y=alt.Y("Alternative:N", sort=order, title=None, axis=alt.Axis(labelLimit=320)))
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="black", strokeDash=[2, 2]).encode(x="x:Q")
    bars = base.mark_rule(strokeWidth=2).encode(x=alt.X("lo:Q", title="Effect and plausible range", axis=alt.Axis(format="%")),
                                                x2="hi:Q", color=alt.Color("kind:N", scale=alt.Scale(
                                                    domain=["Main analysis", "Scored alternative", "Context only"],
                                                    range=[ORANGE, NAVY, GREY]), legend=alt.Legend(orient="top", title=None)))
    pts = base.mark_point(filled=True, size=70).encode(
        x="Effect:Q", color=alt.Color("kind:N", legend=None),
        tooltip=["Alternative:N", alt.Tooltip("Effect:Q", format="+.1%"), alt.Tooltip("lo:Q", format="+.1%"),
                 alt.Tooltip("hi:Q", format="+.1%"), alt.Tooltip("p-value:Q", format=".3f"), "Conclusion:N"])
    return alt.layer(zero, bars, pts).properties(height=max(160, 28 * len(d)))


def windows_table(a: Analysis, expected: float | None = None) -> pd.DataFrame:
    rows = []
    for w in a.windows:
        rng = ("no lower limit" if w.lo_unbounded else f"{w.lo:+.1%}") + " to " + \
              ("no upper limit" if w.hi_unbounded else f"{w.hi:+.1%}")
        r = {"Window": w.label + (" (primary)" if w is a.primary else ""),
             "Estimated effect": f"{w.effect:+.1%}", "Plausible range (95%)": rng,
             "p-value": f"{w.p_value:.3f}", "Clear effect?": "Yes" if w.significant else "No",
             "Smallest detectable": f"±{w.mde(expected):.0%}",
             "Window length OK?": "Yes" if w.length_ok else "Too long for the history",
             "Actual (avg/week)": f"{w.observed:,.4g}", "Comparison (avg/week)": f"{w.predicted:,.4g}"}
        if w.abs_effect is not None:
            r["Cumulative difference"] = f"{w.abs_effect:+,.0f}"
        rows.append(r)
    return pd.DataFrame(rows)


def blend_table(a: Analysis) -> pd.DataFrame:
    if not a.prep.controls:
        return pd.DataFrame()
    return pd.DataFrame({"Control series": a.prep.controls, "Weight": np.round(a.blend.weights, 3)})


def plain_english(a: Analysis, verdict: Verdict, expected: float | None, outcome_name: str) -> str:
    w = a.primary
    s = (f"Over the {w.label.lower()} after the change, {outcome_name} averaged **{w.observed:,.4g}** a week. "
         f"Based on how it tracked the comparison line beforehand, we'd have expected about **{w.predicted:,.4g}** "
         f"without the change. That's a difference of **{w.effect:+.1%}**. ")
    if w.significant:
        s += (f"Only {w.p_value:.0%} of comparable stretches of weeks in the data had a gap this big, "
              "so it's very unlikely to be normal week-to-week variation. ")
    else:
        s += (f"Gaps this size were common before the change (p-value {w.p_value:.2f}), so it could be normal "
              "week-to-week variation. ")
    lo = "a fall of more than 80%" if w.lo_unbounded else f"{w.lo:+.1%}"
    hi = "a rise of several hundred percent" if w.hi_unbounded else f"{w.hi:+.1%}"
    s += f"The true effect is plausibly anywhere between **{lo}** and **{hi}**."
    if expected is not None:
        s += f" If the test result had carried over fully, we'd expect about **{expected:+.1%}**."
    return s


# ---------------------------------------------------------------- reports
def _md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_none_"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(lines)


def markdown_report(meta: dict, verdict: Verdict, a: Analysis, expected, checklist: dict,
                    notes: list[str], run_log: list[dict], summary_text: str,
                    data_checks: list | None = None, placebos: list | None = None, recipe: str | None = None,
                    plan_block: str | None = None, robustness=None) -> str:
    d = a.diagnostics
    out = [f"# Post-release impact check: {meta.get('name') or 'Untitled'}",
           f"_Generated {datetime.now():%d %b %Y %H:%M} with the 120Feet post-release impact checker (v2 engine)._", "",
           "## Summary", "", f"**Verdict: {verdict.label}.** {verdict.headline}", "", summary_text.replace("**", ""), "",
           "## Plan and review", "", plan_block or "_Plan not locked._", "",
           "## Inputs", "",
           f"- Client: {meta.get('client', '')}",
           f"- Test ticket: {meta.get('test_ticket', '')}  |  Release ticket: {meta.get('release_ticket', '')}",
           f"- Test's primary metric: {meta.get('primary_metric', '')}",
           f"- Test result: {meta.get('test_lift_text', 'not provided')}",
           f"- Share of the analysed outcome exposed to the change: {meta.get('exposure', '')}",
           f"- Expected effect if the test held: {'n/a' if expected is None else f'{expected:+.1%}'}",
           f"- Change date used: {meta.get('change_date')} ({meta.get('change_date_reason', '')})",
           f"- Outcome analysed: {meta.get('outcome_desc', '')}",
           f"- Data recipe: {recipe or 'none used'}",
           f"- Control series: {', '.join(a.prep.controls) or 'none'}",
           f"- Placebo metric(s): {', '.join(p.metric for p in placebos) if placebos else 'none (not checked for same-week events)'}",
           f"- Weeks before / after the change used: {a.prep.n_pre} / {a.prep.n_post}", "",
           "## Results by window", "", _md_table(windows_table(a, expected)), "",
           "## Data checks", ""]
    icon = {"ok": "✅", "warn": "⚠️", "fail": "❌", "skipped": "➖"}
    for c in data_checks or []:
        out.append(f"- {icon.get(c.status, '')} **{c.name}.** {c.message}")
    for p in placebos or []:
        out.append(f"- {'⚠️' if p.window.significant else '✅'} **Placebo '{p.metric}'.** {p.window.effect:+.1%} "
                   f"(p = {p.window.p_value:.3f}, range {p.window.lo:+.1%} to {p.window.hi:+.1%})")
    if not placebos:
        out.append("- ➖ **Placebo.** Not checked: no placebo metric selected.")
    if robustness is not None:
        from .robustness import robustness_display
        out += ["", "## Robustness", "", f"**{robustness.rating}.** {robustness.summary}", "",
                _md_table(robustness_display(robustness))]
    out += ["",
           "## Why this verdict", ""] + [f"- {x}" for x in verdict.details] + ["",
           "## Checks on the comparison line", "",
           f"- Typical forecast error before the change: ±{d.backtest_error:.1%} (without controls: ±{d.backtest_error_no_controls:.1%})",
           f"- Share of weekly variation explained before the change: {d.fit_r2:.0%}" if not np.isnan(d.fit_r2) else "",
           f"- Drift before the change: {d.drift_per_year:+.1%} a year (p = {d.drift_p:.2f}){' ⚠️' if d.drift_flag else ''}", "",
           "### Control weights", "", _md_table(blend_table(a)), "",
           "### Effect with each control removed", "", _md_table(a.leave_one_out), ""]
    if checklist:
        out += ["### Control checklist answers", ""]
        for c, ans in checklist.items():
            out.append(f"- **{c}**: " + "; ".join(f"{k} = {v}" for k, v in ans.items()))
        out.append("")
    if len(a.prep.dropped):
        dd = a.prep.dropped.assign(week=a.prep.dropped["week"].dt.strftime("%d %b %Y"))
        out += ["### Weeks left out", "", _md_table(dd), ""]
    if notes:
        out += ["### Data notes", ""] + [f"- {n}" for n in notes] + [""]
    if run_log:
        out += ["## Analysis history in this session", "",
                "Every run is listed so readers can see whether settings were changed after seeing results.", "",
                _md_table(pd.DataFrame(run_log)), ""]
    out += ["## Method", "",
            "The control series are blended (non-negative weights, ridge shrinkage chosen by backtesting) into a "
            "comparison line fitted on the weeks before the change. The effect is the average gap between the outcome "
            "and the comparison line after the change. The p-value and plausible range come from a conformal "
            "permutation test (Chernozhukov, Wüthrich & Zhu, 2021): the post-change gap is compared with the gap over "
            "every other stretch of the same length. In validation on real client data, false alarms stayed at or "
            "below about 5%. See docs/validation.md."]
    return "\n".join(x for x in out if x is not None)


def _chart_svg(chart: alt.Chart) -> str | None:
    """Render a chart to inline SVG (no internet needed to view the report). None if unavailable."""
    try:
        import vl_convert as vlc
        return vlc.vegalite_to_svg(chart.to_json())
    except Exception:  # noqa: BLE001
        return None


def html_report(md_text: str, charts: dict[str, alt.Chart], verdict: Verdict) -> str:
    """Self-contained HTML report.

    Charts are embedded as static SVG so the report works offline and on locked-down
    networks. If the SVG renderer isn't installed, charts fall back to interactive
    Vega charts loaded from a CDN.
    """
    colour = {"green": "#1E8449", "amber": "#B9770E", "red": "#C0392B", "grey": "#5D6D7E"}[verdict.colour]
    body = _md_to_html(md_text)
    svgs = {k: _chart_svg(c) for k, c in charts.items()}
    cdn = any(v is None for v in svgs.values())
    divs, embeds = [], []
    for i, (k, c) in enumerate(charts.items()):
        if svgs[k]:
            divs.append(f'<h3>{html.escape(k)}</h3><div class="chart">{svgs[k]}</div>')
        else:
            divs.append(f'<h3>{html.escape(k)}</h3><div id="c{i}" class="chart"></div>')
            embeds.append(f'vegaEmbed("#c{i}", {c.to_json()}, {{actions:false}});')
    scripts = ("""<script src="https://cdn.jsdelivr.net/npm/vega@5.30.0"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-lite@5.21.0"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-embed@6.26.0"></script>""" if cdn else "")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Post-release impact check</title>{scripts}
<style>body{{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:1000px;margin:32px auto;padding:0 16px;color:#1d2731;line-height:1.5}}
table{{border-collapse:collapse;margin:8px 0 16px;font-size:14px}}td,th{{border:1px solid #d5dbe1;padding:6px 8px;text-align:left}}
th{{background:#f3f5f7}}.verdict{{border-left:6px solid {colour};background:#f7f9fa;padding:12px 16px;margin:16px 0}}
.chart{{width:100%;margin-bottom:16px;overflow-x:auto}}.chart svg{{max-width:100%;height:auto}}h1{{font-size:26px}}h2{{margin-top:28px}}</style></head><body>
<div class="verdict"><strong>Verdict: {html.escape(verdict.label)}.</strong> {html.escape(verdict.headline)}</div>
{body}<h2>Charts</h2>{''.join(divs)}{'<script>' + ''.join(embeds) + '</script>' if embeds else ''}</body></html>"""


def _md_to_html(md: str) -> str:
    """Tiny Markdown converter for the report (headings, bullets, tables, paragraphs)."""
    out, in_list, in_table = [], False, False
    for line in md.split("\n"):
        if line.startswith("|"):
            cells = [html.escape(c.strip()) for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-"):
                continue
            if not in_table:
                out.append("<table>")
                in_table = True
                out.append("<tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr>")
            else:
                out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            txt = html.escape(line[2:]).replace("**", "")
            out.append(f"<li>{txt}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("#"):
            lvl = len(line) - len(line.lstrip("#"))
            out.append(f"<h{lvl}>{html.escape(line.lstrip('#').strip())}</h{lvl}>")
        elif line.strip():
            out.append(f"<p>{html.escape(line).replace('**', '')}</p>")
    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</table>")
    return "\n".join(out)

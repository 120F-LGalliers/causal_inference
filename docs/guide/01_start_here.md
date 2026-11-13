# Start here

## What this tool answers

> **We tested a change, it won, and it was built into the site. Is the benefit still there?**

An A/B test tells you a change worked *while the test ran*. Once it's built into the site for everyone, there's no control group any more, so you can't just compare A with B. The benefit might have stayed, faded, or never carried over (for example, the developers built it slightly differently from the test version).

This tool estimates what the metric **would have done without the change**, and compares that with what it actually did.

## The idea in one picture

Imagine two lines on a chart:

- **Navy line:** your metric (say, forgotten-username clicks per login).
- **Orange line:** a *comparison line*, built from other metrics that move with yours but couldn't be affected by the change (say, forgotten-*password* clicks per login).

Before the change, the two lines move together: same busy weeks, same quiet weeks. After the change, if the navy line breaks away from the orange line and stays away, that gap is the effect.

The tool then asks one more question: **is the gap after the change bigger than the gaps we normally see?** It compares the post-change gap with the gap over every other stretch of weeks in your data. If the post-change gap stands out from almost all of them, the effect is real.

## When to use it

- A test winner was built (productionised) and you want to know if the effect held.
- A change went live without a test (for example, a regulatory or compliance change) and you want an estimate of its impact.
- A change runs at 100% (for example, an always-on personalisation activity) and you want to know what it adds.

## When not to rely on it

- **Small effects.** If the test found a 2–5% uplift, this tool will usually say "inconclusive". That's not the tool failing; weekly business data is too noisy to see effects that small. Use a **holdout group** (5–10% of traffic who keep seeing the old version) instead.
- **Lots else changed at the same time.** A big promotion, a site redesign, a tracking change or another release in the same week can look like an effect.
- **Less than about 12 weeks of data before the change.** The tool needs history to learn what "normal" looks like. A year is much better.

## What you'll need before starting

| What | Where to get it |
|---|---|
| The date users first saw the change | Release ticket (e.g. MAG fix version). **If the winning variant ran at 100% in Target, Monetate or WTO before the release, use that date instead.** |
| The test's result, as a % change in its primary metric | Test readout or one-pager |
| The test dates | Test ticket (they're left out of the "before" period, because only some visitors saw the variant) |
| The test's control-group figure for its primary metric (e.g. "control conversion 2.30%") | Test readout, or the testing tool's report. Used to check your export is the same metric |
| A placebo metric: something the change couldn't affect | Your judgement, or the client's data recipe. See [Data checks and recipes](07_data_checks_and_recipes.md) |
| For client-facing results: a colleague to review | Anyone else on the team. See [Robustness and review](08_robustness_and_review.md) |
| A CSV of weekly or daily data | Your analytics tool. **Start from the client's data recipe if there is one**: it says exactly what to export. See also [Choosing the outcome](02_choosing_the_outcome.md) and [Choosing control series](03_choosing_controls.md) |

## The six steps in the app

The **Run a check** tab walks you through one step at a time. Your answers are kept as you move back and forth.

1. **Start.** Pick the client and where on the site the change was. That loads a *recipe*: the agreed metrics, and the columns to export (with a ready-made query where there is one). You can also try an example or re-open saved settings.
2. **The test.** Test name, the result, the test dates, and (recommended) the control group's figure from the readout.
3. **Go-live date.** When users first saw the change: the date it went to 100% in the testing tool, or the release date.
4. **Your data.** Upload the CSV and confirm which column is the metric to check. The tool checks your export against the test and flags known data issues.
5. **Comparison.** The tool scores the control series and suggests which to use. You answer a short checklist about each one, and optionally pick a placebo metric.
6. **Check & run.** Review a summary (with Edit links), say who it's for, then lock the plan and run.

Then you get the **results**: a verdict in plain English, the key chart, downloads, and more detail if you want it.

Set aside 30–60 minutes the first time, most of it getting the right data. After that, a check takes 15–20 minutes.

## The five verdicts

| Verdict | What it means | What to do |
|---|---|---|
| **Held** | The effect is still clearly there | Report it; the winner is still delivering |
| **Faded** | No clear effect, and the data rules out an effect as big as the test found | Investigate: was it built differently? Did user behaviour change? |
| **Reversed** | The metric moved the opposite way | Investigate urgently |
| **Inconclusive** | The data can't tell either way | Usually the effect is too small to see. Consider a holdout |
| **Unreliable** | Something in the data makes the check untrustworthy (too little history, or the comparison was drifting) | Fix the inputs (more history, different controls) and re-run |

Next: [Choosing the outcome](02_choosing_the_outcome.md)

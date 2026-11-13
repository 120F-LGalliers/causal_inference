# Data checks, placebo metrics and recipes

The statistics in this tool are only trustworthy if the data going in is right. **The most common way to get a wrong answer is picking the wrong data**, not the maths. This page explains the safeguards that catch that.

## Data recipes

A recipe is the agreed way to measure one kind of change for one client: which metric is the outcome, which is the denominator, which control series and placebo metrics are safe, how to export each one, and the client's known data problems.

**How to use one:**

1. In step 1 (Start), choose the client and where on the site the change was. That loads the recipe.
2. Read the **recipe card**. It tells you exactly what to export and how.
3. Export the series using the suggested column names. The app then pre-fills steps 2 and 3.
4. Any known data issues in your date range are listed after you upload.

A recipe marked **"not yet verified"** was drafted from early analyses and hasn't been checked by the account team. Use it, but double-check the definitions.

Recipes live in the `recipes/` folder of the repo, one file per client. See the **Data recipes** tab for the format and the current files. When you learn something new (a tracking break, a better control), add it, so the next person benefits.

## Check against the test

**What it catches:** exporting a slightly different metric from the one the test measured. This is the commonest mistake, and it silently ruins the analysis.

**How it works:** you enter the control group's figure from the test readout (e.g. "control conversion was 2.30%"). The tool works out the same figure from your export over the test weeks and compares the two.

| Difference | What the app says | What to do |
|---|---|---|
| Within 15% | ✅ Looks like the same metric | Carry on |
| 15–40% | ⚠️ Noticeable difference | Check the definition. Common legitimate reasons: the test targeted only part of the traffic; the test counted visitors where your export counts visits |
| Over 40% | ❌ Probably a different metric | Fix the export. The verdict becomes *Unreliable* unless you confirm the difference is expected and say why |

**Where to find the control figure:** the test readout or one-pager, or the testing tool's report (Adobe Target / A4T, Monetate, WTO). For counts (e.g. orders a week), also give the control group's share of traffic (often 50%).

## Placebo metric

**What it catches:** something else happening in the same week as the change, such as a promotion, another release, an outage or a tracking change. The tool can't otherwise tell that apart from your change.

**How it works:** you choose a metric the change **couldn't possibly affect**. The tool runs exactly the same analysis on it. It should show no change.

- **Placebo shows no change:** ✅ no sign of another event that week.
- **Placebo moved, by enough to explain your result:** the verdict becomes **Unreliable**. Find out what else happened.
- **Placebo moved, but not enough to explain your result:** the verdict stands, with a warning to investigate.

**Picking a good placebo:**

- It must be impossible for the change to affect. *Example:* login-page visits, for a change on the My Account dashboard (people log in before they see the dashboard).
- It should be exposed to the same kinds of events as the outcome: same site, same promotions, same releases.
- **It must be able to react to the events you're actually worried about.** "Can't be affected by the change" isn't enough on its own. Ask: *if something else had happened that week, which would distort my result, would this metric move?* If the likely culprit is a new deal or price change on the same page, a metric measured before people reach that page won't see it, so it gives false reassurance.
- It doesn't need to track the outcome closely (that's what controls are for).
- Don't reuse a control as the placebo.
- **If there's no metric that passes both tests, don't use one.** Leaving it blank is better than a placebo that can't see the events that matter. Rely on a control that shares those events (for example the app, which shares national deals and campaigns), the client's campaign calendar and the robustness panel. Recipes say when no placebo is recommended, and why.

**Why it's strongly encouraged:** without one, nothing checks for other events in the same week. The report states "not checked for same-week events" so readers know.

## Automatic checks

These run with every analysis and appear in the **Data checks** panel under the verdict.

**Denominator unaffected by the change.** If the change altered how many people reached the denominator (e.g. a homepage change that sends more people to the page you're using as the denominator), the rate is distorted. The tool tests whether the denominator jumped at the change date, beyond what the controls explain. *If it warns:* re-run with the raw count (no denominator) and compare. In testing it gave a false warning about 3% of the time and caught every 15% jump.

**No hidden break before the change.** Looks for a sudden, lasting step in the gap between outcome and comparison line before the change. That usually means a tracking or definition change. *If it warns:* find out what happened that week; if it's a tracking change, start the data after it or leave earlier weeks out. In testing it gave a false warning 2–3% of the time and caught about half of 15–30% steps, so **a clean result isn't proof** there was no break.

**All series cover the same weeks.** Flags series that start later, end earlier or have gaps. Weeks where any selected series is missing are left out.

**Known issues for this client.** From the recipe: tracking breaks or peaks that overlap your date range.

**Data-quality flags** (in step 4, Your data). Week-on-week jumps of more than 50%, zeros and missing weeks.

## Putting it together: a quick checklist before you share a result

- [ ] Used a recipe, or can explain why not
- [ ] Export matches the test's control figure (✅), or the difference is explained
- [ ] Change date confirmed, including whether the winner ran at 100% in the testing tool first
- [ ] Placebo metric checked (✅)
- [ ] No unexplained warnings in the Data checks panel
- [ ] Checklist answered thoughtfully for every control
- [ ] Analysis history shows no unexplained changes of settings

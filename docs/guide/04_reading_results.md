# Reading the results

## The verdict box

The coloured box at the top gives the answer in one sentence: **Held, Faded, Reversed, Inconclusive, Unreliable**, or, when you didn't give a test result, **Changed** or **No clear change**. Open **"Why this verdict"** to see the numbers behind it.

## The Data checks panel

Directly under the verdict: a row of icons for the checks on your data (✅ fine, ⚠️ look at this, ❌ problem, ➖ not checked), and the placebo result. It opens automatically if anything needs attention. Each item is explained in [Data checks and recipes](07_data_checks_and_recipes.md). A placebo that moved by enough to explain your result, or an export that doesn't match the test, turns the verdict to *Unreliable*.

## The three headline numbers

**Smallest detectable effect.** The smallest change this data could reliably pick up (about an 80% chance of spotting it). If the test found something smaller than this, a "no clear effect" result tells you very little. *Think of it as the resolution of a camera: you can't see details smaller than a pixel.*

**Expected effect if the test held.** Test result × share of the outcome exposed. This is what we'd see if the benefit carried over fully.

**Measured effect.** The estimated effect in the primary window, with its **plausible range** underneath.

## Plausible range (95%)

The range of effects the data can't rule out. If it's −31% to −9%, the true effect is very likely somewhere in there; we can't be more precise.

- **Range doesn't include 0** → a clear effect (positive or negative).
- **Range includes 0** → can't rule out "no effect".
- **Range includes 0 *and* the expected effect** → can't tell: *Inconclusive*.
- **Range includes 0 but excludes the expected effect** → the full test effect didn't carry over: *Faded*.

## p-value

How unusual the post-change gap is compared with the rest of the data. Specifically: the share of comparable stretches of weeks whose gap was at least as extreme as the post-change one.

- **p = 0.02:** only 2% of stretches looked this extreme. Very unlikely to be normal variation.
- **p = 0.40:** 40% of stretches looked this extreme. Quite normal; could easily be noise.

We call an effect "clear" when p is below 0.05 (5%). This is a convention, not a magic line: p = 0.06 is not very different from p = 0.04. Read it together with the range.

## Windows

Results are shown for up to three windows:

- **First 8 weeks:** did the effect show up straight away?
- **Primary window:** used for the verdict. Picked automatically as the longest standard window (8, 13, 26 or 52 weeks) that's no more than half the history before the change. You can change it.
- **All weeks after the change:** the longest view. Often too long for the history; the table says so.

**Why "no more than half the history"?** The test compares the post-change stretch with every other stretch of the same length. If the window is very long compared with the history, there are hardly any comparable stretches, and the test can't detect much. See [Validation](../validation.md).

## Chart 1: actual vs comparison line

- **Navy:** your outcome.
- **Orange dashed:** the comparison line, i.e. what the outcome would be expected to do based on the controls. Before the change it's the fit; after the change it's the prediction.
- **Red line:** the change date. **Grey bands:** weeks left out.

**What good looks like:** before the red line, the two lines move together. After it, if there's an effect, the navy line moves away and stays away.

**Warning signs:** before the red line the lines drift apart steadily, or diverge badly in particular periods (often peak trading). The comparison line isn't capturing something.

## Chart 2: the weekly gap

The gap between the outcome and the comparison line each week, as a percentage.

- **Grey bars:** before the change. They should wobble around zero, mostly inside the shaded band (the typical forecast error).
- **Navy bars:** after the change.
- **Orange line:** the average gap in the primary window, i.e. the estimated effect.

This is the most intuitive chart. If the navy bars sit clearly away from zero while the grey bars hover around it, the effect is visible to the eye.

## Chart 3: is the post-change stretch unusual?

This chart shows exactly what the p-value is calculated from. Assuming there was no effect, the tool fits the comparison line on all the weeks, then works out the average gap over every stretch of the same length as the primary window (wrapping round from the end of the data back to the start). Each grey dot is one of those stretches; the orange dot is the stretch after the change. **The p-value is the share of dots at least as far from zero as the orange one.** If the orange dot sits well outside the grey cloud, the effect is real.

Because the line is fitted assuming no effect, the orange dot is usually a bit closer to zero than the headline effect. That's expected; it's the fair way to test.

## Checks on the comparison line

- **Typical forecast error.** How far off the comparison line typically was when predicting a few weeks ahead, before the change. Compared with no controls, this shows whether your controls helped.
- **Drift.** Whether the gap was steadily rising or falling before the change. If it was, part of any "effect" could just be the drift continuing; the tool warns you.
- **Control weights.** How much the comparison line relies on each control.
- **Effect with each control removed.** If removing one control changes the result a lot, the conclusion depends heavily on that control. Make sure it's a good one.
- **Weeks left out.** Which weeks weren't used, and why.

## Analysis history

Every time you click **Run analysis**, the settings and result are logged and included in the report. This keeps things honest: if someone tries five sets of controls and reports the one they like, readers can see that.

**Good practice:** decide on the outcome, controls and window *before* looking at results, and stick with them. If you change something, have a reason that isn't "the result looked better", and say what it was.

## Worked examples

**Tesco Mobile EAOA-1541: forgotten username copy.** The test found −38% to −45% forgotten-username clicks. Analysed outcome: forgotten-username visits per login visit (~70% exposed → expected −28%). The forgot-password control didn't improve the forecast (the forgot-username rate was stable before the change anyway), so the tool didn't suggest it. Result: first 8 weeks −23%, plausible range −28% to −8%, p = 0.04 → **Held**. Over all 92 weeks −26% (range −35% to −20%, p = 0.01), though that window is longer than the history, so the 8-week result is the one to quote.

**Tesco Mobile EAOA-2008: Family Perks tile.** The test found +2.4% multiline orders. Result: +4.8% over 26 weeks, range −4% to +24%, smallest detectable ±20% → **Inconclusive**. The data can't see an effect as small as 2.4%. A holdout would be needed.

## Common mistakes

| Mistake | Effect | Fix |
|---|---|---|
| Using the release date when the winner ran at 100% in Target earlier | Looks for the effect on the wrong date, usually finds nothing | Use the Target date |
| Not leaving out the test period | The "before" period is contaminated by the variant | Tick "leave out the test period" |
| Control downstream of the change | Hides the effect | See the "never use" list in [Choosing control series](03_choosing_controls.md) |
| Primary window longer than half the history | Very low power; "no clear effect" means little | Use the suggested window |
| Trying lots of settings and reporting the best | False confidence | Decide upfront; the run log shows all attempts |
| Reading "Inconclusive" as "the test didn't work" | Wrong conclusion | It means the data can't tell |
| Exporting a slightly different metric from the test's | Measures the wrong thing | Enter the control figure; use the recipe |
| Skipping the placebo metric | Other same-week events go unnoticed | Pick one; the recipe usually suggests one |

Next: [How it works](05_how_it_works.md)

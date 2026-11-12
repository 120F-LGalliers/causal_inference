# Glossary and FAQ

## Glossary

**Backtest.** Pretending the change happened at an earlier date, forecasting the following weeks, and checking how close the forecast was. Used to choose settings and to measure how accurate the comparison line is.

**Causal inference.** Working out whether one thing *caused* another, not just whether they happened together.

**Comparison line.** The tool's estimate of what the outcome would have done without the change, built from the control series.

**Conformal (permutation) inference.** Judging whether an effect is real by comparing it with the same measurement over every other comparable stretch of data, rather than relying on a formula. Keeps false alarms at the level you ask for.

**Control series.** A metric that moves with the outcome but couldn't be affected by the change. Also called a comparison series, covariate or donor series.

**Counterfactual.** What would have happened if the change hadn't been made. Can't be observed, only estimated.

**Denominator.** The traffic the outcome comes from (e.g. visits to a page), used to turn a count into a rate.

**Detectable effect (smallest).** The smallest effect the data could pick up about 80% of the time.

**Drift.** The gap between outcome and comparison line steadily rising or falling before the change. Breaks the key assumption.

**Effect.** The average percentage difference between the actual outcome and the comparison line after the change.

**Expected effect.** The test's result × the share of the outcome exposed to the change: what we'd see if the benefit carried over fully.

**False alarm (false positive).** Saying there's an effect when there isn't. The tool keeps this to about 5% of checks.

**Holdout.** A small group (often 5–10%) kept on the old experience after a winner is built, so its effect can be measured directly. The gold standard for small effects.

**Interrupted time series.** Comparing a metric's path before and after a known interruption (the change).

**Log scale.** Using logarithms so that effects are relative (%) rather than absolute.

**Outcome.** The metric being checked.

**p-value.** The share of comparable stretches of weeks whose gap was at least as extreme as the post-change one. Small (below 0.05) = unlikely to be normal variation.

**Placebo.** Running the analysis on a date when nothing changed, to check the tool doesn't "find" effects that aren't there. The permutation test effectively runs a placebo for every possible stretch.

**Plausible range (95% interval).** Effects the data can't rule out.

**Power.** The chance of detecting an effect that really exists.

**Primary window.** The number of weeks after the change used for the verdict.

**Ridge (shrinkage).** Gently pulling weights towards zero so the blend doesn't over-fit noise.

**Synthetic control.** Building a comparison from a weighted blend of unaffected units. Our comparison line is a version of this.

**Transition week.** The week the change went live, if mid-week. Left out because it's part before, part after.

## FAQ

**The test found +3% but the tool says Inconclusive. Did the change stop working?**
Not necessarily. Inconclusive means the data can't tell. Weekly business data usually can't detect effects below about 10%. Check the "smallest detectable effect": if it's bigger than the expected effect, this result is expected and says nothing either way. For small effects, use a holdout.

**Can I use this to prove a test result to a client?**
It's supporting evidence, not proof. A *Held* verdict with a clean chart is strong evidence. Present it with the chart and the plausible range, not just the verdict.

**Why does the tool want a year of history?**
To learn what "normal" looks like across seasons, and to have enough comparable stretches for the permutation test. With less, the plausible range gets wide and small effects become invisible.

**What if the winner ran at 100% in Target for months before the release?**
Use the date it went to 100% as the change date. The release itself changed nothing for users.

**Can I analyse a change that was never A/B tested?**
Yes. Leave "the test result is known" unticked. The verdict becomes *Changed* or *No clear change*.

**The tool suggests a control I know was affected by the change. What should I do?**
Don't use it. The automatic checks can't know how your site works. Your judgement and the checklist come first.

**My result changes when I change the controls. Which do I believe?**
If the result depends heavily on one control (see "Effect with each control removed"), be cautious. Pick controls on their merits (closeness, unexposed, no tracking issues) *before* looking at results, and report all attempts (the run log does this automatically).

**Can I check daily instead of weekly?**
Upload daily data and it's summed into weeks. Weekly is more robust to day-of-week patterns and reporting delays.

**What's the difference between v1 and v2?**
v2 (the default) uses blended controls and a permutation test. It keeps false alarms at about 5% and gives the same answer every time. v1 uses a CausalImpact-style model. It's more willing to call effects, but raised false alarms in up to 20% of cases in our validation. v1 is kept for comparison only.

**Where can I see how the tool was validated?**
[docs/validation.md](../validation.md).

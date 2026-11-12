# How it works

You don't need this page to use the tool. It's here for anyone who wants to understand, or explain to a client, what's going on underneath.

## The problem: there's no control group any more

During an A/B test, the control group shows what would have happened without the change. Once the change is built for everyone, that group is gone. Instead, we need to **estimate** what would have happened. That estimate is called the **counterfactual**. Everything in this tool is about building a good counterfactual and being honest about how uncertain it is.

This family of methods is called **causal inference with observational data**. This specific design is an **interrupted time series with a comparison series**, closely related to the **synthetic control method**.

## Step 1: put everything on a weekly log scale

- Daily data is summed into Monday–Sunday weeks; weekly data is aligned to Monday.
- The outcome (or outcome ÷ denominator) and every control are converted to logarithms.

**Why logs?** Effects in our world are relative ("+5%"), not absolute ("+37 orders"). On a log scale, a 5% rise looks the same whether the metric is 100 or 10,000, and the effect comes out directly as a percentage.

**Weeks left out:** the week the change went live (if it was mid-week, that week is part before, part after), the test period, and anything you excluded.

## Step 2: build the comparison line

Using only the weeks **before** the change, the tool finds:

> log(outcome) ≈ constant + w₁ × log(control 1) + w₂ × log(control 2) + …

with three rules:

1. **Weights can't be negative.** A control either helps or is ignored. This mirrors the synthetic control method and stops nonsensical blends.
2. **Weights are shrunk slightly towards zero (ridge regression).** This stops the blend chasing noise when there are several similar controls.
3. **How much to shrink is chosen by backtesting**: the setting that best predicts the next 8 weeks at many earlier dates wins.

With no controls, the comparison line is simply the average level before the change.

The comparison line is then extended past the change date using the controls' actual values. That's the counterfactual.

## Step 3: measure the gap

Each week: **gap = log(actual) − log(comparison)**. Before the change, the gap wobbles around zero. The **estimated effect** is the average gap over the window after the change, converted back to a percentage: effect = e^(average gap) − 1.

## Step 4: is the gap real? (the permutation test)

This is the part that changed in version 2, and the reason the tool is now trustworthy.

**The question:** is the post-change average gap bigger than we'd expect from normal week-to-week wobble?

**The method** (Chernozhukov, Wüthrich & Zhu, 2021, "conformal inference"):

1. Assume, for now, that there was **no effect**.
2. Fit the comparison line using **all** the weeks (before and after), consistent with that assumption.
3. Work out the gap for every week.
4. Take the average gap over the post-change stretch. Then do the same for **every other stretch of the same length**: start at week 1, week 2, week 3 and so on, wrapping around the end of the data back to the start.
5. **p-value** = the share of stretches whose average gap is at least as large (in either direction) as the post-change one.

If there really was no effect, the post-change stretch is just another stretch, equally likely to land anywhere in the ranking, so it only lands in the top 5% about 5% of the time. That's why the false-alarm rate is controlled **by construction**, without trusting a statistical model's assumptions.

**The plausible range** comes from repeating the test assuming different true effects ("suppose it was really −10%: remove 10% from the post-change weeks and re-test"). Every effect the test *can't* reject is in the range.

**Smallest detectable effect** = 1.43 × half the width of the range. An effect that size would be detected about 80% of the time. (1.43 = (1.96 + 0.84) / 1.96, the standard 80%-power calculation.)

### Why not just use a standard regression?

We tried. Standard regression with "robust" standard errors raised false alarms in 9–19% of simulated cases instead of 5%, because weekly business data is correlated from week to week, histories are short, and the formulas behind standard errors assume lots of data. The permutation test avoids those formulas entirely.

### Why not the original CausalImpact approach (v1)?

Version 1 used a Bayesian-style structural time-series model, the approach behind Google's CausalImpact. In our tests it:

- raised false alarms in up to 20% of cases on real client data,
- gave different answers on the same data (it relies on random simulation),
- produced intervals that widened so fast that long windows were almost never conclusive.

It's still available in the app as a comparison, under "Compare with the v1 engine".

## The key assumption

> **Before the change, the gap behaves the same way throughout.**

That means no steady drift, and no period where the comparison line systematically fails (for example, every Black Friday). If that's true, the post-change stretch is comparable to the earlier stretches, and the test is valid.

The tool checks for **drift** (a trend in the pre-change gap) and warns you. You can check the rest by eye on the weekly gap chart: the grey bars should look like random wobble around zero.

## Assumptions you have to check yourself

1. **The controls weren't affected by the change.** The tool checks for jumps at the change date, but can't prove a negative. The checklist covers the rest.
2. **Nothing else changed at the same time** that affected the outcome but not the controls.
3. **The change date is right**, including the case where the winner ran at 100% in a testing tool before release.
4. **Tracking was consistent.**

## Limitations, honestly

- **It can't see small effects.** With typical weekly noise, effects below about 10–20% usually come out *Inconclusive*. That's a property of the data, not the tool.
- **Long windows need long histories.** Keep the primary window to no more than half the "before" period.
- **Seasonal spikes the controls don't capture make everything noisier.** Consider leaving peak weeks out.
- **It estimates the average effect over the window**, not week by week.
- **It's one check, not proof.** Treat a *Held* as strong evidence, especially alongside a sensible chart.

## Further reading

- Chernozhukov, V., Wüthrich, K. & Zhu, Y. (2021). *An exact and robust conformal inference method for counterfactual and synthetic controls.* Journal of the American Statistical Association.
- Abadie, A. (2021). *Using synthetic controls: feasibility, data requirements, and methodological aspects.* Journal of Economic Literature.
- Brodersen, K. et al. (2015). *Inferring causal impact using Bayesian structural time-series models.* Annals of Applied Statistics (the CausalImpact paper behind v1).
- Cunningham, S. *Causal Inference: The Mixtape* (free online), chapters on synthetic control.

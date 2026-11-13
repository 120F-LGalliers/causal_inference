# Choosing control series

This is the most important step. **The tool is only as good as the comparison line, and the comparison line is only as good as the control series you give it.**

## What a control series is

A control series is any metric that:

1. **moves with your outcome** before the change (same busy and quiet weeks, same promotions, same seasons), and
2. **could not have been affected by the change.**

The tool learns how your outcome moved with the controls before the change, then uses the controls to predict what the outcome would have done afterwards. If a control was itself affected by the change, the prediction moves with the effect and hides it.

**An analogy.** You want to know whether a new fertiliser helped your tomatoes. Your neighbour's tomatoes, grown in the same weather without the fertiliser, are a great comparison. Your own tomatoes on the other side of the fence are a terrible one if fertiliser could leak through the fence.

## Where to look: five places, best first

Find as many candidates as you can and put them all in the CSV. The tool checks them for you.

### 1. The same metric, for people who couldn't see the change

Usually the best controls.

| Change | Control |
|---|---|
| New tile on the My Account dashboard | The same orders from visits that **didn't** view the dashboard |
| Change on desktop only | The same metric on mobile |
| Change on handset pages | The same metric on SIM-only pages |
| Change on web only | The same metric in the app |
| Change in one market or school | The same metric in another market or school |

**Watch out for:** people switching between the groups *because of* the change (they see the tile, then order through the app tomorrow), and the same people appearing in both groups on different visits.

### 2. A sibling action on the same page or journey

A different action taken by the same visitors that the change shouldn't affect.

| Change | Control |
|---|---|
| Forgotten **username** copy on the login form | Forgotten **password** visits per login visit |
| Enquiry form field change | Visits to the form's landing page |
| Basket messaging | Product page views |

Tick **"Express control series per the same denominator"** when the sibling shares the outcome's traffic (e.g. both are "per login visit").

### 3. Overall demand

Metrics that show how busy things are generally.

- Total site visits, or visits to unrelated sections
- Brand search volume (Google Trends, or paid-search impressions for the brand name)
- New-customer orders, if the change only affects existing customers (or the other way round)

Weaker than 1 and 2, but useful as an extra control.

### 4. Upstream traffic

Visits that arrive *before* the changed step. If the change is at checkout, sessions reaching the product page can't be affected by it.

**Never use anything downstream of the change.** If the change is on the product page, checkout completions will move *with* the effect and hide it.

### 5. A sister brand or separate site

Same company, same seasons and promotions, different site. Weak on its own, useful in combination.

## Things that rule a control out

- It's **downstream** of the change, or includes the same people at the same moment.
- Its **tracking changed** during the period (a tag broke, a definition changed). Check the data-quality flags.
- It had **its own event** around the change date (a separate launch, promo or outage) that the outcome didn't.
- Its relationship with the outcome **changes steadily over time** (e.g. app share growing month by month).
- It's the **denominator** you've already used.

## Ratio series

Often the best control is a *rate* in an unexposed group, e.g. orders ÷ visits for visitors who didn't see the change. Recipes create these for you. Otherwise use **"Advanced: date labelling and ratio series"** in step 4 (Your data) to build one from two columns.

## What the tool checks for you

When you click **Score the candidates** (step 5), each candidate gets these scores:

| Column | What it means | Good looks like |
|---|---|---|
| **Forecast improvement** | At many earlier dates, the tool predicted the next 8 weeks of the outcome with and without this control. This is how much smaller the errors were with it. **The most important column.** | Positive, ideally +10% or more |
| **Weight in blend** | When all candidates are combined, how much the comparison line relies on this one (0 = ignored) | Above 0 |
| **Correlation: levels** | Do they share trends and seasons? (−1 to 1) | Positive, ideally 0.5+ |
| **Correlation: weekly changes** | Do they react to the same week-to-week shocks? | Positive |
| **Own jump at change date** | Did this control itself jump when the change went live? ⚠️ means a clear jump | No ⚠️ |

A ✅ means the candidate improves the forecast and didn't jump at the change date. Treat it as a suggestion, not an instruction.

**About the ⚠️ jump warning.** If a control jumped when your change went live, there are two explanations:

1. The change affected it, so **don't use it**: it would hide the effect.
2. Something else happened that week that affected both, such as a promotion. Then it may be **exactly the control you want**, because it soaks up that other event.

Only you can tell which. Find out what happened that week.

**Absence of ⚠️ isn't proof.** The jump check can miss small jumps. That's why the checklist matters.

## The checklist

For every control you select, the app asks five questions. You have to answer all of them before running the analysis:

1. Could the change have reached the people or visits in this series?
2. Could the change move customers between this series and the outcome?
3. Is this series driven by the same things as the outcome?
4. Did something happen to only one of them around the change date?
5. Has this series been tracked the same way throughout?

If an answer suggests a problem, the app warns you. Your answers go into the report, so reviewers can see the reasoning.

## How many controls?

**One to three good ones.** The tool blends them and shrinks the weights to avoid over-fitting, but each extra series is another chance of contamination. One excellent control from places 1–2 beats five weak ones.

## How the blend works (in brief)

The tool finds the combination of controls (non-negative weights, plus a constant) that best tracked your outcome before the change, working on a log scale, so a weight of 0.5 means "when this control rises 10%, the outcome tends to rise 5%". It holds back slightly on the weights, by an amount chosen by backtesting, so it doesn't chase noise. Weights can't be negative, so a control can never be used "upside down".

## If you can't find a good control

- Run with no controls. The comparison line is then just the outcome's average level before the change. Treat the result with extra caution, especially if the outcome is seasonal.
- Leave out unusual weeks (peak trading, outages) from the "before" period using **"Advanced: leave out other weeks"** in step 3 (Go-live date).
- For future changes, plan a **holdout**.

Next: [Reading the results](04_reading_results.md)

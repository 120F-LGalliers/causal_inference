# Validation: how reliable is the tool?

We tested both engines in two ways:

1. **Simulated data**, where we control exactly how noisy the data is and whether there's an effect.
2. **Real Tesco Mobile data with fake effects injected.** We took stretches of real weekly data where nothing changed, picked many fake change dates, multiplied the outcome after each date by a known amount, and checked whether each engine noticed.

Two numbers matter:

- **False-alarm rate.** How often the tool says "there's an effect" when there isn't one. We ask for 5%. Higher than that means the tool will sometimes tell you a winner held when it didn't.
- **Detection rate (power).** How often the tool spots an effect that really is there. Higher is better, but never at the expense of false alarms.

## Why we changed the engine

The v1 engine (a CausalImpact-style model) produced false alarms far more often than it should:

| Data | v1 false alarms | v2 false alarms | Target |
|---|---|---|---|
| Simulated, many scenarios | 8–10% | 1–6% | 5% |
| Real TM data, forgot-username rate | 0% | 0–3% | 5% |
| Real TM data, multiline orders, 8-week window | **20%** | 0% | 5% |

v1 also gave different answers on the same data depending on random simulation, and its intervals widened so fast that 26-week checks were rarely conclusive.

We also tested a textbook regression approach (Newey-West standard errors): it raised false alarms in **9–19%** of cases. A leave-out-one-stretch variant raised them in **10–16%**. Both were rejected.

## v2 results: simulated data

Simulated weekly data with a shared demand trend captured by one control, plus autocorrelated noise (4% weekly). 300 runs per row with no effect, 150 with a 10% effect.

| Weeks before change | Window | False alarms (no effect) | Detected (10% effect) |
|---|---|---|---|
| 20 | 8 weeks | 2–4% | 46–48% |
| 20 | 26 weeks | 2–5% | 49–53% |
| 52 | 8 weeks | 5–6% | 73–83% |
| 52 | 26 weeks | 1–2% | 60–67% |
| 100 | 8 weeks | 3–5% | 91–92% |
| 100 | 26 weeks | 4% | 78–81% |

Interval coverage (how often the 95% range contains the true effect): **94–96%** in every scenario tested. That's what a 95% range should do.

## v2 results: real Tesco Mobile data with injected effects

| Data | Window | Fake dates | 0% | 5% | 10% | 20% | 30% |
|---|---|---|---|---|---|---|---|
| Forgot-username rate (2025-26) | 8 weeks | 33 | 3% | 6% | 12% | 82% | 100% |
| Forgot-username rate (2025-26) | 26 weeks | 24 | 0% | 0% | 21% | 75% | 100% |
| Multiline orders per dashboard visit (2024-25) | 8 weeks | 15 | 0% | 0% | 0% | 20% | 27% |
| Multiline orders per dashboard visit (2024-25) | 26 weeks | 6 | 0% | 0% | 0% | 0% | 0% |

(The 0% column is the false-alarm rate; the rest are detection rates.)

For comparison, v1 on the same data detected more (e.g. 45% at 10% on the forgot-username 8-week window), but its multiline results were unusable: a 20% false-alarm rate means a good share of its "detections" were noise.

## What this tells us

- **When v2 says an effect is there, you can trust it.** False alarms stayed at or below about 5% everywhere we looked.
- **v2 is cautious.** It will say "inconclusive" more often than v1. We chose this deliberately: telling a client a winner held when it didn't is worse than saying "we can't tell".
- **Clean, close-to-the-change metrics work well.** The forgot-username rate (a metric right next to the change, with a good comparison) detected 20%+ effects reliably.
- **Noisy, seasonal, downstream metrics with short histories don't.** Multiline orders had big Black Friday spikes in only 20–40 weeks of history. Even a 30% effect was usually missed, and 26-week windows couldn't be tested at all.
- **Long windows need long histories.** The test compares the post-change stretch with every other stretch of the same length. If the window is more than about half the history, there aren't enough comparable stretches, and power collapses. The app now picks the primary window automatically (no more than half the history) and warns if you choose a longer one.

## Practical guidance that follows from this

1. Get **at least a year** of data before the change if you can.
2. Prefer an outcome **close to the change** (clicks or visits on the changed element) over a downstream one (orders).
3. Use **8- or 13-week windows** unless you have well over a year of history.
4. If the comparison doesn't capture peak trading (Black Friday, Christmas), consider **leaving those weeks out** of the pre-period.
5. For small effects (under ~10%), plan a **holdout group** instead.

## Data checks: how often do they warn?

The automatic data checks (added later) were calibrated the same way, on simulated weekly data:

| Check | False warnings (nothing wrong) | Catches |
|---|---|---|
| Denominator jumped at the change date | 3% | 100% of 15% jumps |
| Hidden break before the change | 2–3% | 27–45% of 15% steps; 55–62% of 30% steps |
| Placebo metric moved | ~5% (same test as the main analysis) | Same power as the main analysis |

The hidden-break check is deliberately strict, to avoid crying wolf, so it misses smaller breaks. A clean result isn't proof there was no break.

## Reproducing this

```bash
python validation/run_validation.py
```

It writes `validation/results.csv`. The simulated checks are in `tests/test_calibration.py` and run with the normal test suite.

Reference for the method: Chernozhukov, V., Wüthrich, K. & Zhu, Y. (2021). *An exact and robust conformal inference method for counterfactual and synthetic controls.* Journal of the American Statistical Association, 116(536).

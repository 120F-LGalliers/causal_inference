# Post-release impact checker (v2)

A Streamlit app for answering one question:

> **We tested a change, it won, and it was built into the site. Is the benefit still there?**

It builds a **comparison line** from metrics that couldn't be affected by the change, measures the gap between your metric and that line after the change, and uses a **permutation test** to judge whether the gap is bigger than normal week-to-week wobble. The answer comes back in plain English: *Held, Faded, Reversed, Inconclusive* or *Unreliable*.

**Colleagues new to this should start with the in-app Guide tab** (or `docs/guide/01_start_here.md`).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Pick an example from the dropdown to see a full run before using your own data.

```bash
pip install -r requirements-dev.txt
pytest                                  # behaviour, calibration and app smoke tests
python validation/run_validation.py     # injected-effect study on real series (~1 min)
```

## What changed in v2, and why

| | v1 (CausalImpact-style) | v2 (default) |
|---|---|---|
| Comparison line | State-space model with a drifting baseline | Blend of controls with non-negative weights and backtest-tuned shrinkage; steady baseline |
| Is the effect real? | Model-based simulated intervals | Conformal permutation test (Chernozhukov, Wüthrich & Zhu, 2021) |
| False alarms in validation | 8–10% simulated, **up to 20%** on real client data | **≤ ~5%** everywhere tested |
| Same data, same answer? | No (random simulation) | Yes |
| Long windows | Intervals balloon | Usable, if the history is long enough |
| Choosing controls | Correlation screening (picked the wrong series in testing) | Forecast backtest + automatic weighting + required checklist |

v2 is more cautious: it says *Inconclusive* more often. That's deliberate. Telling a client a winner held when it didn't is worse than saying "we can't tell". Full results: `docs/validation.md`. v1 remains available in the app as a comparison.

## Safeguards against wrong data (phase 1)

The commonest way to get a wrong answer is feeding the tool the wrong data, so v2 includes:

- **Data recipes** (`recipes/*.yaml`): per-client, agreed definitions of outcomes, denominators, controls and placebo metrics, with export instructions and known data issues. Picking one pre-fills the app. Tesco Mobile is seeded; other clients to be added with the account teams.
- **Check against the test:** the export is compared with the test's control-group figure over the test weeks; a big mismatch makes the verdict *Unreliable* unless explained.
- **Placebo metric** (strongly encouraged): the same analysis on a metric the change couldn't affect; if it moves enough to explain the result, the verdict becomes *Unreliable*.
- **Automatic checks:** denominator jump at the change date, hidden breaks before the change, coverage gaps, client known issues.

See `docs/guide/07_data_checks_and_recipes.md`.

## Robustness and review (phase 2)

- **Robustness panel:** every run is repeated under a fixed list of alternatives (each control removed, no controls, change date ±1 week, peak weeks left out, raw count, last 52 weeks only). Rated *Robust*, *Somewhat sensitive* or *Fragile*; a fragile result is flagged in the headline and a green verdict turns amber. Users can't choose the alternatives, so they can't cherry-pick.
- **Locked plans:** results only appear after you choose a purpose (*Internal check* / *Client-facing*), enter your name and lock the plan. The plan ID is a hash of every setting plus a fingerprint of the weekly data, and every run is logged in the report.
- **Review packs and sign-off:** client-facing results are marked *NOT REVIEWED* until a second person uploads the review pack and CSV in the **Review** tab. The tool confirms the pack is unaltered, the data is identical and the results reproduce exactly, then the reviewer answers six questions and approves or asks for changes. The signed report carries the reviewer's name and answers.
- **Offline reports:** charts in the HTML report are embedded as static SVG (via `vl-convert-python`), so reports open without internet access.

Limits: names are self-declared and the integrity hash is tamper-evident, not a security control. It's a process aid, not an audit system. See `docs/guide/08_robustness_and_review.md`.

## Monetate lookup

For Monetate clients, the app can look up each experience's start and end dates, status and traffic split
from Monetate's Metadata API, to find the date a winner went to 100%. Credentials go in the hosted app's
Secrets, never in the repo. See `docs/monetate.md`.

## Before the first push to GitHub

- Make the repository **private** in 120Feet's GitHub organisation: it contains weekly aggregate client data
  in `tests/fixtures/` and `sample_data/`.
- Check `git status` shows no `.streamlit/secrets.toml`, `*.pem` or client exports (all git-ignored).
- Add Monetate credentials in the hosting platform's Secrets, not as files.

## Inputs a user needs

| Input | Where it comes from |
|---|---|
| Change date | Release ticket fix version. **If the winner ran at 100% in a testing tool first, use that date** |
| Test result (% change) | Test readout |
| Share of the outcome the change could reach | Judgement (see Guide → Choosing the outcome) |
| Test dates | Test ticket (left out of the "before" period) |
| Test's control-group figure for the primary metric | Test readout / testing tool report |
| Placebo metric | Recipe, or judgement |
| CSV: date + one column per series | Analytics export: outcome, denominator, candidate controls |

At least 12 weeks before the change are required; a year is strongly recommended.

## How it works (short version)

1. **Weekly, log scale.** Daily data summed into Monday–Sunday weeks; weekly data aligned using the labelling convention you confirm. Mid-week change weeks, the test period and any excluded weeks are left out.
2. **Comparison line.** log(outcome) ≈ constant + Σ wᵢ·log(controlᵢ), weights ≥ 0, ridge strength chosen by rolling-origin backtests on the pre-period.
3. **Effect.** Average post-change gap, as a %.
4. **Permutation test.** Under "no effect", refit on all weeks; compare the post-change average gap with the average gap of every other (circular) stretch of the same length → p-value. Inverting the test over a grid of effects gives the 95% plausible range. Smallest detectable effect = 1.43 × half-width (≈80% power).
5. **Primary window** auto-chosen as the longest of 8/13/26/52 weeks that is ≤ half the pre-period, because power collapses for longer windows.
6. **Diagnostics.** Backtest error with and without controls, drift in the pre-period gap, leave-one-control-out sensitivity, weeks dropped.
7. **Verdict** compares the result with the expected effect (test result × share exposed).

Details in `docs/guide/05_how_it_works.md`.

## Repo layout

```
app.py                      Streamlit UI (Run / Guide / Data recipes / Reliability tabs)
impact_tool/
  data.py                   CSV loading, week conventions, weekly alignment, data-quality flags
  synth.py                  control blending (non-negative ridge) and rolling backtests
  conformal.py              v2 engine: windows, permutation test, intervals, diagnostics, verdict
  controls.py               candidate screening + checklist
  report.py                 charts, plain-English summary, Markdown and HTML reports
  checks.py                 export-vs-test reconciliation, denominator, hidden-break and coverage checks, placebo
  recipes.py                loading and validating client data recipes
  model.py                  v1 engine (comparison only)
recipes/                    client data recipes (YAML), template and format guide
docs/
  guide/                    beginner guide, shown in the app
  validation.md             how reliable it is, with numbers
validation/run_validation.py  injected-effect study on real series
sample_data/                example inputs
tests/                      pytest: behaviour, calibration, regression (TM), app smoke test
.github/workflows/tests.yml CI
```

## Data handling

- Uploaded files are processed in memory and not stored.
- `tests/fixtures/` and `sample_data/example_forgot_username.csv` contain **weekly aggregate Tesco Mobile data** (no personal data). Remove them before sharing outside 120Feet; the synthetic example still works, but the TM regression tests and validation study need replacing.
- `.gitignore` excludes `data/` and `uploads/`.

## Known limitations

- Small effects (under ~10%, often more) usually come back *Inconclusive*. Use holdouts for those.
- Windows longer than half the history have little power; the app warns.
- Seasonal spikes the controls don't capture reduce power; consider leaving peak weeks out.
- The automatic checks can't tell whether a control was affected by the change. The checklist and the user's judgement matter.

## Roadmap

- ~~Phase 2: robustness panel and plan export with peer sign-off~~ (done)
- Phase 3: recipes for Domino's, Nord Anglia, Ripe, Avis and TSB with the account teams
- Phase 4: connector-driven data pulls (fewer manual exports)

- Pooled analysis across many winners ("on average, winners keep X% of their test effect")
- Direct data pulls from Adobe Analytics, Monetate and WTO
- Day-level analysis with day-of-week effects
- Batch mode across every winner with a finished release ticket

# Data recipes

A **recipe** is an agreed way to measure one kind of change for one client: which metric to use as the outcome, which as the denominator, which control series and placebo metrics are safe, and exactly how to export them.

**Why they exist:** the most common way to get a wrong answer from the tool isn't the statistics, it's picking the wrong data. Recipes capture what the account team already knows (where the data lives, which variables mean what, which periods have tracking problems) so each check doesn't start from scratch.

## How the app uses them

1. In step 1, pick the client and a recipe.
2. The app shows the recipe card: definitions, export instructions, known issues and cautions.
3. When you upload a CSV with the suggested column names, the app pre-fills the outcome, denominator, controls and placebo.
4. It warns if your date range overlaps a known issue, or starts before the client's data starts.

You can always change the choices. The recipe is a starting point, not a rule.

## File format

One YAML file per client in this folder (e.g. `tesco_mobile.yaml`). Copy `_template.yaml` to start. Top-level fields:

| Field | What it's for |
|---|---|
| `client`, `owner`, `last_reviewed` | Who maintains it and when it was last checked |
| `data_source` | Tool, report suite or property, which view to use |
| `data_starts` | First date with usable data |
| `release_process` | How to find release dates; whether winners run at 100% in the testing tool first |
| `known_issues` | Tracking breaks, definition changes, recurring peaks (with dates where known). `applies_to` lists the recipe ids affected; leave it empty if every recipe is affected |
| `reference` | Variable meanings, page names: anything people keep looking up |
| `recipes` | The list of recipes (below) |

Each recipe has an `id`, `name`, `use_when`, `example_tests`, `verified`, and:

- `outcome`, `denominator` (or `null`): `column` (suggested CSV column name), `definition`, `how_to_export`
- `controls`: list with `column`, `definition`, `why`, `cautions`, `how_to_export`
- `placebo`: list with `column`, `definition`, `why`
- `typical_detectable_effect`, `notes`

## Rules of thumb

- **Mark new recipes `verified: false`** until someone on the account team has checked the definitions against the analytics setup and a past test.
- **Record the `why`** for every control and placebo: why it moves with the outcome, and why the change can't affect it.
- **Add known issues as soon as you find them**, with dates. A tracking break that isn't written down will catch the next person out.
- **Note the detectable effect** after each real check, so people know what's realistic before they start.
- **Review every six months**, or when the analytics setup changes. Update `last_reviewed`.
- **Change via pull request**, so changes are reviewed and versioned with the tool.

## Clients

| File | Status |
|---|---|
| `tesco_mobile.yaml` | Seeded Nov 2026 from the first TM checks; owner needed; recipes unverified |
| Domino's, Nord Anglia, Ripe, Avis, TSB | To be added with the account teams |

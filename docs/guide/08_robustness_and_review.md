# Robustness, locked plans and review

Two habits protect against fooling ourselves: **checking the answer doesn't depend on one particular set of choices**, and **having someone else check the work before it goes to a client**. The tool builds both in.

## The robustness panel

Every analysis involves choices: which controls, which change date, which weeks to include, rate or count. If the conclusion only holds for one set of choices, it's **fragile**, and someone could (even without meaning to) have picked the set that gives the answer they hoped for.

So the tool automatically re-runs your analysis under a **fixed list of alternatives**. You can't add, remove or pick them; that's deliberate.

| Alternative | What it tests |
|---|---|
| Each control removed in turn | Does the result depend on one control? |
| No control series | Is the result driven by the controls at all? |
| Change date one week earlier / later | Is the date right? Is there a lag or anticipation? |
| Peak trading weeks left out (mid-Nov to early Jan) | Are Black Friday and Christmas distorting the comparison? |
| Raw count instead of the rate | Is the denominator distorting the rate? |
| Only the most recent 52 weeks of history | Has the relationship with the controls changed over time? |
| Shorter windows (8 and 13 weeks) | Shown for context only, not scored, because fewer weeks means less power |

Each alternative reaches one of three conclusions: *clear rise*, *clear fall* or *no clear effect*. The rating:

- **Robust:** at least 80% of the scored alternatives agree with the main analysis, and none finds a clear effect in the opposite direction.
- **Somewhat sensitive:** 60–80% agree, none opposite.
- **Fragile:** fewer than 60% agree, or any alternative finds a clear effect in the opposite direction.

A fragile result keeps its verdict, but the headline says it's fragile and a green verdict turns amber. **Don't present a fragile result to a client without saying so.**

**Reading the chart:** each row shows the effect (dot) and plausible range (line) under one alternative; the orange row is the main analysis. A robust result has rows that broadly line up. If one row sits far away from the others, that choice matters. Find out why.

**Useful patterns:**

- *Change date one week earlier gives a much bigger effect:* the change may have gone live earlier than you think (for example, at 100% in the testing tool).
- *No controls gives a very different answer:* the result depends on the controls, so be sure they're right.
- *Raw count disagrees with the rate:* check the denominator warning.
- *Peaks left out changes the answer:* the controls don't capture peak trading. Consider leaving those weeks out in the main analysis.

## Locking the plan

Before results appear, you choose:

- **Purpose:** *Internal check* or *Client-facing*.
- **Your name.**

Then, in step 6 (Check & run), you click **Lock plan and run**. The tool records every setting and a **fingerprint** of the exact weekly data (a SHA-256 hash), and gives the plan an **ID**. If you change any setting or the data, you get a new plan ID, and the analysis history shows every plan you ran.

**Good practice:** decide the outcome, controls, placebo and window first, based on the recipe and the checks, *then* lock and run. If you change something after seeing the result, write down why. The reviewer will see the history.

## Review (client-facing results)

Client-facing results must be reviewed by a **second person** before they're shared. Until then, the report is marked *NOT REVIEWED: not for client use*.

**Analyst:**

1. Run the check with purpose *Client-facing*.
2. Download the **review pack** (JSON).
3. Send the review pack **and your CSV** to a colleague.

**Reviewer:**

1. Open the **Review** tab and upload both files.
2. The tool checks:
   - **Pack unaltered:** the pack hasn't been edited since it was created.
   - **Plan ID consistent:** the settings match the plan ID.
   - **Same data:** the CSV produces exactly the same weekly data the analyst used.
   - **Results reproduce:** re-running the plan gives identical results. The engine is deterministic, so any difference means something changed.
3. Read the verdict, key settings, data checks, placebo, robustness and the analyst's history.
4. Answer the six review questions:
   - Data matches the recipe, and the export matched the test's control figure (or deviations are justified)
   - Change date is right, including the 100%-in-the-testing-tool question
   - Controls couldn't have been affected by the change; checklist answers are sensible
   - A sensible placebo was used (or its absence is acceptable)
   - The result is robust, or its sensitivity is clearly stated
   - The wording is fair: no over-claiming, and "Inconclusive" isn't presented as "didn't work"
5. Choose **Approved** or **Changes needed**, add comments, and sign.
6. Download the **signed report** and **signed pack** and send them back.

**Rules the tool enforces:**

- The reviewer's name must differ from the analyst's.
- Every question must be answered.
- Any "No" or "Not sure" needs a comment.
- You can't approve with a "No".
- A pack that fails verification can only get "Changes needed".

**Limits, honestly:** there are no user accounts, so names are self-declared, and the integrity check is a tamper-evident hash rather than a security control. It makes accidental or casual changes visible; it won't stop someone determined to fake a review. It's a process aid, not an audit system.

## Internal checks

Internal checks don't need review. Their reports say "review not required (internal check)". If an internal result later goes to a client, re-run it as *Client-facing* and get it reviewed.

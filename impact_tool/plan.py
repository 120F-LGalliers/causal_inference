"""Locked analysis plans, review packs and sign-off.

Why
---
Deciding the outcome, controls and window *before* seeing the result, and having a
second person check the work before it goes to a client, are the two most effective
protections against fooling ourselves.

How it works
------------
1. **Lock the plan.** When you click "Lock plan and run", the tool records every setting
   plus a *fingerprint* of the exact weekly data used (a SHA-256 hash). The plan ID is a
   hash of the settings and fingerprint, so any change to either gives a new plan ID.
2. **Review pack.** For client-facing work, you download a review pack (JSON): the plan,
   the results and the report. Send it with the CSV to a reviewer.
3. **Review.** In the Review tab, the reviewer uploads both. The tool checks the data
   fingerprint matches, re-runs the analysis from the plan and confirms the results
   match exactly (the engine is deterministic). The reviewer then works through a
   checklist and approves or asks for changes.
4. **Signed report.** Approved packs produce a report stamped with the reviewer's name,
   date and comments, plus a signed pack.

Limits
------
There are no user accounts, so names are self-declared and the "signature" is a
tamper-evident hash, not a security control. It makes accidental or casual changes
visible; it doesn't stop a determined person faking a review.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

import numpy as np
import pandas as pd

PACK_VERSION = 1

REVIEW_CHECKLIST = [
    ("data", "The outcome, denominator and controls match the recipe (or the deviations are justified), and the "
             "export matched the test's control-group figure."),
    ("date", "The change date is right, including whether the winner ran at 100% in the testing tool before release."),
    ("controls", "The control series couldn't have been affected by the change, and the checklist answers are sensible."),
    ("placebo", "A sensible placebo metric was used (or its absence is acceptable for this case)."),
    ("robust", "The result is robust, or its sensitivity is clearly stated."),
    ("wording", "The conclusion and wording are fair: no over-claiming, and 'Inconclusive' isn't presented as 'didn't work'."),
]


def fingerprint(weekly: pd.DataFrame) -> str:
    """SHA-256 of the weekly data actually analysed (values rounded to 9 significant figures)."""
    d = weekly.copy().sort_index()
    d = d.reindex(sorted(d.columns), axis=1)
    vals = d.to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        rounded = np.where(np.isfinite(vals), np.vectorize(lambda v: float(f"{v:.9g}"))(np.nan_to_num(vals)), np.nan)
    payload = json.dumps({"index": [str(i.date()) for i in d.index], "columns": list(d.columns),
                          "values": [[None if np.isnan(x) else x for x in row] for row in rounded]}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _canonical(settings: dict) -> dict:
    drop = {"checklist_answers"}          # recorded, but don't change the analysis
    return {k: settings[k] for k in sorted(settings) if k not in drop}


def plan_id(settings: dict, data_fp: str) -> str:
    payload = json.dumps({"settings": _canonical(settings), "data": data_fp}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def make_plan(settings: dict, data_fp: str, author: str, purpose: str) -> dict:
    return {"pack_version": PACK_VERSION, "plan_id": plan_id(settings, data_fp), "data_fingerprint": data_fp,
            "author": author, "purpose": purpose, "locked_at": datetime.now().isoformat(timespec="seconds"),
            "settings": settings}


def make_pack(plan: dict, results: dict, report_md: str, run_log: list[dict]) -> dict:
    pack = {**plan, "results": results, "report_markdown": report_md, "run_log": run_log, "review": None}
    pack["integrity"] = _integrity(pack)
    return pack


def _integrity(pack: dict) -> str:
    core = {k: pack[k] for k in ("plan_id", "data_fingerprint", "settings", "results", "author", "purpose", "review")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()


def verify(pack: dict, data_fp: str, rerun_results: dict) -> list[tuple[str, bool, str]]:
    """Checks a reviewer's upload. Returns (check, passed, message)."""
    out = []
    ok = pack.get("integrity") == _integrity(pack)
    out.append(("Pack unaltered", ok, "The pack hasn't been edited since it was created." if ok else
                "The pack's contents don't match its integrity hash: it was edited after it was created."))
    ok = pack.get("plan_id") == plan_id(pack.get("settings", {}), pack.get("data_fingerprint", ""))
    out.append(("Plan ID consistent", ok, "The plan ID matches the recorded settings." if ok else
                "The plan ID doesn't match the settings: the settings were changed."))
    ok = data_fp == pack.get("data_fingerprint")
    out.append(("Same data", ok, "The CSV you uploaded gives exactly the same weekly data the analyst used." if ok else
                "The CSV you uploaded gives different weekly data from the analyst's. Ask for the exact file."))
    diffs = [k for k in ("window_weeks", "effect", "lo", "hi", "p_value", "verdict", "robustness", "placebos", "checks")
             if pack.get("results", {}).get(k) != rerun_results.get(k)]
    ok = not diffs
    out.append(("Results reproduce", ok, "Re-running the plan gives identical results." if ok else
                "Re-running the plan gives different results for: " + ", ".join(diffs) + "."))
    return out


def sign(pack: dict, reviewer: str, decision: str, answers: dict, comments: str) -> dict:
    signed = dict(pack)
    signed["review"] = {"reviewer": reviewer, "decision": decision, "answers": answers, "comments": comments,
                        "reviewed_at": datetime.now().isoformat(timespec="seconds")}
    signed["integrity"] = _integrity(signed)
    return signed


def review_block_md(review: dict | None, plan: dict) -> str:
    head = (f"**Plan ID:** {plan['plan_id']} · **Purpose:** {plan['purpose']} · **Analyst:** {plan.get('author') or 'not given'}"
            f" · **Plan locked:** {plan['locked_at']}")
    if not review:
        status = ("**Review status: NOT REVIEWED. Not for client use until a second person has reviewed it.**"
                  if plan["purpose"] == "Client-facing" else "**Review status:** not required (internal check).")
        return head + "\n\n" + status
    lines = [head, "", f"**Review: {review['decision']}** by {review['reviewer']} on {review['reviewed_at']}"]
    for k, q in REVIEW_CHECKLIST:
        lines.append(f"- {review['answers'].get(k, '—')}: {q}")
    if review.get("comments"):
        lines += ["", f"Reviewer comments: {review['comments']}"]
    return "\n".join(lines)

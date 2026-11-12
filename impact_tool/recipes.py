"""Loading and checking client data recipes (recipes/*.yaml)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

RECIPE_DIR = Path(__file__).resolve().parents[1] / "recipes"
REQUIRED_TOP = ["client", "data_source", "recipes"]
REQUIRED_RECIPE = ["id", "name", "outcome"]


@dataclass
class KnownIssue:
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    affects: str
    advice: str
    applies_to: list[str]

    def overlaps(self, a: pd.Timestamp, b: pd.Timestamp) -> bool:
        if self.start is None:
            return True            # undated / recurring: always worth showing
        if self.end is None:
            return self.start <= b  # ongoing since start
        return self.start <= b and self.end >= a


def _ts(v):
    return None if v in (None, "", "null") else pd.Timestamp(str(v))


def load_all(directory: Path = RECIPE_DIR) -> dict[str, dict]:
    """Return {client name: parsed file} for every recipes/*.yaml except the template."""
    out = {}
    for f in sorted(directory.glob("*.yaml")):
        if f.name.startswith("_"):
            continue
        data = yaml.safe_load(f.read_text())
        problems = validate(data)
        if problems:
            raise ValueError(f"{f.name}: " + "; ".join(problems))
        data["_file"] = f.name
        out[data["client"]] = data
    return out


def validate(data: dict) -> list[str]:
    problems = [f"missing '{k}'" for k in REQUIRED_TOP if k not in (data or {})]
    if problems:
        return problems
    ids = set()
    for i, r in enumerate(data.get("recipes") or []):
        for k in REQUIRED_RECIPE:
            if k not in r:
                problems.append(f"recipe {i + 1} missing '{k}'")
        if r.get("id") in ids:
            problems.append(f"duplicate recipe id '{r.get('id')}'")
        ids.add(r.get("id"))
        if not (r.get("outcome") or {}).get("column"):
            problems.append(f"recipe '{r.get('id')}' has no outcome column")
    return problems


def known_issues(client: dict) -> list[KnownIssue]:
    return [KnownIssue(_ts(k.get("start")), _ts(k.get("end")), k.get("affects", ""), k.get("advice", ""),
                       list(k.get("applies_to") or [])) for k in client.get("known_issues") or []]


def recipe_columns(recipe: dict) -> dict:
    """Suggested column names: outcome, denominator, controls, placebo."""
    den = recipe.get("denominator") or {}
    return {"outcome": recipe["outcome"]["column"],
            "denominator": den.get("column") or None,
            "controls": [c["column"] for c in recipe.get("controls") or [] if c.get("column")],
            "placebo": [p["column"] for p in recipe.get("placebo") or [] if p.get("column")]}


def date_warnings(client: dict, first: pd.Timestamp, last: pd.Timestamp, recipe_id: str | None = None) -> list[str]:
    """Warnings about the uploaded date range for this client (and recipe, if given)."""
    out = []
    start = _ts(client.get("data_starts"))
    if start is not None and first < start:
        out.append(f"Your data starts {first:%d %b %Y}, but {client['client']} data is only reliable from "
                   f"{start:%d %b %Y}. Earlier weeks may be empty or wrong.")
    for k in known_issues(client):
        if k.applies_to and recipe_id not in k.applies_to:
            continue
        if k.overlaps(first, last):
            when = ("Recurring" if k.start is None else f"from {k.start:%d %b %Y}" if k.end is None
                    else f"{k.start:%d %b %Y}" if k.start == k.end else f"{k.start:%d %b %Y} – {k.end:%d %b %Y}")
            out.append(f"**Known issue ({when}):** {k.affects}. {k.advice}")
    return out

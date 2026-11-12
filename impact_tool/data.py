"""Loading, weekly alignment and data-quality checks."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Spec:
    """Everything the model needs to know about the series and the dates."""

    outcome: str                      # numerator column (e.g. orders)
    denominator: str | None           # optional denominator column (e.g. visits)
    controls: list[str]               # comparison / confounder columns
    change_date: pd.Timestamp         # date users first saw the change
    exclude: list[tuple[pd.Timestamp, pd.Timestamp]] = field(default_factory=list)
    controls_as_rate: bool = False    # divide controls by the same denominator as the outcome

    @property
    def is_rate(self) -> bool:
        return bool(self.denominator)


def load_csv(file, date_col: str | None = None) -> tuple[pd.DataFrame, str]:
    """Read a CSV and parse the date column (first column if not given)."""
    df = pd.read_csv(file)
    date_col = date_col or df.columns[0]
    raw = df[date_col].astype(str).str.strip()
    parsed = pd.to_datetime(raw, format="ISO8601", errors="coerce")      # 2025-01-31
    if parsed.isna().any():
        parsed = pd.to_datetime(raw, dayfirst=True, errors="coerce")    # 31/01/2025 (UK)
    if parsed.isna().any():
        parsed = pd.to_datetime(raw, format="mixed", dayfirst=True, errors="coerce")  # 'Jan 6, 2025'
    df[date_col] = parsed
    if df[date_col].isna().any():
        bad = int(df[date_col].isna().sum())
        raise ValueError(f"{bad} rows have a date that couldn't be read in column '{date_col}'.")
    return df, date_col


WEEK_CONVENTIONS = {
    "auto": "Work it out from the dates",
    "daily": "Daily rows",
    "week_start_monday": "Weekly rows labelled with the Monday the week starts",
    "week_start_sunday": "Weekly rows labelled with the Sunday the week starts",
    "week_end_sunday": "Weekly rows labelled with the Sunday the week ends",
    "week_end_saturday": "Weekly rows labelled with the Saturday the week ends",
}
# Days to add to a weekly label to land inside the Monday-Sunday week it describes
_OFFSET = {"week_start_monday": 0, "week_start_sunday": 1, "week_end_sunday": -6, "week_end_saturday": -5}


def detect_convention(dates: pd.Series) -> str:
    """Best guess at how dates are labelled."""
    gaps = dates.sort_values().diff().dt.days.dropna()
    if len(gaps) and gaps.median() <= 1.5:
        return "daily"
    dow = dates.dt.dayofweek.mode()
    dow = int(dow.iloc[0]) if len(dow) else 0
    return {0: "week_start_monday", 6: "week_start_sunday", 5: "week_end_saturday"}.get(dow, "week_start_monday")


def to_weekly(df: pd.DataFrame, date_col: str, cols: list[str],
              convention: str = "auto") -> tuple[pd.DataFrame, list[str]]:
    """Return a Monday-indexed weekly frame of the given columns.

    Daily data is summed into Monday-to-Sunday weeks and incomplete first/last weeks
    are dropped. Weekly data is mapped to the Monday of the week it describes, using
    the labelling convention (week start or week end, Monday/Sunday/Saturday).
    """
    notes: list[str] = []
    d = df[[date_col] + cols].copy()
    d[cols] = d[cols].apply(pd.to_numeric, errors="coerce").astype(float)
    d = d.sort_values(date_col)
    if convention == "auto":
        convention = detect_convention(d[date_col])
        notes.append(f"Date format detected as: {WEEK_CONVENTIONS[convention]}. Change it in step 2 if that's wrong"
                     + (" (Sunday dates can also mean 'week ending Sunday')." if convention == 'week_start_sunday' else "."))

    if convention == "daily":
        week_start = d[date_col].dt.to_period("W-SUN").dt.start_time
        grouped = d.groupby(week_start)
        weekly = grouped[cols].sum(min_count=1)
        days = grouped[date_col].nunique()
        partial = days[days < 7].index
        edge = [w for w in partial if w in (weekly.index.min(), weekly.index.max())]
        if edge:
            weekly = weekly.drop(edge)
            notes.append(f"Dropped {len(edge)} incomplete week(s) at the start/end of the data.")
        mid = [w for w in partial if w not in edge]
        if mid:
            notes.append(f"{len(mid)} week(s) in the middle have fewer than 7 days of data: "
                         + ", ".join(w.strftime('%d %b %Y') for w in mid[:5]))
        notes.append("Daily data summed into Monday–Sunday weeks.")
    else:
        shifted = d[date_col] + pd.to_timedelta(_OFFSET[convention], unit="D")
        week_start = shifted.dt.to_period("W-SUN").dt.start_time
        weekly = d.assign(_w=week_start).groupby("_w")[cols].sum(min_count=1)
        if week_start.duplicated().any():
            notes.append("Some weeks appear more than once and were added together. Check the date format.")

    full = pd.date_range(weekly.index.min(), weekly.index.max(), freq="7D")
    missing = full.difference(weekly.index)
    if len(missing):
        notes.append(f"{len(missing)} missing week(s): "
                     + ", ".join(w.strftime('%d %b %Y') for w in missing[:5]))
    weekly = weekly.reindex(full)
    weekly.index.name = "week"
    return weekly, notes


def quality_flags(weekly: pd.DataFrame, jump: float = 0.5) -> pd.DataFrame:
    """Flag zeros, gaps and sudden week-on-week jumps (often tracking breaks)."""
    rows = []
    for c in weekly.columns:
        s = weekly[c]
        for w in s[s.isna()].index:
            rows.append((c, w, "missing"))
        for w in s[s <= 0].index:
            rows.append((c, w, "zero or negative"))
        ch = s.pct_change(fill_method=None)
        for w, v in ch[ch.abs() > jump].items():
            rows.append((c, w, f"{v:+.0%} vs previous week"))
    out = pd.DataFrame(rows, columns=["series", "week", "issue"])
    return out.sort_values(["week", "series"]).reset_index(drop=True)


def change_weeks(index: pd.DatetimeIndex, change_date: pd.Timestamp) -> tuple[pd.Timestamp | None, pd.Timestamp]:
    """Return (transition_week, first_post_week).

    If the change landed mid-week, that week is a transition week and is left out
    of both periods. If it landed on a Monday, there is no transition week.
    """
    change_date = pd.Timestamp(change_date).normalize()
    wk = change_date.to_period("W-SUN").start_time
    if wk == change_date:
        return None, wk
    return wk, wk + pd.Timedelta(days=7)


def model_frame(weekly: pd.DataFrame, spec: Spec) -> pd.DataFrame:
    """Log-transformed frame: column 'y' plus one column per control."""
    out = pd.DataFrame(index=weekly.index)
    num = weekly[spec.outcome]
    y = num / weekly[spec.denominator] if spec.is_rate else num
    out["y_raw"] = y
    out["y"] = np.log(y.where(y > 0))
    for c in spec.controls:
        x = weekly[c] / weekly[spec.denominator] if (spec.controls_as_rate and spec.is_rate) else weekly[c]
        out[c] = np.log(x.where(x > 0))
    return out


def excluded_mask(index: pd.DatetimeIndex, exclude: list[tuple[pd.Timestamp, pd.Timestamp]]) -> np.ndarray:
    """True for weeks overlapping any excluded window."""
    m = np.zeros(len(index), dtype=bool)
    for a, b in exclude:
        a, b = pd.Timestamp(a), pd.Timestamp(b)
        m |= (index + pd.Timedelta(days=6) >= a) & (index <= b)
    return m

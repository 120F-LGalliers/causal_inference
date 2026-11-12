"""120Feet post-release impact tool: did a test winner's effect hold after go-live?

v2 engine (default): impact_tool.conformal  (blended controls + permutation inference)
v1 engine (comparison): impact_tool.model   (CausalImpact-style state-space model)
"""
from .data import Spec, load_csv, to_weekly, quality_flags, model_frame, change_weeks, WEEK_CONVENTIONS
from .conformal import analyse, make_verdict, ALPHA
from .controls import screen, scores_table, CHECKLIST, SAFE_ANSWER

__all__ = ["Spec", "load_csv", "to_weekly", "quality_flags", "model_frame", "change_weeks", "WEEK_CONVENTIONS",
           "analyse", "make_verdict", "ALPHA", "screen", "scores_table", "CHECKLIST", "SAFE_ANSWER"]

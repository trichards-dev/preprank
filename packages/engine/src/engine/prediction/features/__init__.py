"""Prediction-layer feature implementations.

Each Phase-2 prediction feature is a small, pure module under this package.
Features are flagged on via ``PredictionConfig.enabled_features`` and consumed
by the validator's predictor/runner — they never mutate the LHSAA power
rating itself.
"""
from __future__ import annotations

from .margin import (
    capped_margin,
    precompute_team_week_margins,
    team_margin_signal,
)
from .recent_form import (
    game_recency_weight,
    precompute_team_week_form,
    team_form_signal,
)
from .sos_depth import (
    precompute_depth_sos_signal,
    team_opponents_through_week,
)
from .totals import (
    precompute_team_week_totals,
    team_offense_defense,
)

__all__ = [
    "capped_margin",
    "team_margin_signal",
    "precompute_team_week_margins",
    "game_recency_weight",
    "team_form_signal",
    "precompute_team_week_form",
    "team_opponents_through_week",
    "precompute_depth_sos_signal",
    "team_offense_defense",
    "precompute_team_week_totals",
]

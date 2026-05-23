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

__all__ = [
    "capped_margin",
    "team_margin_signal",
    "precompute_team_week_margins",
]

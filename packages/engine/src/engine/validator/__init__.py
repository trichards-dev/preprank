"""PrepRank engine validator framework.

Public API:
- :func:`run_validation` — run validation for one config across (sports x seasons).
- :class:`RunResult` — aggregated per-run result returned by ``run_validation``.
- :func:`load_run_inputs` — assemble (games, ratings, prior-season ratings, teams)
  for one (sport, season).
- Metrics: :func:`game_winner_accuracy`, :func:`brier_score`,
  :func:`reliability_bins`, :func:`rating_projection_delta`,
  :func:`bootstrap_ci`, :func:`playoff_field_accuracy`.
"""
from __future__ import annotations

from .data import load_run_inputs
from .metrics import (
    bootstrap_ci,
    brier_score,
    game_winner_accuracy,
    playoff_field_accuracy,
    rating_projection_delta,
    reliability_bins,
)
from .predictor import PredictionRecord, predict_game
from .runner import RunResult, run_validation

__all__ = [
    "run_validation",
    "RunResult",
    "load_run_inputs",
    "predict_game",
    "PredictionRecord",
    "game_winner_accuracy",
    "brier_score",
    "reliability_bins",
    "rating_projection_delta",
    "bootstrap_ci",
    "playoff_field_accuracy",
]

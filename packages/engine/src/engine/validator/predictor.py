"""Prediction primitive for the validator.

Thin wrapper over :func:`engine.win_probability.win_probability_v2` so that
all validator runs share one well-tested code path. ``PredictionRecord`` is
the per-game payload that flows through metrics + DB writes + CSV export.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.prediction.config import PredictionConfig
from engine.win_probability import win_probability_v2


@dataclass
class PredictionRecord:
    """One game's prediction + the context needed to score it.

    Score / spread fields stay ``None`` at the baseline run; Phase 2a wires up
    a scoring model and will populate them.
    """

    game_id: int
    home_team_id: int
    away_team_id: int
    home_win_probability: float
    predicted_home_score: float | None
    predicted_away_score: float | None
    predicted_spread: float | None
    home_rating_pregame: float
    away_rating_pregame: float
    home_cold_start: bool
    away_cold_start: bool
    actual_home_won: bool | None
    sport: str
    season_year: int
    week_number: int


def predict_game(
    home_rating: float,
    away_rating: float,
    sport: str,
    config: PredictionConfig,
) -> float:
    """Return P(home_team wins) given pre-game ratings.

    Pure function over :func:`win_probability_v2`; kept as a separate symbol
    so Phase 2 features can later compose around it without changing the
    validator's call sites.
    """
    return win_probability_v2(home_rating, away_rating, config, sport=sport)

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
    home_margin_signal: float = 0.0,
    away_margin_signal: float = 0.0,
    home_form_signal: float = 0.0,
    away_form_signal: float = 0.0,
) -> float:
    """Return P(home_team wins) given pre-game ratings.

    Pure function over :func:`win_probability_v2`. Two prediction-layer
    signals can shift each side's effective rating before the matchup is
    fed to ``win_probability_v2``:

    * ``margin`` (Phase 2a): when ``'margin' in config.enabled_features``,
      the per-sport weight from ``config.margin_weight_by_sport`` (falling
      back to ``config.margin_weight``) is applied to each side's pre-game
      capped-margin signal.
    * ``recent_form`` (Phase 2b): when ``'recent_form' in config.enabled_features``,
      the per-sport weight from ``config.form_weight_by_sport`` (falling
      back to ``config.form_weight``) is applied to each side's pre-game
      recency-weighted form signal.

    When neither feature is enabled, both signals are ignored and the
    call collapses to the legacy ``win_probability_v2`` path —
    guaranteeing zero behavior change for baseline runs. When both are
    enabled the contributions are additive.
    """
    home_eff = home_rating
    away_eff = away_rating

    if "margin" in config.enabled_features:
        weight = config.margin_weight_by_sport.get(sport, config.margin_weight)
        home_eff += weight * home_margin_signal
        away_eff += weight * away_margin_signal

    if "recent_form" in config.enabled_features:
        fw = config.form_weight_by_sport.get(sport, config.form_weight)
        home_eff += fw * home_form_signal
        away_eff += fw * away_form_signal

    return win_probability_v2(home_eff, away_eff, config, sport=sport)

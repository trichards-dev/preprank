"""Logistic win probability model.

P(home_win) = 1 / (1 + exp(-k * (home_rating - away_rating + home_advantage)))

The legacy ``win_probability`` / ``win_probability_batch`` signatures are
frozen for backward compatibility. The ``_v2`` variants accept a
:class:`PredictionConfig` and route the same math through the config's
``k_factor`` / ``home_advantage`` (with optional per-sport HFA override),
so that a default config produces results numerically identical to the
legacy path.
"""
from __future__ import annotations

import numpy as np

from engine.prediction.config import PredictionConfig


def win_probability(
    home_rating: float,
    away_rating: float,
    home_advantage: float = 0.5,
    k: float = 0.8,
) -> float:
    """Scalar win probability for home team."""
    exponent = -k * (home_rating - away_rating + home_advantage)
    return float(1.0 / (1.0 + np.exp(exponent)))


def win_probability_batch(
    home_ratings: np.ndarray,
    away_ratings: np.ndarray,
    home_advantage: float = 0.5,
    k: float = 0.8,
) -> np.ndarray:
    """Vectorized win probability for arrays of matchups."""
    exponent = -k * (home_ratings - away_ratings + home_advantage)
    return 1.0 / (1.0 + np.exp(exponent))


def _resolve_hfa(config: PredictionConfig, sport: str | None) -> float:
    """Return the HFA for ``sport`` from config, falling back to the global value."""
    if sport is not None and sport in config.home_advantage_by_sport:
        return config.home_advantage_by_sport[sport]
    return config.home_advantage


def win_probability_v2(
    home_rating: float,
    away_rating: float,
    config: PredictionConfig,
    sport: str | None = None,
) -> float:
    """Scalar win probability driven by a :class:`PredictionConfig`.

    Pulls ``k`` from ``config.k_factor`` and HFA from
    ``config.home_advantage_by_sport.get(sport, config.home_advantage)``.
    With an empty ``enabled_features`` list and a default config, the
    result is numerically identical to ``win_probability(home, away)``.
    """
    hfa = _resolve_hfa(config, sport)
    return win_probability(
        home_rating=home_rating,
        away_rating=away_rating,
        home_advantage=hfa,
        k=config.k_factor,
    )


def win_probability_batch_v2(
    home_ratings: np.ndarray,
    away_ratings: np.ndarray,
    config: PredictionConfig,
    sport: str | None = None,
) -> np.ndarray:
    """Vectorized win probability driven by a :class:`PredictionConfig`.

    See :func:`win_probability_v2` for parameter resolution. With a
    default config this returns the same array as the legacy
    ``win_probability_batch`` call.
    """
    hfa = _resolve_hfa(config, sport)
    return win_probability_batch(
        home_ratings=home_ratings,
        away_ratings=away_ratings,
        home_advantage=hfa,
        k=config.k_factor,
    )

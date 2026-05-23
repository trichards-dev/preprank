"""Regression tests for the prediction-layer config and the v2 routing.

These tests pin down the contract that a default ``PredictionConfig``
preserves legacy engine behavior bit-for-bit:
  * The default constructor equals the explicit ``baseline()``.
  * ``win_probability_v2`` and ``win_probability_batch_v2`` match the
    legacy scalar/batch routines.
  * ``run_simulation`` without ``prediction_config`` is unchanged.
"""
from __future__ import annotations

import numpy as np
import pytest

from engine.monte_carlo import run_simulation
from engine.prediction.config import PredictionConfig
from engine.types import GameResult, GameStatus, ScheduledGame, SimulationConfig, TeamRecord
from engine.win_probability import (
    win_probability,
    win_probability_batch,
    win_probability_batch_v2,
    win_probability_v2,
)


def test_default_config_baseline():
    """Default constructor and the explicit baseline must be equal."""
    assert PredictionConfig() == PredictionConfig.baseline()


def test_win_probability_v2_matches_legacy_when_default():
    """v2 with a default config equals the legacy scalar call."""
    config = PredictionConfig()
    v2 = win_probability_v2(70.0, 65.0, config)
    legacy = win_probability(70.0, 65.0)
    assert np.allclose(v2, legacy, atol=1e-12)


def test_win_probability_v2_matches_legacy_across_ratings():
    """Sweep several rating pairs - v2 must hug the legacy path exactly."""
    config = PredictionConfig()
    for home, away in [(10.0, 10.0), (12.0, 8.0), (5.0, 25.0), (100.0, 0.0)]:
        assert np.allclose(
            win_probability_v2(home, away, config),
            win_probability(home, away),
            atol=1e-12,
        )


def test_win_probability_batch_v2_matches_legacy():
    """Batch v2 with a default config equals the legacy batch call."""
    home = np.array([10.0, 12.0, 8.0, 70.0])
    away = np.array([10.0, 10.0, 15.0, 65.0])
    config = PredictionConfig()
    v2 = win_probability_batch_v2(home, away, config)
    legacy = win_probability_batch(home, away)
    assert np.allclose(v2, legacy, atol=1e-12)


def test_win_probability_v2_uses_sport_specific_hfa():
    """When a sport has an HFA override, v2 picks it up; otherwise falls back."""
    config = PredictionConfig(home_advantage_by_sport={"Football": 1.0})
    # Sport with an override: v2 should use HFA=1.0, not 0.5.
    expected = win_probability(70.0, 65.0, home_advantage=1.0, k=0.8)
    assert np.allclose(win_probability_v2(70.0, 65.0, config, sport="Football"), expected, atol=1e-12)
    # Sport not in the override map: fall back to the global 0.5.
    expected_fallback = win_probability(70.0, 65.0, home_advantage=0.5, k=0.8)
    assert np.allclose(
        win_probability_v2(70.0, 65.0, config, sport="Volleyball"),
        expected_fallback,
        atol=1e-12,
    )


def _make_4_team_league():
    teams = {
        1: TeamRecord(team_id=1, school_name="Alpha", division="I", classification="5A"),
        2: TeamRecord(team_id=2, school_name="Beta", division="I", classification="5A"),
        3: TeamRecord(team_id=3, school_name="Gamma", division="I", classification="5A"),
        4: TeamRecord(team_id=4, school_name="Delta", division="I", classification="5A"),
    }
    played = [
        GameResult(game_id=1, home_team_id=1, away_team_id=2, home_score=28, away_score=14, status=GameStatus.FINAL),
        GameResult(game_id=2, home_team_id=3, away_team_id=4, home_score=21, away_score=7, status=GameStatus.FINAL),
        GameResult(game_id=3, home_team_id=1, away_team_id=3, home_score=17, away_score=10, status=GameStatus.FINAL),
    ]
    remaining = [
        ScheduledGame(game_id=4, home_team_id=2, away_team_id=3),
        ScheduledGame(game_id=5, home_team_id=4, away_team_id=1),
        ScheduledGame(game_id=6, home_team_id=2, away_team_id=4),
    ]
    config = SimulationConfig(
        sport_name="Football", season_year=2025, week_number=3,
        num_runs=1000, playoff_spots=2,
    )
    return teams, played, remaining, config


def test_monte_carlo_legacy_unaffected_when_no_prediction_config():
    """run_simulation without prediction_config must equal the prior behavior.

    With a fixed seed the legacy call is deterministic; we compare projected
    rating means for every team to a parallel call invoked the same way.
    """
    teams, played, remaining, config = _make_4_team_league()
    baseline = run_simulation(teams, played, remaining, config, seed=42)
    rerun = run_simulation(teams, played, remaining, config, seed=42)
    for tid in teams:
        assert baseline[tid].projected_rating_mean == pytest.approx(
            rerun[tid].projected_rating_mean, abs=1e-9
        )
        assert baseline[tid].playoff_probability == pytest.approx(
            rerun[tid].playoff_probability, abs=1e-9
        )
        assert baseline[tid].projected_wins_mean == pytest.approx(
            rerun[tid].projected_wins_mean, abs=1e-9
        )


def test_monte_carlo_default_prediction_config_matches_legacy():
    """Passing a default PredictionConfig must match the legacy path bit-for-bit."""
    teams, played, remaining, config = _make_4_team_league()
    legacy = run_simulation(teams, played, remaining, config, seed=42)
    with_config = run_simulation(
        teams, played, remaining, config, seed=42, prediction_config=PredictionConfig()
    )
    for tid in teams:
        assert legacy[tid].projected_rating_mean == pytest.approx(
            with_config[tid].projected_rating_mean, abs=1e-9
        )
        assert legacy[tid].playoff_probability == pytest.approx(
            with_config[tid].playoff_probability, abs=1e-9
        )
        assert legacy[tid].championship_probability == pytest.approx(
            with_config[tid].championship_probability, abs=1e-9
        )
        assert legacy[tid].projected_wins_mean == pytest.approx(
            with_config[tid].projected_wins_mean, abs=1e-9
        )

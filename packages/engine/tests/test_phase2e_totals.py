"""Unit tests for the Phase-2e uncapped scoring-totals feature.

Coverage:
    - ``team_offense_defense`` returns ``(0.0, 0.0)`` for a team that
      didn't play any contributing game.
    - ``team_offense_defense`` does NOT cap blowouts (the explicit
      contract — uncapped totals are the whole point of this phase).
    - ``precompute_team_week_totals`` aggregates *through* the indexed
      week (lookup at ``(team, W)`` only sees games at weeks <= W).
    - ``predict_game`` with totals disabled equals the legacy
      ``win_probability_v2``.
    - ``predict_game`` with totals enabled but signals exactly zero
      collapses to the baseline.
    - ``predict_game`` raises the home win probability when the home
      team's offense exceeds the away team's defense (and vice versa).
    - ``_build_config_for_label('phase-2e')`` loads both
      ``margin_weight_by_sport`` and ``totals_weight_by_sport`` from
      ``fitted_params.json``.
    - The baseline label is unaffected when a Phase-2e fit step writes
      ``totals_weight_by_sport`` to ``fitted_params.json``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.prediction.config import PredictionConfig
from engine.prediction.features.totals import (
    precompute_team_week_totals,
    team_offense_defense,
)
from engine.validator import cli as validator_cli
from engine.validator.predictor import predict_game
from engine.win_probability import win_probability_v2


# ---------------------------------------------------------------------------
# Fixture: redirect FITTED_PARAMS_PATH at a temp file for the config tests.
# ---------------------------------------------------------------------------
@pytest.fixture
def patched_fitted_params(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Same pattern as test_phase2d_sos_depth: redirect the CLI's params
    reader at a writable temp file (``_load_fitted_params``'s default arg
    is captured at function-definition time)."""
    target = tmp_path / "fitted_params.json"
    monkeypatch.setattr(validator_cli, "FITTED_PARAMS_PATH", target)

    real_load = validator_cli._load_fitted_params

    def _load(path: Path = target) -> dict:
        return real_load(path)

    monkeypatch.setattr(validator_cli, "_load_fitted_params", _load)
    return target


# ---------------------------------------------------------------------------
# team_offense_defense
# ---------------------------------------------------------------------------
def test_team_offense_defense_no_games_returns_zero_zero():
    """No contributing games -> (0.0, 0.0) — cold-start safe."""
    # Empty input.
    assert team_offense_defense([], team_id=1) == (0.0, 0.0)
    # Games exist but team_id wasn't in any of them.
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 21, "away_score": 7,
         "_engine_week": 1},
    ]
    assert team_offense_defense(games, team_id=99) == (0.0, 0.0)
    # Games exist for the team but lack scores -> still cold-start.
    games_no_scores = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": None, "away_score": None,
         "_engine_week": 1},
    ]
    assert team_offense_defense(games_no_scores, team_id=1) == (0.0, 0.0)


def test_team_offense_defense_uncapped_blowout():
    """Uncapped behavior is the explicit contract: a 70-0 blowout
    contributes the full 70 to offensive_strength and 0 to
    defensive_weakness, regardless of any per-sport margin cap."""
    games = [
        # Team 1 scores 70, allows 0 — a complete blowout that capped
        # margin (Football cap = 35) would not see in full.
        {"home_team_id": 1, "away_team_id": 2, "home_score": 70, "away_score": 0,
         "_engine_week": 1},
        # Team 1 scores 50, allows 10 — another large game.
        {"home_team_id": 3, "away_team_id": 1, "home_score": 10, "away_score": 50,
         "_engine_week": 2},
    ]
    off, deff = team_offense_defense(games, team_id=1)
    # mean(70, 50) = 60.0; mean(0, 10) = 5.0 — uncapped.
    assert off == pytest.approx(60.0)
    assert deff == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# precompute_team_week_totals
# ---------------------------------------------------------------------------
def test_precompute_team_week_totals_through_week_inclusive():
    """Lookup at (team, W) covers games at weeks <= W (not future games)
    and densifies between played weeks."""
    games = [
        # Team 1 plays at weeks 1, 3 (skipping 2). Team 2 plays only at
        # week 1. Team 3 plays only at week 3.
        {"home_team_id": 1, "away_team_id": 2, "home_score": 30, "away_score": 10,
         "_engine_week": 1},
        {"home_team_id": 3, "away_team_id": 1, "home_score": 14, "away_score": 28,
         "_engine_week": 3},
    ]
    table = precompute_team_week_totals(games)

    # Team 1 at week 1: scored 30, allowed 10 (one game).
    assert table[(1, 1)] == (pytest.approx(30.0), pytest.approx(10.0))
    # Densified: week 2 carries the same running mean.
    assert table[(1, 2)] == (pytest.approx(30.0), pytest.approx(10.0))
    # Team 1 at week 3: scored (30 + 28)/2 = 29; allowed (10 + 14)/2 = 12.
    assert table[(1, 3)] == (pytest.approx(29.0), pytest.approx(12.0))

    # Team 2 only at week 1: scored 10, allowed 30 (away side).
    assert table[(2, 1)] == (pytest.approx(10.0), pytest.approx(30.0))
    # Densified forward: week 2 + 3 still report team 2's only game.
    assert table[(2, 2)] == (pytest.approx(10.0), pytest.approx(30.0))
    assert table[(2, 3)] == (pytest.approx(10.0), pytest.approx(30.0))

    # Team 3 only at week 3 (no earlier weeks emit an entry for team 3).
    assert (3, 1) not in table
    assert (3, 2) not in table
    assert table[(3, 3)] == (pytest.approx(14.0), pytest.approx(28.0))


# ---------------------------------------------------------------------------
# predict_game wiring
# ---------------------------------------------------------------------------
def test_predict_game_totals_disabled_matches_baseline():
    """With 'totals' NOT in enabled_features, all four off/def args
    must be ignored — even when populated with large values."""
    cfg = PredictionConfig()  # nothing enabled
    direct = win_probability_v2(70.0, 65.0, cfg, sport="Football")
    via = predict_game(
        70.0, 65.0, "Football", cfg,
        home_off=50.0, home_def=10.0,
        away_off=20.0, away_def=40.0,
    )
    assert via == pytest.approx(direct, abs=1e-12)


def test_predict_game_totals_enabled_zero_signal_matches_baseline():
    """With 'totals' enabled but every off/def value exactly 0.0, the
    home_signal and away_signal are both 0.0 and the call collapses
    to the legacy win_probability_v2 result."""
    cfg = PredictionConfig(
        enabled_features=["totals"],
        totals_weight_by_sport={"Football": 0.1},
    )
    direct = win_probability_v2(70.0, 65.0, cfg, sport="Football")
    via = predict_game(
        70.0, 65.0, "Football", cfg,
        home_off=0.0, home_def=0.0,
        away_off=0.0, away_def=0.0,
    )
    assert via == pytest.approx(direct, abs=1e-12)


def test_predict_game_totals_favors_better_offense_against_worse_defense():
    """A matchup where the home team has a much better offense than
    the away team's defense (and the away team's offense is roughly
    equal to the home team's defense) should raise P(home_win) above
    the baseline; reversing the asymmetry should drop it below.
    """
    cfg = PredictionConfig(
        enabled_features=["totals"],
        totals_weight_by_sport={"Football": 0.1},
    )
    baseline = predict_game(70.0, 70.0, "Football", cfg)

    # Home offense >> away defense; away offense ~ home defense.
    home_strong = predict_game(
        70.0, 70.0, "Football", cfg,
        home_off=45.0, home_def=20.0,
        away_off=20.0, away_def=15.0,
    )
    # Home: 45 - 15 = +30. Away: 20 - 20 = 0. tw=0.1 ->
    # home_eff = 70 + 3.0 = 73; away_eff unchanged.
    assert home_strong > baseline

    # Mirror: away dominates the matchup totals.
    away_strong = predict_game(
        70.0, 70.0, "Football", cfg,
        home_off=20.0, home_def=20.0,
        away_off=45.0, away_def=15.0,
    )
    assert away_strong < baseline

    # And the relationship is monotonic: a larger offense-defense gap
    # produces a larger swing.
    p_combined = predict_game(
        70.0, 70.0, "Football", cfg,
        home_off=45.0, home_def=20.0,
        away_off=20.0, away_def=15.0,
    )
    # Hand-build expected effective ratings.
    plain = PredictionConfig()
    home_eff = 70.0 + 0.1 * (45.0 - 15.0)  # = 73.0
    away_eff = 70.0 + 0.1 * (20.0 - 20.0)  # = 70.0
    p_expected = win_probability_v2(home_eff, away_eff, plain, sport="Football")
    assert p_combined == pytest.approx(p_expected, abs=1e-12)


# ---------------------------------------------------------------------------
# _build_config_for_label('phase-2e')
# ---------------------------------------------------------------------------
def test_phase2e_config_loads_both_margin_and_totals_weights(
    patched_fitted_params: Path,
):
    """phase-2e reads both margin_weight_by_sport and
    totals_weight_by_sport from fitted_params.json."""
    patched_fitted_params.write_text(
        json.dumps(
            {
                "margin_weight_by_sport": {
                    "Football": 0.5,
                    "Boys Basketball": 1.0,
                },
                "totals_weight_by_sport": {
                    "Football": 0.1,
                    "Boys Basketball": 0.2,
                    "Baseball": 0.05,
                },
            }
        )
    )

    cfg = validator_cli._build_config_for_label("phase-2e")

    assert "margin" in cfg.enabled_features
    assert "totals" in cfg.enabled_features
    # recent_form was rejected in Phase 2b — must NOT be in phase-2e.
    assert "recent_form" not in cfg.enabled_features
    # sos_depth is its own separate experiment; not enabled here.
    assert "sos_depth" not in cfg.enabled_features
    assert cfg.margin_weight_by_sport == {
        "Football": 0.5,
        "Boys Basketball": 1.0,
    }
    assert cfg.totals_weight_by_sport == {
        "Football": 0.1,
        "Boys Basketball": 0.2,
        "Baseball": 0.05,
    }


def test_baseline_unaffected_by_totals_fit(patched_fitted_params: Path):
    """baseline must remain a default-everything config even after the
    Phase-2e fit step has populated fitted_params.json with
    totals_weight_by_sport. Mirrors test_phase2d_sos_depth's regression
    guard for sos_depth."""
    patched_fitted_params.write_text(
        json.dumps(
            {
                "margin_weight_by_sport": {"Football": 0.5},
                "totals_weight_by_sport": {"Football": 0.1},
            }
        )
    )

    cfg = validator_cli._build_config_for_label("baseline")

    assert cfg.totals_weight_by_sport == {}
    assert cfg.totals_weight == 0.0
    assert cfg.margin_weight_by_sport == {}
    assert cfg.enabled_features == []

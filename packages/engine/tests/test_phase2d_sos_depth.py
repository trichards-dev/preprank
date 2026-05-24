"""Unit tests for the Phase-2d depth-2 SOS adjustment feature.

Coverage:
    - ``team_opponents_through_week`` returns the empty set for a team
      that didn't play; week filter is inclusive.
    - ``precompute_depth_sos_signal`` returns 0.0 when a team has no
      opponents through the indexed week.
    - ``precompute_depth_sos_signal`` returns a positive signal when
      opponents-of-opponents are explicitly stronger than opponents.
    - ``precompute_depth_sos_signal`` excludes the team itself from the
      opponents-of-opponents set.
    - ``predict_game`` with sos_depth disabled equals the legacy
      ``win_probability_v2``.
    - ``predict_game`` with sos_depth enabled but both signals 0.0
      equals the baseline.
    - ``predict_game`` composes margin + sos_depth additively.
    - ``_build_config_for_label('phase-2d')`` loads both
      ``margin_weight_by_sport`` and ``sos_depth_weight_by_sport`` from
      ``fitted_params.json``.
    - The baseline label is unaffected when a Phase-2d fit step writes
      ``sos_depth_weight_by_sport`` to ``fitted_params.json``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.prediction.config import PredictionConfig
from engine.prediction.features.sos_depth import (
    precompute_depth_sos_signal,
    team_opponents_through_week,
)
from engine.validator import cli as validator_cli
from engine.validator.predictor import predict_game
from engine.win_probability import win_probability_v2


# ---------------------------------------------------------------------------
# Fixture: redirect FITTED_PARAMS_PATH at a temp file for the config tests.
# ---------------------------------------------------------------------------
@pytest.fixture
def patched_fitted_params(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Same pattern as test_phase2c_hfa: redirect the CLI's params reader at
    a writable temp file (since ``_load_fitted_params``'s default arg is
    captured at function definition time)."""
    target = tmp_path / "fitted_params.json"
    monkeypatch.setattr(validator_cli, "FITTED_PARAMS_PATH", target)

    real_load = validator_cli._load_fitted_params

    def _load(path: Path = target) -> dict:
        return real_load(path)

    monkeypatch.setattr(validator_cli, "_load_fitted_params", _load)
    return target


# ---------------------------------------------------------------------------
# team_opponents_through_week
# ---------------------------------------------------------------------------
def test_team_opponents_through_week_no_games():
    """A team that didn't play any games has no opponents."""
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 21, "away_score": 7,
         "_engine_week": 1},
    ]
    # Team 99 didn't play in any of these games.
    assert team_opponents_through_week(games, team_id=99, through_week=5) == set()
    # And an empty games list returns empty.
    assert team_opponents_through_week([], team_id=1, through_week=5) == set()


def test_team_opponents_through_week_inclusive():
    """A game at week 2 must appear in the set when through_week=2."""
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 21, "away_score": 7,
         "_engine_week": 1},
        {"home_team_id": 1, "away_team_id": 3, "home_score": 14, "away_score": 21,
         "_engine_week": 2},
        {"home_team_id": 1, "away_team_id": 4, "home_score": 7, "away_score": 0,
         "_engine_week": 3},
    ]
    # Through week 1: only team 2 is an opponent.
    assert team_opponents_through_week(games, team_id=1, through_week=1) == {2}
    # Through week 2: teams 2 and 3 are opponents (inclusive).
    assert team_opponents_through_week(games, team_id=1, through_week=2) == {2, 3}
    # Through week 3: all three.
    assert team_opponents_through_week(games, team_id=1, through_week=3) == {2, 3, 4}


def test_team_opponents_through_week_skips_missing_scores_and_out_of_state():
    """Unscored games and out-of-state games shouldn't count as opponents."""
    games = [
        # Unscored — skip.
        {"home_team_id": 1, "away_team_id": 2, "home_score": None, "away_score": None,
         "_engine_week": 1},
        # Out-of-state — skip.
        {"home_team_id": 1, "away_team_id": 3, "home_score": 7, "away_score": 0,
         "_engine_week": 2, "is_out_of_state": True},
        # Valid.
        {"home_team_id": 1, "away_team_id": 4, "home_score": 7, "away_score": 0,
         "_engine_week": 3},
    ]
    assert team_opponents_through_week(games, team_id=1, through_week=5) == {4}


# ---------------------------------------------------------------------------
# precompute_depth_sos_signal
# ---------------------------------------------------------------------------
def test_precompute_depth_sos_signal_returns_zero_for_no_opponents():
    """A team that's never played has no entry (or 0.0 at most) — and even
    a team that 'plays' only in a game with no scores should not get an
    entry at all (no usable contribution).
    """
    cfg = PredictionConfig()
    # No games at all -> empty table.
    assert precompute_depth_sos_signal([], {}, "Football", cfg) == {}

    # A single scored game with no rating data anywhere -> signal at
    # week 1 should still emit 0.0 (depth1 and depth2 both collapse to
    # the no-rating fallback of 0.0).
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 21, "away_score": 7,
         "_engine_week": 1},
    ]
    table = precompute_depth_sos_signal(games, {}, "Football", cfg)
    # Both team 1 and team 2 played; but neither has *opponents* of
    # opponents (each other's only opponent is the other side), so the
    # OO set excluding T itself is empty -> depth2 collapses to 0.0,
    # and depth1 has no rating data so it's also 0.0. Signal = 0.0.
    assert table.get((1, 1)) == pytest.approx(0.0)
    assert table.get((2, 1)) == pytest.approx(0.0)


def test_precompute_depth_sos_signal_positive_when_oo_stronger():
    """When T's opponents have played a strong set of opponents (the
    OO set), the depth-2 - depth-1 SOS signal for T must be positive.

    The signal is recomputed at each week T plays a game (the cadence
    a runner cares about — predict_game looks the signal up at W-1).
    To exercise the "OO stronger than O" case we need T to play twice
    with A picking up a strong opponent (B) in between.
    """
    cfg = PredictionConfig()
    # Teams 1 (T), 2 (A), 3 (B), 4 (D, a second weak opponent for T).
    games = [
        # Week 1: T plays A. (T's OO at end of week 1 is empty — A's
        # only opponent so far is T.)
        {"home_team_id": 1, "away_team_id": 2, "home_score": 14, "away_score": 7,
         "_engine_week": 1},
        # Week 2: A plays B (T is idle).
        {"home_team_id": 2, "away_team_id": 3, "home_score": 14, "away_score": 21,
         "_engine_week": 2},
        # Week 3: T plays D (a fresh weak opponent). At this point
        # T's opponents = {A, D}; A's opponents (through W=3) = {T, B};
        # D's opponents = {T}. Excluding T from the OO set leaves {B}.
        {"home_team_id": 1, "away_team_id": 4, "home_score": 21, "away_score": 7,
         "_engine_week": 3},
    ]
    # Ratings: A and D are weak (50), B is strong (80). Use the same
    # rating across all observed weeks for simplicity.
    ratings: dict[tuple[int, int], float] = {}
    for w in range(1, 4):
        ratings[(1, w)] = 60.0  # T (irrelevant — T isn't in any mean)
        ratings[(2, w)] = 50.0  # A (weak)
        ratings[(3, w)] = 80.0  # B (strong)
        ratings[(4, w)] = 50.0  # D (weak)
    table = precompute_depth_sos_signal(games, ratings, "Football", cfg)
    # At week 1 T's OO is empty (A's only opponent so far is T).
    # depth2 collapses to 0.0; depth1 = rating(A) = 50; signal = -50.
    assert table.get((1, 1)) == pytest.approx(-50.0)
    # At week 3 T plays again. opponents(T) = {A, D}; OO = {B}.
    # depth1 = mean(rating(A), rating(D)) = mean(50, 50) = 50.
    # depth2 = mean(rating(B)) = 80. Signal = 80 - 50 = +30 — the
    # central "OO stronger than O" case.
    assert table.get((1, 3)) == pytest.approx(30.0)


def test_precompute_depth_sos_signal_excludes_self():
    """When T's opponent has T as one of their opponents, T should not
    appear in T's own opponents-of-opponents set."""
    cfg = PredictionConfig()
    # Just T (1) vs A (2). A's only opponent is T -> after excluding T,
    # the OO set is empty.
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 14, "away_score": 7,
         "_engine_week": 1},
    ]
    # Ratings exist for both teams.
    ratings = {(1, 1): 60.0, (2, 1): 50.0}
    table = precompute_depth_sos_signal(games, ratings, "Football", cfg)
    # T at week 1: opponents = {A}, OO = {} (A's only opponent is T).
    # depth1 = rating(A) = 50. depth2 collapses to 0 (no OO). Signal =
    # 0 - 50 = -50.
    # The point of this test: T's OO set excludes T itself — were it
    # included, depth2 would equal rating(T) = 60 and signal would be 10.
    assert table.get((1, 1)) == pytest.approx(-50.0)
    # And from A's perspective the symmetric case holds.
    assert table.get((2, 1)) == pytest.approx(-60.0)


def test_precompute_depth_sos_signal_handles_missing_opponent_ratings():
    """Opponents with no rating at any week <= W should be dropped from
    the mean rather than crashing or being substituted with 0.0 inside
    the average."""
    cfg = PredictionConfig()
    # T (1) plays A (2) and B (3). A has a rating, B does not.
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 14, "away_score": 7,
         "_engine_week": 1},
        {"home_team_id": 1, "away_team_id": 3, "home_score": 14, "away_score": 7,
         "_engine_week": 2},
    ]
    # Only rating(A) is populated. B is "cold start" — no rating at any week.
    ratings = {(2, 1): 50.0, (2, 2): 50.0}
    table = precompute_depth_sos_signal(games, ratings, "Football", cfg)
    # At week 2, T has opponents {A, B}. depth1 should be the mean of
    # A only (B dropped) -> 50.0. OO excluding T is empty -> depth2
    # falls back to 0.0. Signal = 0 - 50 = -50.
    assert table.get((1, 2)) == pytest.approx(-50.0)


# ---------------------------------------------------------------------------
# predict_game wiring
# ---------------------------------------------------------------------------
def test_predict_game_sos_disabled_matches_baseline():
    """With 'sos_depth' NOT in enabled_features, the signals must be ignored."""
    cfg = PredictionConfig()  # nothing enabled
    direct = win_probability_v2(70.0, 65.0, cfg, sport="Football")
    via = predict_game(
        70.0, 65.0, "Football", cfg,
        home_sos_depth_signal=10.0,
        away_sos_depth_signal=-5.0,
    )
    assert via == pytest.approx(direct, abs=1e-12)


def test_predict_game_sos_enabled_zero_signal_matches_baseline():
    """With 'sos_depth' enabled but both signals exactly 0.0, the call
    must collapse to the legacy win_probability_v2 result."""
    cfg = PredictionConfig(
        enabled_features=["sos_depth"],
        sos_depth_weight_by_sport={"Football": 1.5},
    )
    direct = win_probability_v2(70.0, 65.0, cfg, sport="Football")
    via = predict_game(
        70.0, 65.0, "Football", cfg,
        home_sos_depth_signal=0.0, away_sos_depth_signal=0.0,
    )
    assert via == pytest.approx(direct, abs=1e-12)


def test_predict_game_sos_enabled_signal_shifts_probability():
    """A positive home SOS signal should raise P(home_win); negative drops it."""
    cfg = PredictionConfig(
        enabled_features=["sos_depth"],
        sos_depth_weight_by_sport={"Football": 1.0},
    )
    baseline = predict_game(70.0, 70.0, "Football", cfg)
    boosted = predict_game(
        70.0, 70.0, "Football", cfg,
        home_sos_depth_signal=5.0,
    )
    suppressed = predict_game(
        70.0, 70.0, "Football", cfg,
        home_sos_depth_signal=-5.0,
    )
    assert boosted > baseline > suppressed


def test_predict_game_margin_plus_sos_additive():
    """When both margin and sos_depth are enabled the contributions
    must compose additively: shifting home_eff by margin_weight*margin
    plus sos_weight*sos.
    """
    cfg = PredictionConfig(
        enabled_features=["margin", "sos_depth"],
        margin_weight_by_sport={"Football": 1.0},
        sos_depth_weight_by_sport={"Football": 1.0},
    )
    # Compute what predict_game does:
    p_combined = predict_game(
        70.0, 70.0, "Football", cfg,
        home_margin_signal=4.0,
        away_margin_signal=-1.0,
        home_sos_depth_signal=2.0,
        away_sos_depth_signal=-3.0,
    )
    # Equivalent: hand-build effective ratings and feed them straight
    # to win_probability_v2 via a config that has neither feature
    # enabled (so the predictor doesn't double-apply weights).
    plain = PredictionConfig()
    home_eff = 70.0 + 1.0 * 4.0 + 1.0 * 2.0   # = 76.0
    away_eff = 70.0 + 1.0 * -1.0 + 1.0 * -3.0  # = 66.0
    p_expected = win_probability_v2(home_eff, away_eff, plain, sport="Football")
    assert p_combined == pytest.approx(p_expected, abs=1e-12)


# ---------------------------------------------------------------------------
# _build_config_for_label('phase-2d')
# ---------------------------------------------------------------------------
def test_phase2d_config_loads_both_margin_and_sos_weights(
    patched_fitted_params: Path,
):
    """phase-2d reads both margin_weight_by_sport and
    sos_depth_weight_by_sport from fitted_params.json."""
    patched_fitted_params.write_text(
        json.dumps(
            {
                "margin_weight_by_sport": {
                    "Football": 0.5,
                    "Boys Basketball": 1.0,
                },
                "sos_depth_weight_by_sport": {
                    "Football": 1.5,
                    "Boys Basketball": 2.0,
                    "Baseball": 0.5,
                },
            }
        )
    )

    cfg = validator_cli._build_config_for_label("phase-2d")

    assert "margin" in cfg.enabled_features
    assert "sos_depth" in cfg.enabled_features
    # recent_form was rejected in Phase 2b — must NOT be in phase-2d.
    assert "recent_form" not in cfg.enabled_features
    assert cfg.margin_weight_by_sport == {
        "Football": 0.5,
        "Boys Basketball": 1.0,
    }
    assert cfg.sos_depth_weight_by_sport == {
        "Football": 1.5,
        "Boys Basketball": 2.0,
        "Baseball": 0.5,
    }


def test_baseline_unaffected_by_sos_fit(patched_fitted_params: Path):
    """baseline must remain a default-everything config even after the
    Phase-2d fit step has populated fitted_params.json with
    sos_depth_weight_by_sport. Mirrors test_phase2c_hfa's regression
    guard for HFA."""
    patched_fitted_params.write_text(
        json.dumps(
            {
                "margin_weight_by_sport": {"Football": 0.5},
                "sos_depth_weight_by_sport": {"Football": 1.5},
            }
        )
    )

    cfg = validator_cli._build_config_for_label("baseline")

    assert cfg.sos_depth_weight_by_sport == {}
    assert cfg.sos_depth_weight == 0.0
    assert cfg.margin_weight_by_sport == {}
    assert cfg.enabled_features == []


def test_phase2a_unaffected_by_sos_fit(patched_fitted_params: Path):
    """Phase-2a runs must keep sos_depth_weight_by_sport={} even after
    Phase-2d writes per-sport entries to fitted_params.json. Otherwise
    re-running the phase-2a validator after Phase 2d would silently
    change its baseline-comparable numbers."""
    patched_fitted_params.write_text(
        json.dumps(
            {
                "margin_weight_by_sport": {"Football": 0.5},
                "sos_depth_weight_by_sport": {"Football": 1.5},
            }
        )
    )

    cfg = validator_cli._build_config_for_label("phase-2a")

    assert cfg.sos_depth_weight_by_sport == {}
    assert cfg.sos_depth_weight == 0.0
    # And margin weights should still load from the file.
    assert cfg.margin_weight_by_sport == {"Football": 0.5}

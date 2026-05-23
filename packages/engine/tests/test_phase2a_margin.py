"""Unit + integration tests for the Phase-2a score-margin feature.

Coverage:
    - ``capped_margin`` clips to the per-sport cap in both directions.
    - ``team_margin_signal`` returns 0.0 for an empty input.
    - ``team_margin_signal`` sign tracks who won (home perspective vs away).
    - ``predict_game`` with margin disabled equals ``win_probability_v2``.
    - ``predict_game`` with margin enabled but both signals 0.0 still
      equals the baseline.
    - ``precompute_team_week_margins`` aggregates *through* the indexed
      week inclusive (not the next week's game).
    - Integration: a runner pass with ``enabled_features=['margin']``
      produces holdout probabilities that differ from a baseline pass on
      the same fixture.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from engine.prediction.config import PredictionConfig
from engine.prediction.features.margin import (
    capped_margin,
    precompute_team_week_margins,
    team_margin_signal,
)
from engine.validator.predictor import predict_game
from engine.validator.runner import run_validation
from engine.win_probability import win_probability_v2

# Re-use the fake Supabase client + fixture builder from the validator tests.
from tests.test_validator import _build_fake_db, _FakeSupabase


# ---------------------------------------------------------------------------
# capped_margin
# ---------------------------------------------------------------------------
def test_capped_margin_clips_to_sport_cap():
    cfg = PredictionConfig()
    # Football: cap=35. A 50-0 blowout clips to +35.
    assert capped_margin(50, 0, "Football", cfg) == 35
    assert capped_margin(0, 50, "Football", cfg) == -35
    # Inside the cap is untouched.
    assert capped_margin(28, 14, "Football", cfg) == 14
    # Baseball: cap=15. 12-0 clips to +15? No, 12 is below 15 -> stays at +12.
    # A 22-0 game clips to +15.
    assert capped_margin(22, 0, "Baseball", cfg) == 15
    assert capped_margin(12, 0, "Baseball", cfg) == 12
    # Soccer: cap=5. A 10-0 game clips to +5.
    assert capped_margin(10, 0, "Boys Soccer", cfg) == 5
    # Volleyball: cap=3. A sweep 3-0 clips to +3; 3-2 stays at +1.
    assert capped_margin(3, 0, "Volleyball", cfg) == 3
    assert capped_margin(3, 2, "Volleyball", cfg) == 1


def test_capped_margin_unknown_sport_falls_back_to_max_cap():
    cfg = PredictionConfig()
    # 'Lacrosse' isn't in the map; fallback uses the maximum cap (35).
    assert capped_margin(50, 0, "Lacrosse", cfg) == 35
    assert capped_margin(20, 0, "Lacrosse", cfg) == 20


# ---------------------------------------------------------------------------
# team_margin_signal
# ---------------------------------------------------------------------------
def test_team_margin_signal_zero_when_no_games():
    cfg = PredictionConfig()
    assert team_margin_signal([], team_id=1, sport="Football", config=cfg) == 0.0
    # Team not in any of the games -> still 0.0
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 28, "away_score": 14},
    ]
    assert team_margin_signal(games, team_id=99, sport="Football", config=cfg) == 0.0


def test_team_margin_signal_sign():
    cfg = PredictionConfig()
    # Team 1 wins big at home, team 1 also loses big on the road.
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 49, "away_score": 7},   # +35 (capped)
        {"home_team_id": 3, "away_team_id": 1, "home_score": 56, "away_score": 14},  # -35 (capped, team1 lost)
    ]
    # Mean across team 1's two games: (35 + -35) / 2 = 0
    assert team_margin_signal(games, team_id=1, sport="Football", config=cfg) == 0.0

    # Team that won big -> positive signal
    games2 = [
        {"home_team_id": 5, "away_team_id": 6, "home_score": 28, "away_score": 0},
    ]
    assert team_margin_signal(games2, team_id=5, sport="Football", config=cfg) > 0
    # Same game from team 6's perspective: negative
    assert team_margin_signal(games2, team_id=6, sport="Football", config=cfg) < 0


# ---------------------------------------------------------------------------
# predict_game wiring
# ---------------------------------------------------------------------------
def test_predict_game_margin_disabled_matches_baseline():
    cfg = PredictionConfig()  # 'margin' NOT in enabled_features
    direct = win_probability_v2(70.0, 65.0, cfg, sport="Football")
    via = predict_game(
        70.0, 65.0, "Football", cfg,
        home_margin_signal=10.0, away_margin_signal=-5.0,
    )
    # Signals are ignored when feature is off.
    assert via == pytest.approx(direct, abs=1e-12)


def test_predict_game_margin_enabled_zero_signal_matches_baseline():
    cfg = PredictionConfig(
        enabled_features=["margin"],
        margin_weight_by_sport={"Football": 1.5},
    )
    direct = win_probability_v2(70.0, 65.0, cfg, sport="Football")
    via = predict_game(
        70.0, 65.0, "Football", cfg,
        home_margin_signal=0.0, away_margin_signal=0.0,
    )
    assert via == pytest.approx(direct, abs=1e-12)


def test_predict_game_margin_enabled_signal_shifts_probability():
    """With a positive home signal, P(home_win) goes up; negative -> down."""
    cfg = PredictionConfig(
        enabled_features=["margin"],
        margin_weight_by_sport={"Football": 1.0},
    )
    baseline = predict_game(70.0, 70.0, "Football", cfg)  # both signals default to 0
    boosted = predict_game(
        70.0, 70.0, "Football", cfg,
        home_margin_signal=5.0, away_margin_signal=0.0,
    )
    suppressed = predict_game(
        70.0, 70.0, "Football", cfg,
        home_margin_signal=-5.0, away_margin_signal=0.0,
    )
    assert boosted > baseline > suppressed


# ---------------------------------------------------------------------------
# precompute_team_week_margins
# ---------------------------------------------------------------------------
def test_precompute_team_week_margins_through_week_inclusive():
    """Lookup at (team, W) covers games at weeks <= W (not future games)."""
    cfg = PredictionConfig()
    # Team 1 plays games at weeks 1, 2, 3 — all wins by +14 (well below cap).
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 21, "away_score": 7,
         "_engine_week": 1},
        {"home_team_id": 1, "away_team_id": 3, "home_score": 21, "away_score": 7,
         "_engine_week": 2},
        {"home_team_id": 1, "away_team_id": 4, "home_score": 21, "away_score": 7,
         "_engine_week": 3},
    ]
    table = precompute_team_week_margins(games, "Football", cfg)
    # At week 1: only game-1 counts. Mean = +14.
    assert table[(1, 1)] == pytest.approx(14.0)
    # At week 2: games 1 + 2 count, week 3 does NOT. Mean = +14.
    assert table[(1, 2)] == pytest.approx(14.0)
    # At week 3: all three count. Mean = +14.
    assert table[(1, 3)] == pytest.approx(14.0)
    # Opponent teams are also indexed -- team 2 plays only at week 1.
    assert table[(2, 1)] == pytest.approx(-14.0)
    # Team 2 should keep that signal at later week indices (no later games).
    assert table[(2, 2)] == pytest.approx(-14.0)
    assert table[(2, 3)] == pytest.approx(-14.0)


def test_precompute_team_week_margins_empty():
    cfg = PredictionConfig()
    assert precompute_team_week_margins([], "Football", cfg) == {}


def test_precompute_team_week_margins_skips_missing_scores():
    cfg = PredictionConfig()
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": None, "away_score": None,
         "_engine_week": 1},
        {"home_team_id": 1, "away_team_id": 2, "home_score": 28, "away_score": 14,
         "_engine_week": 2},
    ]
    table = precompute_team_week_margins(games, "Football", cfg)
    # Week 1 had no scored games -> team 1 entry only appears starting week 2.
    assert (1, 1) not in table
    assert table[(1, 2)] == pytest.approx(14.0)


# ---------------------------------------------------------------------------
# Integration: runner with margin enabled vs baseline on the same fixture
# ---------------------------------------------------------------------------
def test_runner_margin_enabled_differs_from_baseline(tmp_path: Path):
    """A margin-enabled run on a fixture must produce holdout numbers that
    are not bit-for-bit identical to a baseline run on the same fixture.

    The fixture has 4 Football games across weeks 1-4 with non-trivial
    score deltas, so any per-team margin signal != 0 at W-1 will shift
    the home-win probability at week W.
    """
    # --- baseline pass ---
    db_baseline = _build_fake_db()
    sb_b = _FakeSupabase(db_baseline)
    baseline_cfg = PredictionConfig.baseline()
    baseline_result = run_validation(
        config=baseline_cfg,
        config_label="baseline-margin-test",
        sports=["Football"],
        seasons=[2025],
        holdout_seasons=[2025],
        write_to_db=False,
        output_dir=tmp_path / "baseline",
        n_bootstrap=0,
        supabase_client=sb_b,
        now_fn=lambda: datetime(2026, 1, 1, 12, 0, 0),
    )
    baseline_block = baseline_result.sports["Football"]["holdout"]

    # --- margin-enabled pass on a fresh copy of the same fixture ---
    db_margin = _build_fake_db()
    sb_m = _FakeSupabase(db_margin)
    margin_cfg = PredictionConfig(
        enabled_features=["margin"],
        margin_weight_by_sport={"Football": 1.5},
    )
    margin_result = run_validation(
        config=margin_cfg,
        config_label="phase-2a-margin-test",
        sports=["Football"],
        seasons=[2025],
        holdout_seasons=[2025],
        write_to_db=False,
        output_dir=tmp_path / "phase2a",
        n_bootstrap=0,
        supabase_client=sb_m,
        now_fn=lambda: datetime(2026, 1, 1, 12, 0, 0),
    )
    margin_block = margin_result.sports["Football"]["holdout"]

    # Same number of games either way
    assert baseline_block["n_games"] == margin_block["n_games"] == 4

    # Brier or accuracy should differ — margin shifts at least one prediction.
    differs = (
        baseline_block["brier"] != margin_block["brier"]
        or baseline_block["game_winner_acc"] != margin_block["game_winner_acc"]
    )
    assert differs, (
        "Margin-enabled run produced identical metrics to baseline; "
        "signals must be flowing into predict_game."
    )

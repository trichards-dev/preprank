"""Unit + integration tests for the Phase-2b recent-form feature.

Coverage:
    - ``game_recency_weight`` plateau at 1.5 inside the window, decay
      linearly to 1.0 at game 8, flat 1.0 beyond.
    - ``team_form_signal`` is 0.0 with no games; a team whose recent
      game is a blowout win outweighs older average losses.
    - ``precompute_team_week_form`` uses through-week-inclusive
      indexing matching the margin module.
    - ``predict_game`` is bit-for-bit identical to the baseline when the
      ``recent_form`` feature is disabled.
    - ``predict_game`` collapses to the Phase-2a result when the feature
      is on but the form signals are exactly 0.0.
    - When both margin + recent_form are enabled, each signal adds its
      ``weight * signal`` term to the effective rating (additive
      composition).
"""
from __future__ import annotations

import pytest

from engine.prediction.config import PredictionConfig
from engine.prediction.features.recent_form import (
    game_recency_weight,
    precompute_team_week_form,
    team_form_signal,
)
from engine.validator.predictor import predict_game
from engine.win_probability import win_probability_v2


# ---------------------------------------------------------------------------
# game_recency_weight
# ---------------------------------------------------------------------------
def test_game_recency_weight_window():
    """Games 0..2 (window=3) get the peak weight; game 8 hits the floor."""
    # Plateau region.
    assert game_recency_weight(0) == pytest.approx(1.5)
    assert game_recency_weight(1) == pytest.approx(1.5)
    assert game_recency_weight(2) == pytest.approx(1.5)
    # Floor region (games_back >= floor_at).
    assert game_recency_weight(8) == pytest.approx(1.0)
    assert game_recency_weight(20) == pytest.approx(1.0)
    # Middle of the decay (games_back=5 with window=3, floor_at=8).
    # Linear from (3, 1.5) to (8, 1.0): at games_back=5, progress=2/5,
    # weight = 1.5 + (1.0 - 1.5) * 0.4 = 1.3.
    assert game_recency_weight(5) == pytest.approx(1.3)
    # And the spec example: games_back=5 is "somewhere in between (~1.2)".
    # Our 1.3 satisfies "somewhere in between"; the test asserts strict bounds.
    assert 1.0 < game_recency_weight(5) < 1.5


def test_game_recency_weight_decay_linear():
    """Decay is linear between (window, peak) and (floor_at, 1.0)."""
    # Hand-computed values for window=3, peak=1.5, floor_at=8 (defaults):
    #   games_back=3 -> at the boundary, still peak (per spec)? Actually
    #   the helper treats games_back<window as plateau and games_back>=window
    #   as decay start, so games_back=3 is the first decay point.
    # At games_back=3, progress=0 -> weight=1.5.
    # At games_back=4, progress=1/5 -> 1.5 + (-0.5)*0.2 = 1.4
    # At games_back=5, progress=2/5 -> 1.3
    # At games_back=6, progress=3/5 -> 1.2
    # At games_back=7, progress=4/5 -> 1.1
    # At games_back=8, floor -> 1.0
    assert game_recency_weight(3) == pytest.approx(1.5)
    assert game_recency_weight(4) == pytest.approx(1.4)
    assert game_recency_weight(5) == pytest.approx(1.3)
    assert game_recency_weight(6) == pytest.approx(1.2)
    assert game_recency_weight(7) == pytest.approx(1.1)
    assert game_recency_weight(8) == pytest.approx(1.0)
    # Step size is constant -> proves linearity.
    diffs = [
        game_recency_weight(k) - game_recency_weight(k + 1) for k in (3, 4, 5, 6)
    ]
    assert all(d == pytest.approx(0.1) for d in diffs)


def test_game_recency_weight_negative_games_back_is_safe():
    """Defensive: negative values should not blow up; return 1.0."""
    assert game_recency_weight(-1) == pytest.approx(1.0)
    assert game_recency_weight(-5) == pytest.approx(1.0)


def test_game_recency_weight_custom_window():
    """Custom window/peak/floor_at parameters are honored."""
    # window=2, peak=2.0, floor_at=6
    assert game_recency_weight(0, window=2, peak=2.0, floor_at=6) == pytest.approx(2.0)
    assert game_recency_weight(1, window=2, peak=2.0, floor_at=6) == pytest.approx(2.0)
    # games_back=2 is first decay point; progress=0 -> peak
    assert game_recency_weight(2, window=2, peak=2.0, floor_at=6) == pytest.approx(2.0)
    # games_back=4 with span=4 -> progress=2/4 -> 2.0 + (-1.0)*0.5 = 1.5
    assert game_recency_weight(4, window=2, peak=2.0, floor_at=6) == pytest.approx(1.5)
    assert game_recency_weight(6, window=2, peak=2.0, floor_at=6) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# team_form_signal
# ---------------------------------------------------------------------------
def test_team_form_signal_zero_when_no_games():
    cfg = PredictionConfig()
    assert team_form_signal([], team_id=1, sport="Football", config=cfg) == 0.0
    # Team not in any game.
    games = [
        {"home_team_id": 2, "away_team_id": 3, "home_score": 28, "away_score": 14,
         "_engine_week": 1},
    ]
    assert team_form_signal(games, team_id=99, sport="Football", config=cfg) == 0.0
    # All games missing scores.
    games2 = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": None, "away_score": None,
         "_engine_week": 1},
    ]
    assert team_form_signal(games2, team_id=1, sport="Football", config=cfg) == 0.0


def test_team_form_signal_recent_dominates_old():
    """A team with one blowout win 1 game ago and 5 average losses long-ago
    has POSITIVE form (recent weighted heavier)."""
    cfg = PredictionConfig()
    # Football cap=35. Older losses are -7 each (well below cap), most recent
    # game is a +35 blowout win. There are 6 games total; team 1 played all.
    games = [
        {"home_team_id": 2, "away_team_id": 1, "home_score": 21, "away_score": 14,
         "_engine_week": 1},  # team 1 lost by 7 -> signed = -7
        {"home_team_id": 2, "away_team_id": 1, "home_score": 21, "away_score": 14,
         "_engine_week": 2},
        {"home_team_id": 2, "away_team_id": 1, "home_score": 21, "away_score": 14,
         "_engine_week": 3},
        {"home_team_id": 2, "away_team_id": 1, "home_score": 21, "away_score": 14,
         "_engine_week": 4},
        {"home_team_id": 2, "away_team_id": 1, "home_score": 21, "away_score": 14,
         "_engine_week": 5},
        # Most recent game: team 1 wins big at home.
        {"home_team_id": 1, "away_team_id": 2, "home_score": 56, "away_score": 0,
         "_engine_week": 6},  # capped to +35
    ]
    sig = team_form_signal(games, team_id=1, sport="Football", config=cfg)
    # Sanity: the unweighted mean would be (5*(-7) + 35)/6 = 0.0. The
    # recency-weighted version should be strictly positive.
    assert sig > 0.0, f"expected positive form signal, got {sig}"


def test_team_form_signal_single_game_equals_signed_margin():
    """With one game, the recency-weighted average is just that game's signed
    capped margin (the single weight cancels)."""
    cfg = PredictionConfig()
    games = [
        {"home_team_id": 5, "away_team_id": 6, "home_score": 28, "away_score": 14,
         "_engine_week": 1},
    ]
    assert team_form_signal(games, team_id=5, sport="Football", config=cfg) == pytest.approx(14.0)
    assert team_form_signal(games, team_id=6, sport="Football", config=cfg) == pytest.approx(-14.0)


# ---------------------------------------------------------------------------
# precompute_team_week_form
# ---------------------------------------------------------------------------
def test_precompute_team_week_form_through_week_inclusive():
    """Lookup at (team, W) covers games at weeks <= W (not future games),
    densified across the week range so the runner can index any W."""
    cfg = PredictionConfig()
    # Team 1 plays at weeks 1, 2, 3 — all +14 wins (below cap).
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 21, "away_score": 7,
         "_engine_week": 1},
        {"home_team_id": 1, "away_team_id": 3, "home_score": 21, "away_score": 7,
         "_engine_week": 2},
        {"home_team_id": 1, "away_team_id": 4, "home_score": 21, "away_score": 7,
         "_engine_week": 3},
    ]
    table = precompute_team_week_form(games, "Football", cfg)
    # With identical margins, the recency-weighted mean is just +14.0.
    assert table[(1, 1)] == pytest.approx(14.0)
    assert table[(1, 2)] == pytest.approx(14.0)
    assert table[(1, 3)] == pytest.approx(14.0)
    # Team 2 only plays at week 1; densification carries it forward.
    assert table[(2, 1)] == pytest.approx(-14.0)
    assert table[(2, 2)] == pytest.approx(-14.0)
    assert table[(2, 3)] == pytest.approx(-14.0)


def test_precompute_team_week_form_empty():
    cfg = PredictionConfig()
    assert precompute_team_week_form([], "Football", cfg) == {}


def test_precompute_team_week_form_skips_missing_scores():
    cfg = PredictionConfig()
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": None, "away_score": None,
         "_engine_week": 1},
        {"home_team_id": 1, "away_team_id": 2, "home_score": 28, "away_score": 14,
         "_engine_week": 2},
    ]
    table = precompute_team_week_form(games, "Football", cfg)
    assert (1, 1) not in table
    assert table[(1, 2)] == pytest.approx(14.0)


def test_precompute_team_week_form_recency_curve_takes_effect():
    """Across many games with varied margins, the precompute table should
    not collapse to the simple arithmetic mean — the most-recent games
    must carry more weight than the older ones."""
    cfg = PredictionConfig()
    # Team 1 plays 6 games. First 5 are -7 losses, the 6th is a +35 capped
    # blowout win. The simple mean is (5*(-7) + 35)/6 = 0.0; recency-weighted
    # form should be > 0 at week 6.
    games = [
        {"home_team_id": 2, "away_team_id": 1, "home_score": 21, "away_score": 14,
         "_engine_week": w}
        for w in (1, 2, 3, 4, 5)
    ] + [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 56, "away_score": 0,
         "_engine_week": 6},
    ]
    table = precompute_team_week_form(games, "Football", cfg)
    assert table[(1, 6)] > 0.0


# ---------------------------------------------------------------------------
# predict_game wiring
# ---------------------------------------------------------------------------
def test_predict_game_form_disabled_matches_baseline():
    """With recent_form NOT enabled, form signals must be ignored entirely."""
    cfg = PredictionConfig()  # no features enabled
    direct = win_probability_v2(70.0, 65.0, cfg, sport="Football")
    via = predict_game(
        70.0, 65.0, "Football", cfg,
        home_form_signal=10.0, away_form_signal=-5.0,
    )
    assert via == pytest.approx(direct, abs=1e-12)


def test_predict_game_form_enabled_zero_signal_matches_baseline():
    """recent_form on but with zero form signals -> baseline."""
    cfg = PredictionConfig(
        enabled_features=["recent_form"],
        form_weight_by_sport={"Football": 1.5},
    )
    direct = win_probability_v2(70.0, 65.0, cfg, sport="Football")
    via = predict_game(
        70.0, 65.0, "Football", cfg,
        home_form_signal=0.0, away_form_signal=0.0,
    )
    assert via == pytest.approx(direct, abs=1e-12)


def test_predict_game_form_enabled_signal_shifts_probability():
    """Positive home form signal -> P(home_win) up; negative -> down."""
    cfg = PredictionConfig(
        enabled_features=["recent_form"],
        form_weight_by_sport={"Football": 1.0},
    )
    baseline = predict_game(70.0, 70.0, "Football", cfg)
    boosted = predict_game(
        70.0, 70.0, "Football", cfg,
        home_form_signal=5.0, away_form_signal=0.0,
    )
    suppressed = predict_game(
        70.0, 70.0, "Football", cfg,
        home_form_signal=-5.0, away_form_signal=0.0,
    )
    assert boosted > baseline > suppressed


def test_predict_game_margin_plus_form_additive():
    """When both features are on, each signal contributes its own
    ``weight * signal`` to the effective rating (additive composition).

    Compare the both-on result against the explicit
    win_probability_v2(home_eff, away_eff, ...) value computed with the
    two adjustments added by hand.
    """
    cfg = PredictionConfig(
        enabled_features=["margin", "recent_form"],
        margin_weight_by_sport={"Football": 1.5},
        form_weight_by_sport={"Football": 2.0},
    )
    h_rating, a_rating = 70.0, 65.0
    h_margin, a_margin = 4.0, -2.0
    h_form, a_form = 3.0, 1.0

    # Manually compute the effective ratings.
    h_eff = h_rating + 1.5 * h_margin + 2.0 * h_form
    a_eff = a_rating + 1.5 * a_margin + 2.0 * a_form
    expected = win_probability_v2(h_eff, a_eff, cfg, sport="Football")

    got = predict_game(
        h_rating, a_rating, "Football", cfg,
        home_margin_signal=h_margin, away_margin_signal=a_margin,
        home_form_signal=h_form, away_form_signal=a_form,
    )
    assert got == pytest.approx(expected, abs=1e-12)


def test_predict_game_form_uses_default_weight_when_no_sport_entry():
    """Falls back to ``form_weight`` if the sport isn't in the per-sport map."""
    cfg = PredictionConfig(
        enabled_features=["recent_form"],
        form_weight=2.0,
        # No per-sport entry for 'Football'
    )
    expected = win_probability_v2(70.0 + 2.0 * 3.0, 65.0, cfg, sport="Football")
    got = predict_game(
        70.0, 65.0, "Football", cfg,
        home_form_signal=3.0, away_form_signal=0.0,
    )
    assert got == pytest.approx(expected, abs=1e-12)


# ---------------------------------------------------------------------------
# Regression: a margin-only run with form NOT enabled is unaffected.
# ---------------------------------------------------------------------------
def test_predict_game_margin_only_unchanged_by_form_field_presence():
    """Phase 2a path must be identical whether or not form_weight_by_sport is
    populated — recent_form is only consumed when it's in enabled_features."""
    h_rating, a_rating = 70.0, 65.0
    h_margin, a_margin = 4.0, -2.0

    cfg_a = PredictionConfig(
        enabled_features=["margin"],
        margin_weight_by_sport={"Football": 1.5},
    )
    cfg_b = PredictionConfig(
        enabled_features=["margin"],
        margin_weight_by_sport={"Football": 1.5},
        # form weights set but feature off -> must be ignored
        form_weight_by_sport={"Football": 99.0},
        form_weight=99.0,
    )
    p_a = predict_game(
        h_rating, a_rating, "Football", cfg_a,
        home_margin_signal=h_margin, away_margin_signal=a_margin,
        home_form_signal=10.0, away_form_signal=-10.0,
    )
    p_b = predict_game(
        h_rating, a_rating, "Football", cfg_b,
        home_margin_signal=h_margin, away_margin_signal=a_margin,
        home_form_signal=10.0, away_form_signal=-10.0,
    )
    assert p_a == pytest.approx(p_b, abs=1e-12)

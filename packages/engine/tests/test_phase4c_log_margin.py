"""Tests for Phase 4c log-margin feature (Δf_margin, β₃ slot).

Covers:
  - ``log_compressed_margin`` returns 0 on ties, monotone in |raw|,
    sign-preserving, log(|x|+1) shape.
  - ``team_log_margin_signal`` returns 0 with no games; correctly signs
    by team perspective; matches the per-game spec formula on small
    examples.
  - ``precompute_team_week_log_margins`` enforces temporal-boundary
    contract (entry at week W aggregates games with _engine_week <= W),
    is dense in W between min/max, returns no entry for teams that
    never played.
"""
from __future__ import annotations

import math

import pytest

from engine.prediction.features.log_margin import (
    log_compressed_margin,
    precompute_team_week_log_margins,
    team_log_margin_signal,
)


# ---------------------------------------------------------------------------
# log_compressed_margin
# ---------------------------------------------------------------------------
def test_log_compressed_margin_tie_is_zero():
    assert log_compressed_margin(7, 7) == 0.0
    assert log_compressed_margin(0, 0) == 0.0


def test_log_compressed_margin_sign():
    assert log_compressed_margin(21, 14) > 0    # home wins
    assert log_compressed_margin(14, 21) < 0    # away wins
    assert log_compressed_margin(21, 14) == pytest.approx(-log_compressed_margin(14, 21))


def test_log_compressed_margin_formula():
    # 49-7: ln(43)
    assert log_compressed_margin(49, 7) == pytest.approx(math.log(43))
    # 21-14: ln(8)
    assert log_compressed_margin(21, 14) == pytest.approx(math.log(8))
    # 14-21: -ln(8)
    assert log_compressed_margin(14, 21) == pytest.approx(-math.log(8))


def test_log_compressed_margin_blowout_compression():
    # Per spec rationale: a 49-7 win contributes ln(43) ≈ 3.76 vs a 21-14 win's
    # ln(8) ≈ 2.08. Informative ordering, not hostage to runaway scores.
    big = log_compressed_margin(49, 7)
    medium = log_compressed_margin(21, 14)
    assert big > medium                          # ordering preserved
    assert (big / medium) < 6.0                  # but blowout is not 6× more weight


def test_log_compressed_margin_monotone():
    # |raw| increases → magnitude increases
    for m in range(1, 50):
        cur = abs(log_compressed_margin(m, 0))
        nxt = abs(log_compressed_margin(m + 1, 0))
        assert nxt > cur


# ---------------------------------------------------------------------------
# team_log_margin_signal
# ---------------------------------------------------------------------------
def test_team_log_margin_signal_no_games_is_zero():
    assert team_log_margin_signal([], team_id=1) == 0.0
    assert team_log_margin_signal([{"home_team_id": 2, "away_team_id": 3,
                                    "home_score": 10, "away_score": 7}],
                                  team_id=1) == 0.0


def test_team_log_margin_signal_signs_by_team_perspective():
    # Team 1 wins 21-14 at home → +ln(8). Team 2 lost 14-21 → -ln(8).
    g = {"home_team_id": 1, "away_team_id": 2, "home_score": 21, "away_score": 14}
    assert team_log_margin_signal([g], team_id=1) == pytest.approx(math.log(8))
    assert team_log_margin_signal([g], team_id=2) == pytest.approx(-math.log(8))


def test_team_log_margin_signal_skips_unscored_games():
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 21, "away_score": 14},
        {"home_team_id": 1, "away_team_id": 3, "home_score": None, "away_score": None},
    ]
    # Unscored game ignored — mean across the 1 scored game = ln(8)
    assert team_log_margin_signal(games, team_id=1) == pytest.approx(math.log(8))


def test_team_log_margin_signal_means_across_games():
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 21, "away_score": 14},   # +ln 8
        {"home_team_id": 3, "away_team_id": 1, "home_score": 7, "away_score": 28},    # team 1 away,
                                                                                       # away wins 28-7
                                                                                       # → -log_cm(7,28) = -(-ln(22)) = +ln(22)
    ]
    expected = (math.log(8) + math.log(22)) / 2.0
    assert team_log_margin_signal(games, team_id=1) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# precompute_team_week_log_margins
# ---------------------------------------------------------------------------
def test_precompute_empty_input_is_empty_dict():
    assert precompute_team_week_log_margins([]) == {}


def test_precompute_skips_games_without_engine_week():
    games = [
        {"home_team_id": 1, "away_team_id": 2, "home_score": 21, "away_score": 14},
        # missing _engine_week
    ]
    assert precompute_team_week_log_margins(games) == {}


def test_precompute_skips_games_without_scores():
    games = [
        {"home_team_id": 1, "away_team_id": 2,
         "home_score": None, "away_score": None, "_engine_week": 1},
    ]
    assert precompute_team_week_log_margins(games) == {}


def test_precompute_through_week_contract():
    # Team 1: wins 21-14 in week 1, then loses 7-14 in week 2 (away).
    # Through week 1: signal = ln(8).
    # Through week 2: signal = (ln(8) + log_cm(7,14)_team1_away) / 2
    #               = (ln(8) + (-(-ln(8)))) / 2 = (ln(8) + ln(8))/2 = ln(8)... wait,
    # Wait — actually team 1 at home wins 21-14: +ln(8).
    # Team 1 away, game 7-14: log_cm(7,14) = -ln(8). Team 1 is away so signed: -(-ln(8)) = +ln(8).
    # Hmm both contribute +ln(8). Let me re-pick to avoid coincidence.
    games = [
        {"home_team_id": 1, "away_team_id": 2,
         "home_score": 21, "away_score": 14, "_engine_week": 1},   # team 1 home wins → +ln 8
        {"home_team_id": 3, "away_team_id": 1,
         "home_score": 28, "away_score": 7, "_engine_week": 2},    # team 1 away, lost 7-28
                                                                    # log_cm(28,7) = +ln(22)
                                                                    # team 1 away → -ln(22)
    ]
    out = precompute_team_week_log_margins(games)
    # Through week 1: team 1 has only the first game
    assert out[(1, 1)] == pytest.approx(math.log(8))
    # Through week 2: average of (+ln(8), -ln(22))
    expected_w2 = (math.log(8) + (-math.log(22))) / 2.0
    assert out[(1, 2)] == pytest.approx(expected_w2)


def test_precompute_dense_in_intervening_weeks():
    # Team 1 plays week 1 and week 4. Weeks 2 and 3 should carry the week-1
    # value (cumulative-mean is unchanged across no-game weeks).
    games = [
        {"home_team_id": 1, "away_team_id": 2,
         "home_score": 21, "away_score": 14, "_engine_week": 1},
        {"home_team_id": 1, "away_team_id": 3,
         "home_score": 35, "away_score": 0, "_engine_week": 4},
    ]
    out = precompute_team_week_log_margins(games)
    w1_signal = math.log(8)
    assert out[(1, 1)] == pytest.approx(w1_signal)
    assert out[(1, 2)] == pytest.approx(w1_signal)
    assert out[(1, 3)] == pytest.approx(w1_signal)
    assert (1, 4) in out


def test_precompute_no_entry_before_first_game():
    # Team 1 first plays in week 3. No entry at week 1 or 2.
    games = [
        {"home_team_id": 1, "away_team_id": 2,
         "home_score": 14, "away_score": 7, "_engine_week": 3},
        # A different team plays in week 1 so weeks_seen includes 1
        {"home_team_id": 4, "away_team_id": 5,
         "home_score": 10, "away_score": 0, "_engine_week": 1},
    ]
    out = precompute_team_week_log_margins(games)
    # Team 4 has entries 1, 2, 3; team 5 has entries 1, 2, 3; team 1 only has 3
    assert (1, 1) not in out
    assert (1, 2) not in out
    assert (1, 3) in out
    assert (4, 1) in out
    assert (5, 1) in out


def test_precompute_skips_unparseable_week():
    games = [
        {"home_team_id": 1, "away_team_id": 2,
         "home_score": 21, "away_score": 14, "_engine_week": "bad"},
        {"home_team_id": 1, "away_team_id": 3,
         "home_score": 14, "away_score": 7, "_engine_week": 2},
    ]
    out = precompute_team_week_log_margins(games)
    # First game's bad-week is dropped; team 1's only valid contribution is week 2.
    assert (1, 2) in out
    assert out[(1, 2)] == pytest.approx(math.log(8))


def test_precompute_temporal_boundary_strict():
    # Sanity check the runner's pattern: form.get((team_id, W-1)) must return
    # a signal built from games with _engine_week <= W-1.
    games = [
        {"home_team_id": 1, "away_team_id": 2,
         "home_score": 21, "away_score": 14, "_engine_week": 1},   # +ln(8)
        {"home_team_id": 1, "away_team_id": 3,
         "home_score": 35, "away_score": 0, "_engine_week": 2},    # +ln(36)
        {"home_team_id": 1, "away_team_id": 4,
         "home_score": 7, "away_score": 14, "_engine_week": 3},    # -ln(8)
    ]
    out = precompute_team_week_log_margins(games)
    # The runner predicting a week-3 game uses W-1=2 lookup
    expected_at_w2 = (math.log(8) + math.log(36)) / 2.0
    assert out[(1, 2)] == pytest.approx(expected_at_w2)
    # Week-3 game is NOT in the W-1=2 lookup (that's the leakage check)
    expected_at_w3 = (math.log(8) + math.log(36) + (-math.log(8))) / 3.0
    assert out[(1, 3)] == pytest.approx(expected_at_w3)
    # Strict inequality: out[(1,2)] != out[(1,3)] — week-3 game is excluded from the W=2 view
    assert out[(1, 2)] != out[(1, 3)]

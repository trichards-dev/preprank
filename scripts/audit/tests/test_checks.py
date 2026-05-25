"""Synthetic-fixture tests for the Phase 0 checks.

Each check gets one PASS-case fixture and one FAIL-case fixture so we know
the threshold logic actually flips. INFO-only checks (0.5, 0.6) just verify
the metrics shape.
"""
from __future__ import annotations

from scripts.audit.checks import (
    check_0_1_home_away_sanity,
    check_0_2_score_distribution,
    check_0_3_team_game_balance,
    check_0_4_league_arithmetic,
    check_0_5_mercy_rule,
    check_0_6_classification_drift,
)


def _g(home, away, hs, as_, *, status="final", date="2025-09-12", oos=False):
    return {
        "id": id((home, away, hs, as_, date)),
        "home_team_id": home,
        "away_team_id": away,
        "home_score": hs,
        "away_score": as_,
        "status": status,
        "is_out_of_state": oos,
        "game_date": date,
        "week_number": 1,
    }


# ---------------------------------------------------------------------------
# 0.1 home/away sanity
# ---------------------------------------------------------------------------
def test_0_1_pass_with_balanced_home_win_rate():
    # 16 home wins, 14 away wins → home_win_rate ≈ 0.533 (in pass band 0.50-0.62)
    games = [_g(1, 2, 21, 14) for _ in range(16)] + [_g(2, 1, 14, 21) for _ in range(14)]
    r = check_0_1_home_away_sanity(games, sport_id=1, sport_name="Football", season_year=2025)
    assert r.status == "pass"
    assert 0.50 <= r.metrics["home_win_rate"] <= 0.62


def test_0_1_fail_when_home_wins_88_percent():
    """The exact baseline scenario the v2 plan calls out for baseball."""
    games = [_g(1, 2, 7, 3) for _ in range(88)] + [_g(2, 1, 3, 7) for _ in range(12)]
    r = check_0_1_home_away_sanity(games, sport_id=11, sport_name="Baseball", season_year=2025)
    assert r.status == "fail"
    assert r.metrics["home_win_rate"] >= 0.85


def test_0_1_info_when_sample_too_small():
    games = [_g(1, 2, 7, 3) for _ in range(5)]
    r = check_0_1_home_away_sanity(games, 1, "Football", 2025)
    assert r.status == "info"


# ---------------------------------------------------------------------------
# 0.2 score distribution
# ---------------------------------------------------------------------------
def test_0_2_pass_with_normal_football_scores():
    games = [_g(1, 2, 28, 21) for _ in range(50)] + [_g(2, 1, 14, 35) for _ in range(50)]
    r = check_0_2_score_distribution(games, 1, "Football", 2025)
    assert r.status == "pass"
    assert 30 <= r.metrics["total_score_mean"] <= 80


def test_0_2_fail_on_negative_score():
    games = [_g(1, 2, 28, 21) for _ in range(50)] + [_g(2, 1, -3, 14)]
    r = check_0_2_score_distribution(games, 1, "Football", 2025)
    assert r.status == "fail"
    assert r.metrics["n_negative_score"] == 1


def test_0_2_fail_on_high_null_rate():
    games = [_g(1, 2, None, None) for _ in range(10)] + [_g(1, 2, 28, 21) for _ in range(90)]
    r = check_0_2_score_distribution(games, 1, "Football", 2025)
    assert r.status == "fail"
    assert r.metrics["null_score_rate"] >= 0.05


# ---------------------------------------------------------------------------
# 0.3 team-game balance
# ---------------------------------------------------------------------------
def test_0_3_pass_when_all_teams_balanced():
    teams = {i: {"division": "I", "school_name": f"T{i}"} for i in range(1, 21)}
    games = []
    for i in range(1, 21):
        for j in range(i + 1, 21):
            # alternate home/away so each team has equal home + away
            games.append(_g(i, j, 7, 14) if (i + j) % 2 else _g(j, i, 7, 14))
    r = check_0_3_team_game_balance(games, teams, 1, "Football", 2025)
    assert r.status == "pass"


def test_0_3_fail_when_most_teams_skewed():
    teams = {i: {"division": "I", "school_name": f"T{i}"} for i in range(1, 21)}
    # Every team plays team 0 with team i always home and team 0 always away.
    games = [_g(i, 99, 7, 3) for i in range(1, 21) for _ in range(5)]
    teams[99] = {"division": "I", "school_name": "T99"}
    r = check_0_3_team_game_balance(games, teams, 1, "Football", 2025)
    # team 99 plays 0 home / 100 away → imbalance 1.0
    # teams 1..20 play 5 home / 0 away each → imbalance 1.0
    assert r.status == "fail"
    assert r.metrics["frac_balanced"] < 0.5


# ---------------------------------------------------------------------------
# 0.4 intra-division arithmetic
# ---------------------------------------------------------------------------
def test_0_4_pass_on_clean_intra_division_games():
    teams = {i: {"division": "I"} for i in range(1, 5)}
    games = [_g(1, 2, 14, 7), _g(3, 4, 10, 0), _g(2, 3, 7, 6), _g(4, 1, 0, 14)]
    r = check_0_4_league_arithmetic(games, teams, 1, "Football", 2025)
    assert r.status == "pass"
    assert r.metrics["by_division"]["I"]["games"] == 4


def test_0_4_counts_cross_division_games_separately():
    """With the 2026-05-25 revision, cross-division games are tracked in
    their own aggregate (not silently dropped). Status reflects the cross
    aggregate's invariant when there are no intra-division games."""
    teams = {1: {"division": "I"}, 2: {"division": "II"}}
    games = [_g(1, 2, 14, 7)]
    r = check_0_4_league_arithmetic(games, teams, 1, "Football", 2025)
    assert r.status == "pass"
    assert r.metrics["cross_division_games"] == 1
    assert r.metrics["intra_division_games"] == 0


def test_0_4_info_when_no_games_at_all():
    r = check_0_4_league_arithmetic([], {}, 1, "Football", 2025)
    assert r.status == "info"


# ---------------------------------------------------------------------------
# 0.5 mercy-rule detection (info-only)
# ---------------------------------------------------------------------------
def test_0_5_reports_mercy_rate():
    games = [_g(1, 2, 56, 0) for _ in range(10)] + [_g(1, 2, 21, 14) for _ in range(40)]
    r = check_0_5_mercy_rule(games, 1, "Football", 2025)
    assert r.status == "info"
    assert r.metrics["mercy_rate"] == 0.2
    assert r.metrics["threshold"] == 36  # 2026-05-25: bumped from 35 → 36


def test_0_5_handles_sport_without_threshold():
    games = [_g(1, 2, 5, 3) for _ in range(10)]
    r = check_0_5_mercy_rule(games, 99, "Esports", 2025)
    assert r.status == "info"
    assert "threshold" not in r.metrics or r.metrics.get("threshold") is None


# ---------------------------------------------------------------------------
# 0.6 division drift (info-only)
# ---------------------------------------------------------------------------
def test_0_6_no_drift_when_division_stable():
    teams = [
        {"school_id": 1, "season_year": y, "division": "I", "sport_id": 1}
        for y in range(2021, 2026)
    ]
    r = check_0_6_classification_drift(teams, 1, "Football")
    assert r.status == "info"
    assert r.metrics["n_drifted_above_threshold"] == 0


def test_0_6_flags_any_division_change():
    """With max_changes_before_flag = 0, a single division change is flagged."""
    teams = [
        {"school_id": 1, "season_year": 2021, "division": "I", "sport_id": 1},
        {"school_id": 1, "season_year": 2022, "division": "I", "sport_id": 1},
        {"school_id": 1, "season_year": 2023, "division": "II", "sport_id": 1},
        {"school_id": 1, "season_year": 2024, "division": "II", "sport_id": 1},
    ]
    r = check_0_6_classification_drift(teams, 1, "Football")
    assert r.metrics["n_drifted_above_threshold"] == 1
    assert r.anomalies and r.anomalies[0]["school_id"] == 1

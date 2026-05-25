"""Tests for the reclassification-event detector."""
from __future__ import annotations

from scripts.audit.reclass_events import detect_reclass_events


def _team(school_id, season, division, sport_id=1):
    return {"school_id": school_id, "season_year": season,
            "division": division, "sport_id": sport_id}


def test_no_event_when_divisions_stable():
    teams = []
    for school in range(1, 21):
        for season in range(2021, 2026):
            teams.append(_team(school, season, "I"))
    events = detect_reclass_events(teams, sport_id=1, sport_name="Football")
    assert events == []


def test_detects_event_when_majority_changes_division():
    """80% of schools jump from Division V to Division IV in 2025 — should
    fire one event for the 2024 → 2025 transition. Uses min_schools=10
    override since the synthetic fixture has fewer than the production
    default (30) but the ratio behavior is the thing being tested."""
    teams = []
    for school in range(1, 21):
        for season in range(2021, 2026):
            if season == 2025 and school <= 16:
                teams.append(_team(school, season, "IV"))
            else:
                teams.append(_team(school, season, "V"))
    events = detect_reclass_events(teams, sport_id=1, sport_name="Football", min_schools=10)
    assert len(events) == 1
    e = events[0]
    assert e.season_year == 2025 and e.prior_season == 2024
    assert e.n_changed == 16 and e.n_schools_both_seasons == 20
    assert e.change_fraction == 0.8
    assert e.division_transitions == {"V -> IV": 16}


def test_threshold_is_respected():
    """30% change should NOT fire at default 50% threshold but SHOULD fire at 25%."""
    teams = []
    for school in range(1, 11):
        for season in range(2021, 2023):
            div = "II" if (season == 2022 and school <= 3) else "I"
            teams.append(_team(school, season, div))
    assert detect_reclass_events(teams, 1, "Football", threshold=0.50, min_schools=5) == []
    events = detect_reclass_events(teams, 1, "Football", threshold=0.25, min_schools=5)
    assert len(events) == 1
    assert events[0].n_changed == 3

"""Tests for the team_ingest extension.

Spec from Reese 2026-05-27 B1.2a: idempotent ingest, alias resolution
via engine.data.school_aliases, source attribution on every insert,
cross-reference against existing teams.sport_id before insert.
"""
from __future__ import annotations

import pytest

from engine.data.team_ingest import IngestResult, ingest_alignment


def _fake_inserter():
    """Returns (insert_fn, store_list, next_id_ref) — the inserter assigns
    sequential IDs starting at 1000 and appends to the store. Mirrors a
    fake DB."""
    counter = {"next": 1000}
    store: list[dict] = []

    def insert(payload: dict) -> dict:
        new_row = dict(payload)
        new_row["id"] = counter["next"]
        counter["next"] += 1
        store.append(new_row)
        return new_row

    return insert, store


def _simple_participation(sport_to_schools: dict[str, list[dict]]) -> dict:
    return {
        "season": "2025-26",
        "source": "test fixture",
        "participation": sport_to_schools,
    }


SPORT_ID_MAP = {
    "Football": 1, "Volleyball": 2, "Boys Basketball": 3, "Girls Basketball": 4,
    "Boys Soccer": 5, "Girls Soccer": 6, "Baseball": 7, "Softball": 8,
}


# ---------------------------------------------------------------------------
# Happy path: new schools + new teams insert
# ---------------------------------------------------------------------------
def test_ingest_inserts_new_school_and_team():
    participation = _simple_participation({
        "Football": [{"school": "Brand New School", "city": "Baton Rouge", "classification": "4A"}]
    })
    insert_school, school_store = _fake_inserter()
    insert_team, team_store = _fake_inserter()

    result = ingest_alignment(
        participation_data=participation,
        sport_id_map=SPORT_ID_MAP,
        season_year=2025,
        db_schools=[],
        db_teams=[],
        insert_school_fn=insert_school,
        insert_team_fn=insert_team,
    )

    assert result.n_schools_inserted == 1
    assert result.n_teams_inserted == 1
    assert result.schools_inserted[0]["name"] == "Brand New School"
    assert result.teams_inserted[0]["sport"] == "Football"
    assert result.teams_inserted[0]["season_year"] == 2025
    # Source attribution flows through
    assert result.schools_inserted[0]["source"] == result.source_attribution
    assert result.teams_inserted[0]["source"] == result.source_attribution
    assert school_store[0]["_source"] == result.source_attribution
    assert team_store[0]["_source"] == result.source_attribution


# ---------------------------------------------------------------------------
# Idempotency: re-running with same input produces no new inserts
# ---------------------------------------------------------------------------
def test_ingest_is_idempotent_on_existing_schools_and_teams():
    """If db_schools already has the school AND db_teams already has the
    (school, sport, season) tuple, no inserts happen."""
    participation = _simple_participation({
        "Football": [{"school": "Acadiana", "city": "Lafayette", "classification": "5A"}]
    })
    db_schools = [{"id": 1, "name": "Acadiana", "classification": "5A", "parish": None}]
    db_teams = [{"id": 100, "school_id": 1, "sport_id": 1, "season_year": 2025}]
    insert_school, school_store = _fake_inserter()
    insert_team, team_store = _fake_inserter()

    result = ingest_alignment(
        participation_data=participation,
        sport_id_map=SPORT_ID_MAP,
        season_year=2025,
        db_schools=db_schools,
        db_teams=db_teams,
        insert_school_fn=insert_school,
        insert_team_fn=insert_team,
    )
    assert result.n_schools_inserted == 0
    assert result.n_teams_inserted == 0
    assert len(result.schools_already_present) == 1
    assert len(result.teams_already_present) == 1
    assert school_store == []
    assert team_store == []


def test_ingest_idempotent_with_existing_school_new_team():
    """School row exists but team row for this sport-season doesn't —
    only the team row gets inserted."""
    participation = _simple_participation({
        "Football": [{"school": "Acadiana", "city": "Lafayette", "classification": "5A"}]
    })
    db_schools = [{"id": 1, "name": "Acadiana", "classification": "5A", "parish": None}]
    db_teams = []  # no team row yet
    insert_school, _ = _fake_inserter()
    insert_team, team_store = _fake_inserter()

    result = ingest_alignment(
        participation_data=participation,
        sport_id_map=SPORT_ID_MAP,
        season_year=2025,
        db_schools=db_schools, db_teams=db_teams,
        insert_school_fn=insert_school, insert_team_fn=insert_team,
    )
    assert result.n_schools_inserted == 0
    assert result.n_teams_inserted == 1
    assert team_store[0]["school_id"] == 1
    assert team_store[0]["sport_id"] == 1


# ---------------------------------------------------------------------------
# Alias resolution: B1.1 explicit aliases prevent duplicate inserts
# ---------------------------------------------------------------------------
def test_ingest_resolves_via_st_helena_alias():
    """The LHSAA canonical name 'St. Helena College and Career Acad.'
    must resolve to the DB row 'St. Helena College & Career Acad.' (id=98)
    via EXPLICIT_ALIASES — no new school row inserted."""
    participation = _simple_participation({
        "Football": [{"school": "St. Helena College and Career Acad.",
                       "city": "Greensburg", "classification": "2A"}]
    })
    db_schools = [{"id": 98, "name": "St. Helena College & Career Acad.",
                    "classification": "3A", "parish": None}]
    insert_school, school_store = _fake_inserter()
    insert_team, team_store = _fake_inserter()

    result = ingest_alignment(
        participation_data=participation,
        sport_id_map=SPORT_ID_MAP, season_year=2025,
        db_schools=db_schools, db_teams=[],
        insert_school_fn=insert_school, insert_team_fn=insert_team,
    )
    # School resolved via alias — NOT inserted
    assert result.n_schools_inserted == 0
    assert result.n_schools_resolved_via_alias == 1
    assert result.schools_resolved_via_alias[0]["resolved_to_id"] == 98
    # Team inserted against the resolved school_id
    assert result.n_teams_inserted == 1
    assert team_store[0]["school_id"] == 98
    assert school_store == []   # no school insert


def test_ingest_resolves_via_mentorship_alias():
    """Mentorship Academy → Helix Mentorship Academy (id=222) per
    2026-05-27 verification."""
    participation = _simple_participation({
        "Boys Basketball": [{"school": "Mentorship Academy",
                              "city": "Baton Rouge", "classification": "3A"}]
    })
    db_schools = [{"id": 222, "name": "Helix Mentorship Academy",
                    "classification": "4A", "parish": None}]
    insert_school, _ = _fake_inserter()
    insert_team, team_store = _fake_inserter()

    result = ingest_alignment(
        participation_data=participation,
        sport_id_map=SPORT_ID_MAP, season_year=2025,
        db_schools=db_schools, db_teams=[],
        insert_school_fn=insert_school, insert_team_fn=insert_team,
    )
    assert result.n_schools_inserted == 0
    assert result.n_schools_resolved_via_alias == 1
    assert team_store[0]["school_id"] == 222


def test_ingest_does_not_alias_known_false_positive():
    """Ben Franklin (LHSAA canonical, 4A NOLA) must NOT auto-resolve to
    Franklin (DB id=138, 2A Franklin LA) — they're distinct schools."""
    participation = _simple_participation({
        "Football": [{"school": "Ben Franklin", "city": "New Orleans",
                       "classification": "4A"}]
    })
    db_schools = [{"id": 138, "name": "Franklin", "classification": "2A", "parish": None}]
    insert_school, school_store = _fake_inserter()
    insert_team, team_store = _fake_inserter()

    result = ingest_alignment(
        participation_data=participation,
        sport_id_map=SPORT_ID_MAP, season_year=2025,
        db_schools=db_schools, db_teams=[],
        insert_school_fn=insert_school, insert_team_fn=insert_team,
    )
    # Ben Franklin must be inserted as a NEW school, not aliased to Franklin
    assert result.n_schools_inserted == 1
    assert result.n_schools_resolved_via_alias == 0
    assert school_store[0]["name"] == "Ben Franklin"
    # Team inserted against the new school id (not id=138)
    assert team_store[0]["school_id"] != 138
    assert team_store[0]["school_id"] == school_store[0]["id"]


# ---------------------------------------------------------------------------
# Multi-sport: school fielding multiple sports gets ONE school row + N team rows
# ---------------------------------------------------------------------------
def test_ingest_multi_sport_school_inserts_one_school_n_teams():
    """A new school that fields 3 sports should produce 1 school insert
    and 3 team inserts (one per sport)."""
    participation = _simple_participation({
        "Football": [{"school": "Multi Sport School", "city": "BR", "classification": "5A"}],
        "Boys Basketball": [{"school": "Multi Sport School", "city": "BR", "classification": "5A"}],
        "Baseball": [{"school": "Multi Sport School", "city": "BR", "classification": "5A"}],
    })
    insert_school, school_store = _fake_inserter()
    insert_team, team_store = _fake_inserter()
    result = ingest_alignment(
        participation_data=participation,
        sport_id_map=SPORT_ID_MAP, season_year=2025,
        db_schools=[], db_teams=[],
        insert_school_fn=insert_school, insert_team_fn=insert_team,
    )
    assert result.n_schools_inserted == 1
    assert len(school_store) == 1
    assert result.n_teams_inserted == 3
    assert {t["sport"] for t in result.teams_inserted} == {"Football", "Boys Basketball", "Baseball"}
    # All teams point to the same school_id
    school_ids = {t["school_id"] for t in team_store}
    assert len(school_ids) == 1
    assert next(iter(school_ids)) == school_store[0]["id"]


# ---------------------------------------------------------------------------
# Source attribution + skip handling
# ---------------------------------------------------------------------------
def test_ingest_custom_source_attribution_flows_through():
    participation = _simple_participation({
        "Football": [{"school": "Test School", "city": "X", "classification": "1A"}]
    })
    insert_school, _ = _fake_inserter()
    insert_team, _ = _fake_inserter()
    result = ingest_alignment(
        participation_data=participation, sport_id_map=SPORT_ID_MAP, season_year=2025,
        db_schools=[], db_teams=[],
        insert_school_fn=insert_school, insert_team_fn=insert_team,
        source_attribution="custom source label v1",
    )
    assert result.source_attribution == "custom source label v1"
    assert result.schools_inserted[0]["source"] == "custom source label v1"


def test_ingest_skips_unknown_sport():
    participation = _simple_participation({
        "Cricket": [{"school": "Bowler Academy", "city": "X", "classification": "5A"}]
    })
    insert_school, _ = _fake_inserter()
    insert_team, _ = _fake_inserter()
    result = ingest_alignment(
        participation_data=participation, sport_id_map=SPORT_ID_MAP, season_year=2025,
        db_schools=[], db_teams=[],
        insert_school_fn=insert_school, insert_team_fn=insert_team,
    )
    assert result.n_schools_inserted == 0
    assert result.n_teams_inserted == 0
    assert len(result.skipped_with_reasons) == 1
    assert result.skipped_with_reasons[0]["reason"] == "sport_not_in_id_map"


def test_ingest_skips_empty_school_name():
    participation = _simple_participation({
        "Football": [{"school": "", "city": "X", "classification": "1A"}]
    })
    insert_school, _ = _fake_inserter()
    insert_team, _ = _fake_inserter()
    result = ingest_alignment(
        participation_data=participation, sport_id_map=SPORT_ID_MAP, season_year=2025,
        db_schools=[], db_teams=[],
        insert_school_fn=insert_school, insert_team_fn=insert_team,
    )
    assert result.n_schools_inserted == 0
    assert len(result.skipped_with_reasons) == 1
    assert result.skipped_with_reasons[0]["reason"] == "empty_school_name"

"""Tests for the Workstream B1.2b bundled deploy.

Three concurrent changes that must ship together:
  (a) UniqueConstraint(home_team_id, away_team_id, sport_id, season_year, game_date)
      on the games table — declared on the Game model in apps/api/app/models.py,
      enforced by Alembic migration dc98fac605a9_add_games_unique_constraint.
  (b) scripts/ingest_sports_historical.py replaces .insert() with .upsert(
      on_conflict=<same five columns>) so re-runs are idempotent against the
      constraint.
  (c) scripts/ingest_sports_historical.py:calculate_and_store_ratings filters
      OOS schools (parish LIKE 'OOS%') AND any school with NULL classification
      out of team_records, preventing the pydantic ValidationError on NULL
      classification (Option B + belt-and-suspenders).

The model-level constraint declaration is covered by
``test_models.test_game_has_matchup_unique_constraint``.

The CI-enforced drift test below (test_constraint_columns_match_scraper_on_conflict)
runs WITHOUT a DB — that's deliberate; CI must catch on_conflict drift even
when no DB is available. The other tests require a live Supabase connection
and skip if env vars aren't set.
"""
from __future__ import annotations

import inspect
import os
import re
import sys
from pathlib import Path

import pytest

from sqlalchemy import UniqueConstraint


# Repo root must be on sys.path so the scripts/ package imports cleanly from
# this test (apps/api/tests/...). The api package itself is on sys.path
# already via pytest discovery, but scripts/ is not.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Per-test skip marker for the integration tests below. Module-level
# pytestmark would mask the drift test from CI when DB env is absent — bad.
_needs_supabase = pytest.mark.skipif(
    not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY")),
    reason="Integration tests require SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY",
)


# ---------------------------------------------------------------------------
# CI-enforced drift test — NO DB required. This is the test that catches
# the drift the inline comments warn about.
# ---------------------------------------------------------------------------
def test_constraint_columns_match_scraper_on_conflict():
    """CI-enforced parity between the games UniqueConstraint columns (source
    of truth in the Game model) and the on_conflict literal in the scraper's
    upsert call.

    If this fails, one of:
      (a) the model's __table_args__ UniqueConstraint columns changed, or
      (b) the scraper's on_conflict literal changed
    was edited without the other. They must move together.
    """
    from app.models import Game
    constraint = next(
        c for c in Game.__table_args__
        if isinstance(c, UniqueConstraint) and c.name == "uq_games_matchup"
    )
    constraint_cols = sorted(c.name for c in constraint.columns)

    import scripts.ingest_sports_historical as scraper
    src = inspect.getsource(scraper.run_sport)
    m = re.search(r'on_conflict="([^"]+)"', src)
    assert m is not None, \
        "Scraper run_sport() has no on_conflict literal — has the upsert been removed?"
    scraper_cols = sorted(m.group(1).split(","))

    assert constraint_cols == scraper_cols, (
        f"DRIFT between Game uq_games_matchup columns and scraper on_conflict:\n"
        f"  constraint: {constraint_cols}\n"
        f"  scraper:    {scraper_cols}\n"
        f"Both must list home_team_id, away_team_id, sport_id, season_year, game_date."
    )


def test_football_games_constraint_columns_match_scraper_on_conflict():
    """CI-enforced parity between Game uq_games_matchup and the FOOTBALL
    scraper's on_conflict literal. Mirrors the sports-scraper drift test
    above; ports the same B1.2b discipline to ingest_football_historical.py.

    The football scraper is currently dormant — Football data was last
    ingested before f35fc46 landed. This test exists from day one so any
    future football scrape is guarded against the constraint-drift bug
    class that B1.2b surfaced.
    """
    from app.models import Game
    constraint = next(
        c for c in Game.__table_args__
        if isinstance(c, UniqueConstraint) and c.name == "uq_games_matchup"
    )
    constraint_cols = sorted(c.name for c in constraint.columns)

    import scripts.ingest_football_historical as football_scraper
    src = inspect.getsource(football_scraper.run)
    # Find the games-table on_conflict literal specifically (the file has two:
    # one for games, one for power_ratings — match on the games table).
    games_block = re.search(
        r'sb\.table\("games"\)\.upsert\(.*?on_conflict="([^"]+)"',
        src,
        re.DOTALL,
    )
    assert games_block is not None, (
        "Football scraper run() has no games upsert with on_conflict — "
        "has it been removed or refactored?"
    )
    scraper_cols = sorted(games_block.group(1).split(","))

    assert constraint_cols == scraper_cols, (
        f"DRIFT between Game uq_games_matchup columns and FOOTBALL scraper on_conflict:\n"
        f"  constraint: {constraint_cols}\n"
        f"  scraper:    {scraper_cols}\n"
        f"Both must list home_team_id, away_team_id, sport_id, season_year, game_date."
    )


def test_power_ratings_constraint_columns_match_scraper_on_conflict():
    """CI-enforced parity between PowerRating uq_power_ratings_...'s columns
    and the on_conflict literal in calculate_and_store_ratings's power_ratings
    upsert call.

    CAVEAT: this test catches COLUMN-LIST DRIFT between the model constraint
    and the scraper on_conflict literal. It does NOT catch SEMANTIC
    WRONGNESS of the constraint design itself.

    The pre-existing 3-column declaration (team_id, week_number, season_year)
    was wrong by design — it ignored snapshot_date, so any drift test pointed
    at the 3-column declaration would have happily passed while the real bug
    (LHSAA-source time-series snapshots being force-merged) was wide open.
    A drift test guards mechanical consistency, not semantic correctness.

    Discovered during 2026-05-28 B1.2b post-mortem when Workstream B1.2b's
    smoke test exposed the 42P10 'no matching constraint' error on the
    on_conflict literal pointing at a constraint that existed nowhere.
    The fix was to expand to 5 columns + NULLS NOT DISTINCT.

    Future maintainers: if you're changing the rating-storage schema, ensure
    the data semantics (engine path vs lhsaa_official path) still align with
    a 5-column unique constraint. This test will NOT catch that.
    """
    from app.models import PowerRating
    constraint = next(
        c for c in PowerRating.__table_args__
        if isinstance(c, UniqueConstraint)
        and c.name == "uq_power_ratings_team_week_season_source_snapshot"
    )
    constraint_cols = sorted(c.name for c in constraint.columns)

    import scripts.ingest_sports_historical as scraper
    src = inspect.getsource(scraper.calculate_and_store_ratings)
    # The function may have multiple on_conflict references over time; find
    # the one that targets the power_ratings table.
    pr_block = re.search(
        r'sb\.table\("power_ratings"\)\.upsert\(.*?on_conflict="([^"]+)"',
        src,
        re.DOTALL,
    )
    assert pr_block is not None, (
        "calculate_and_store_ratings has no power_ratings upsert with on_conflict — "
        "has the upsert been removed or refactored?"
    )
    scraper_cols = sorted(pr_block.group(1).split(","))

    assert constraint_cols == scraper_cols, (
        f"DRIFT between PowerRating uq_power_ratings_... columns and scraper on_conflict:\n"
        f"  constraint: {constraint_cols}\n"
        f"  scraper:    {scraper_cols}\n"
        f"Both must list team_id, week_number, season_year, source, snapshot_date."
    )


def test_football_power_ratings_constraint_columns_match_scraper_on_conflict():
    """CI-enforced parity between PowerRating uq_power_ratings_... columns
    and the FOOTBALL scraper's power_ratings on_conflict literal. Mirrors
    the sports-scraper power_ratings drift test above.

    Same caveat as the sports power_ratings drift test: this catches
    column-list drift but NOT semantic wrongness of the constraint design
    itself. The 5-column NULLS NOT DISTINCT design (engine source=NULL,
    lhsaa_official source=DATE) is documented in PowerRating model docstring.
    """
    from app.models import PowerRating
    constraint = next(
        c for c in PowerRating.__table_args__
        if isinstance(c, UniqueConstraint)
        and c.name == "uq_power_ratings_team_week_season_source_snapshot"
    )
    constraint_cols = sorted(c.name for c in constraint.columns)

    import scripts.ingest_football_historical as football_scraper
    src = inspect.getsource(football_scraper.calculate_and_store_ratings)
    pr_block = re.search(
        r'sb\.table\("power_ratings"\)\.upsert\(.*?on_conflict="([^"]+)"',
        src,
        re.DOTALL,
    )
    assert pr_block is not None, (
        "Football scraper calculate_and_store_ratings has no power_ratings "
        "upsert with on_conflict — has it been removed or refactored?"
    )
    scraper_cols = sorted(pr_block.group(1).split(","))

    assert constraint_cols == scraper_cols, (
        f"DRIFT between PowerRating uq_power_ratings_... columns and FOOTBALL scraper on_conflict:\n"
        f"  constraint: {constraint_cols}\n"
        f"  scraper:    {scraper_cols}\n"
        f"Both must list team_id, week_number, season_year, source, snapshot_date."
    )


# ---------------------------------------------------------------------------
# Post-resolution dedup tests — NO DB required.
#
# Discovered 2026-05-28 GBB 2022 halt: the scraper's string-based
# deduplicate() at L347 lets name-variant duplicates through. After
# match_school() resolution they end up with the same (home_team_id,
# away_team_id, sport_id, season_year, game_date) tuple in games_to_insert,
# and the upsert crashes with Postgres 21000.
#
# The post-resolution dedup pass closes the hole; these tests guard it.
# ---------------------------------------------------------------------------
def test_post_resolution_dedup_collapses_name_variant_duplicates():
    """Two rows with the same team_id tuple but logically distinct source
    rows must collapse to one. Survivor picked by richness order."""
    from scripts.ingest_sports_historical import deduplicate_by_constraint

    games_to_insert = [
        # Row A: from 5A filter sweep, is_district=True (richer metadata)
        {
            "home_team_id": 100, "away_team_id": 200,
            "sport_id": 6, "season_year": 2022, "game_date": "2022-01-15",
            "home_score": 45, "away_score": 38, "status": "final",
            "is_district": True, "is_playoff": False, "week_number": None,
            "source": "lhsaaonline",
        },
        # Row B: same constraint tuple, from 4A filter sweep, is_district=False
        {
            "home_team_id": 100, "away_team_id": 200,
            "sport_id": 6, "season_year": 2022, "game_date": "2022-01-15",
            "home_score": 45, "away_score": 38, "status": "final",
            "is_district": False, "is_playoff": False, "week_number": None,
            "source": "lhsaaonline",
        },
        # Row C: different teams — must NOT be affected by dedup
        {
            "home_team_id": 300, "away_team_id": 400,
            "sport_id": 6, "season_year": 2022, "game_date": "2022-01-15",
            "home_score": 60, "away_score": 55, "status": "final",
            "is_district": True, "is_playoff": False, "week_number": None,
            "source": "lhsaaonline",
        },
    ]

    deduped, n_collisions = deduplicate_by_constraint(games_to_insert)

    assert n_collisions == 1
    assert len(deduped) == 2
    survivor = next(r for r in deduped if r["home_team_id"] == 100)
    assert survivor["is_district"] is True, \
        "Richness picker should keep the row with is_district=True"
    other = next(r for r in deduped if r["home_team_id"] == 300)
    assert other["home_score"] == 60


def test_post_resolution_dedup_prefers_later_seen_on_tie():
    """When richness is equal, the later-seen row wins — later classification
    filter sweeps are more likely to have corrected/updated entries."""
    from scripts.ingest_sports_historical import deduplicate_by_constraint

    row_first = {
        "home_team_id": 100, "away_team_id": 200,
        "sport_id": 12, "season_year": 2024, "game_date": "2024-03-15",
        "home_score": 5, "away_score": 3, "status": "final",
        "is_district": False, "is_playoff": False, "week_number": None,
        "source": "lhsaaonline-5A",
    }
    row_later = {**row_first, "source": "lhsaaonline-4A"}

    deduped, n_collisions = deduplicate_by_constraint([row_first, row_later])

    assert n_collisions == 1
    assert len(deduped) == 1
    assert deduped[0]["source"] == "lhsaaonline-4A", \
        "On tie, the later-seen row should win"


def test_post_resolution_dedup_no_collisions_passes_through():
    """Empty case: no collisions, input passes through unchanged."""
    from scripts.ingest_sports_historical import deduplicate_by_constraint

    rows = [
        {
            "home_team_id": 100, "away_team_id": 200,
            "sport_id": 6, "season_year": 2022, "game_date": "2022-01-15",
            "home_score": 45, "away_score": 38, "status": "final",
            "is_district": True, "is_playoff": False, "week_number": None,
        },
        {
            "home_team_id": 100, "away_team_id": 200,
            "sport_id": 6, "season_year": 2022, "game_date": "2022-01-22",
            "home_score": 50, "away_score": 40, "status": "final",
            "is_district": False, "is_playoff": False, "week_number": None,
        },
    ]
    deduped, n_collisions = deduplicate_by_constraint(rows)
    assert n_collisions == 0
    assert len(deduped) == 2


def test_post_resolution_dedup_empty_input_passes_through():
    """Empty input → empty output, zero collisions. Trivial-but-real edge case
    if a sport-year happens to have no matched games (e.g., a fresh season
    with no scrapeable data yet)."""
    from scripts.ingest_sports_historical import deduplicate_by_constraint
    deduped, n_collisions = deduplicate_by_constraint([])
    assert deduped == []
    assert n_collisions == 0


def test_post_resolution_dedup_richness_picker_score_dominates_metadata():
    """If two rows differ in score completeness AND metadata, score wins."""
    from scripts.ingest_sports_historical import deduplicate_by_constraint

    row_complete_scores_no_meta = {
        "home_team_id": 100, "away_team_id": 200,
        "sport_id": 12, "season_year": 2024, "game_date": "2024-03-15",
        "home_score": 5, "away_score": 3, "status": "final",
        "is_district": False, "is_playoff": False, "week_number": None,
    }
    row_null_score_rich_meta = {
        **row_complete_scores_no_meta,
        "home_score": None,
        "is_district": True,
        "is_playoff": True,
    }
    # Order matters for tie-break verification; put the WRONG candidate
    # second so a buggy "later-seen always wins" picker would fail this test
    deduped, n_collisions = deduplicate_by_constraint(
        [row_complete_scores_no_meta, row_null_score_rich_meta]
    )
    assert n_collisions == 1
    assert len(deduped) == 1
    assert deduped[0]["home_score"] == 5, \
        "Score completeness must beat metadata richness when they conflict"


# ---------------------------------------------------------------------------
# Integration tests — require live Supabase connection.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def sb():
    """A Supabase client bound to the configured project."""
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


@_needs_supabase
def test_upsert_idempotent_on_repeated_insert(sb):
    """The scraper's upsert with on_conflict on the canonical matchup columns
    must produce one row, not two, when called twice with the same payload.

    Uses a sentinel game_date far in the future so it can't collide with real
    data, and cleans up after itself.
    """
    SENTINEL_DATE = "2099-12-31"
    teams = sb.table("teams").select("id").limit(2).execute().data
    assert len(teams) >= 2, "DB must have at least 2 teams to run this test"
    home_id, away_id = teams[0]["id"], teams[1]["id"]
    sport_row = sb.table("teams").select("sport_id").eq("id", home_id).execute().data[0]
    sport_id = sport_row["sport_id"]
    season_year = 2099

    payload = {
        "home_team_id": home_id, "away_team_id": away_id,
        "sport_id": sport_id, "season_year": season_year,
        "game_date": SENTINEL_DATE,
        "home_score": 1, "away_score": 0, "status": "final",
        "source": "test_upsert_idempotent",
    }

    try:
        sb.table("games").upsert(
            [payload],
            on_conflict="home_team_id,away_team_id,sport_id,season_year,game_date",
        ).execute()
        count1 = sb.table("games").select("id", count="exact") \
            .eq("home_team_id", home_id).eq("away_team_id", away_id) \
            .eq("sport_id", sport_id).eq("season_year", season_year) \
            .eq("game_date", SENTINEL_DATE).execute().count
        assert count1 == 1, f"After first upsert: expected 1 row, got {count1}"

        sb.table("games").upsert(
            [payload],
            on_conflict="home_team_id,away_team_id,sport_id,season_year,game_date",
        ).execute()
        count2 = sb.table("games").select("id", count="exact") \
            .eq("home_team_id", home_id).eq("away_team_id", away_id) \
            .eq("sport_id", sport_id).eq("season_year", season_year) \
            .eq("game_date", SENTINEL_DATE).execute().count
        assert count2 == 1, f"After second upsert: expected 1 row, got {count2}"

        payload_updated = {**payload, "home_score": 99, "away_score": 88,
                           "source": "test_upsert_idempotent_v2"}
        sb.table("games").upsert(
            [payload_updated],
            on_conflict="home_team_id,away_team_id,sport_id,season_year,game_date",
        ).execute()
        count3 = sb.table("games").select("id, home_score, away_score", count="exact") \
            .eq("home_team_id", home_id).eq("away_team_id", away_id) \
            .eq("sport_id", sport_id).eq("season_year", season_year) \
            .eq("game_date", SENTINEL_DATE).execute()
        assert count3.count == 1, f"After updating upsert: expected 1 row, got {count3.count}"
        assert count3.data[0]["home_score"] == 99
    finally:
        sb.table("games") \
          .delete() \
          .eq("home_team_id", home_id).eq("away_team_id", away_id) \
          .eq("sport_id", sport_id).eq("season_year", season_year) \
          .eq("game_date", SENTINEL_DATE).execute()


@_needs_supabase
def test_unique_constraint_rejects_plain_insert_dupe(sb):
    """The DB-level constraint must reject duplicate INSERTs even when the
    scraper-side upsert is bypassed. This is the defense-in-depth check —
    future ingestion paths (manual SQL, third-party imports) can't sneak
    around the constraint."""
    SENTINEL_DATE = "2099-11-30"
    teams = sb.table("teams").select("id").limit(2).execute().data
    home_id, away_id = teams[0]["id"], teams[1]["id"]
    sport_row = sb.table("teams").select("sport_id").eq("id", home_id).execute().data[0]
    sport_id = sport_row["sport_id"]
    season_year = 2099
    payload = {
        "home_team_id": home_id, "away_team_id": away_id,
        "sport_id": sport_id, "season_year": season_year,
        "game_date": SENTINEL_DATE,
        "status": "final",
        "source": "test_unique_constraint",
    }

    try:
        sb.table("games").insert([payload]).execute()
        with pytest.raises(Exception) as excinfo:
            sb.table("games").insert([payload]).execute()
        # PostgREST surfaces unique-violation as code "23505"
        assert "23505" in str(excinfo.value) or "duplicate" in str(excinfo.value).lower(), \
            f"Expected unique-violation error, got: {excinfo.value}"
    finally:
        sb.table("games") \
          .delete() \
          .eq("home_team_id", home_id).eq("away_team_id", away_id) \
          .eq("sport_id", sport_id).eq("season_year", season_year) \
          .eq("game_date", SENTINEL_DATE).execute()


@_needs_supabase
def test_oos_and_null_classification_excluded_from_team_records(sb, monkeypatch):
    """calculate_and_store_ratings must not crash on OOS schools OR on any
    school with NULL classification, and must not include them in team_records.
    This is Option B + the belt-and-suspenders fix.

    Strategy: stub engine.calculate_all_ratings to capture team_records, then
    assert no problem school's team appears in it.
    """
    # Find real OOS schools + null-classification schools that already exist
    excluded_schools = sb.table("schools") \
        .select("id, name, parish, classification") \
        .or_("parish.like.OOS%,classification.is.null") \
        .execute().data
    if not excluded_schools:
        pytest.skip("No OOS or NULL-classification schools in DB to test against")
    excluded_school_ids = {s["id"] for s in excluded_schools}

    excluded_teams = sb.table("teams") \
        .select("id, school_id") \
        .eq("sport_id", 12).eq("season_year", 2024) \
        .in_("school_id", list(excluded_school_ids)) \
        .execute().data
    if not excluded_teams:
        pytest.skip("No Softball 2024 teams with excluded schools — regression scenario absent")
    excluded_team_ids = {t["id"] for t in excluded_teams}

    captured = {}
    def fake_calc(records, results):
        captured["team_records"] = records
        return {}

    import scripts.ingest_sports_historical as scraper
    monkeypatch.setattr("engine.power_rating.calculate_all_ratings", fake_calc)

    cfg = scraper.SPORTS["softball"]
    scraper.calculate_and_store_ratings(sb, cfg, 2024, team_cache={}, dry_run=True)

    records = captured.get("team_records", {})
    leaked = excluded_team_ids & set(records.keys())
    assert not leaked, (
        f"Excluded team_ids leaked into team_records (Option B regression): "
        f"{sorted(leaked)[:5]}..."
    )

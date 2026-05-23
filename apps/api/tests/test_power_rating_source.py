"""Tests for the source + snapshot_date columns and the partial unique indexes.

Requires: PostgreSQL with alembic head migration applied. The seed places
exactly one engine-source row per (team_id, week_number, season_year) on the
2025 football set; these tests are write-light and use unique team/week values
to avoid colliding with seed rows.
"""
from sqlalchemy import text
from app.database import SessionLocal


# Pick (team_id, week, year) values clearly outside the seed footprint (week 11, year 2025).
SAFE_TEAM_ID = 1
SAFE_WEEK = 88
SAFE_YEAR = 1999


def _cleanup(session, team_id: int = SAFE_TEAM_ID,
             week: int = SAFE_WEEK, year: int = SAFE_YEAR):
    session.execute(
        text("DELETE FROM power_ratings WHERE team_id = :tid AND season_year = :y"),
        {"tid": team_id, "y": year},
    )
    session.commit()


def test_source_defaults_to_engine():
    session = SessionLocal()
    try:
        _cleanup(session)
        session.execute(text("""
            INSERT INTO power_ratings (team_id, week_number, season_year, power_rating)
            VALUES (:tid, :week, :year, 50.0)
        """), {"tid": SAFE_TEAM_ID, "week": SAFE_WEEK, "year": SAFE_YEAR})
        session.commit()

        row = session.execute(text("""
            SELECT source FROM power_ratings
            WHERE team_id = :tid AND week_number = :week AND season_year = :year
        """), {"tid": SAFE_TEAM_ID, "week": SAFE_WEEK, "year": SAFE_YEAR}).first()
        assert row is not None
        assert row[0] == "engine"
    finally:
        _cleanup(session)
        session.close()


def test_engine_partial_unique_index_rejects_duplicates():
    session = SessionLocal()
    try:
        _cleanup(session)
        session.execute(text("""
            INSERT INTO power_ratings (team_id, week_number, season_year, power_rating, source)
            VALUES (:tid, :week, :year, 50.0, 'engine')
        """), {"tid": SAFE_TEAM_ID, "week": SAFE_WEEK, "year": SAFE_YEAR})
        session.commit()

        import pytest
        with pytest.raises(Exception) as excinfo:
            session.execute(text("""
                INSERT INTO power_ratings (team_id, week_number, season_year, power_rating, source)
                VALUES (:tid, :week, :year, 60.0, 'engine')
            """), {"tid": SAFE_TEAM_ID, "week": SAFE_WEEK, "year": SAFE_YEAR})
            session.commit()
        # SQLAlchemy wraps UniqueViolation in IntegrityError; either is fine.
        msg = str(excinfo.value).lower()
        assert "unique" in msg or "duplicate" in msg
        session.rollback()
    finally:
        _cleanup(session)
        session.close()


def test_lhsaa_and_engine_can_coexist_for_same_team_week_year():
    session = SessionLocal()
    try:
        _cleanup(session)
        session.execute(text("""
            INSERT INTO power_ratings (team_id, week_number, season_year, power_rating, source)
            VALUES (:tid, :week, :year, 50.0, 'engine')
        """), {"tid": SAFE_TEAM_ID, "week": SAFE_WEEK, "year": SAFE_YEAR})
        session.execute(text("""
            INSERT INTO power_ratings (team_id, week_number, season_year, power_rating, source, snapshot_date)
            VALUES (:tid, :week, :year, 51.5, 'lhsaa_official', NULL)
        """), {"tid": SAFE_TEAM_ID, "week": SAFE_WEEK, "year": SAFE_YEAR})
        session.commit()

        n = session.execute(text("""
            SELECT count(*) FROM power_ratings
            WHERE team_id = :tid AND week_number = :week AND season_year = :year
        """), {"tid": SAFE_TEAM_ID, "week": SAFE_WEEK, "year": SAFE_YEAR}).scalar()
        assert n == 2
    finally:
        _cleanup(session)
        session.close()


def test_lhsaa_partial_unique_index_rejects_duplicate_finals():
    """NULLS NOT DISTINCT means two NULL-snapshot_date Final rows collide."""
    session = SessionLocal()
    try:
        _cleanup(session)
        session.execute(text("""
            INSERT INTO power_ratings (team_id, week_number, season_year, power_rating, source, snapshot_date)
            VALUES (:tid, 99, :year, 70.0, 'lhsaa_official', NULL)
        """), {"tid": SAFE_TEAM_ID, "year": SAFE_YEAR})
        session.commit()

        import pytest
        with pytest.raises(Exception) as excinfo:
            session.execute(text("""
                INSERT INTO power_ratings (team_id, week_number, season_year, power_rating, source, snapshot_date)
                VALUES (:tid, 99, :year, 71.0, 'lhsaa_official', NULL)
            """), {"tid": SAFE_TEAM_ID, "year": SAFE_YEAR})
            session.commit()
        msg = str(excinfo.value).lower()
        assert "unique" in msg or "duplicate" in msg
        session.rollback()
    finally:
        _cleanup(session)
        session.close()


def test_lhsaa_distinct_snapshot_dates_can_coexist():
    session = SessionLocal()
    try:
        _cleanup(session)
        session.execute(text("""
            INSERT INTO power_ratings (team_id, week_number, season_year, power_rating, source, snapshot_date)
            VALUES (:tid, 50, :year, 70.0, 'lhsaa_official', DATE '1999-03-01')
        """), {"tid": SAFE_TEAM_ID, "year": SAFE_YEAR})
        session.execute(text("""
            INSERT INTO power_ratings (team_id, week_number, season_year, power_rating, source, snapshot_date)
            VALUES (:tid, 50, :year, 72.0, 'lhsaa_official', DATE '1999-03-15')
        """), {"tid": SAFE_TEAM_ID, "year": SAFE_YEAR})
        session.commit()

        n = session.execute(text("""
            SELECT count(*) FROM power_ratings
            WHERE team_id = :tid AND season_year = :year AND source = 'lhsaa_official'
        """), {"tid": SAFE_TEAM_ID, "year": SAFE_YEAR}).scalar()
        assert n == 2
    finally:
        _cleanup(session)
        session.close()

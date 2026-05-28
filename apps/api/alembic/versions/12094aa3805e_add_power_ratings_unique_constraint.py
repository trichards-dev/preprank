"""add_power_ratings_unique_constraint

Revision ID: 12094aa3805e
Revises: dc98fac605a9
Create Date: 2026-05-28 14:50:32.604813

Adds UniqueConstraint(team_id, week_number, season_year, source, snapshot_date)
NULLS NOT DISTINCT to the power_ratings table, named
`uq_power_ratings_team_week_season_source_snapshot`.

Requires PostgreSQL 15+ for `NULLS NOT DISTINCT` syntax. Verified PG 17.6 at
deploy time (server_version_num = 170006). If this migration is ever ported
to PG <15, swap to a partial unique index using
`COALESCE(snapshot_date, '1900-01-01'::date)` as a NULL sentinel — same
semantics, uglier syntax.

Why 5 columns instead of 3:
  The PowerRating table has two writer paths with different semantics:
    - `source='engine'`, `snapshot_date=NULL`: one row per (team, week, season),
      idempotent over recompute reruns.
    - `source='lhsaa_official'`, `snapshot_date=<DATE>`: one row per LHSAA
      publication date (time-series snapshots).
  A 3-column constraint (team, week, season) would force-merge 311 legitimate
  time-series snapshots from the LHSAA loader. The 5-column constraint with
  NULLS NOT DISTINCT serves both writers correctly:
    - Engine reruns with NULL=NULL conflict → upsert update in place.
    - LHSAA publications with distinct dates → preserved as distinct rows.

Bundled with the games unique constraint (dc98fac605a9) and four code changes:
  - apps/api/app/models.py Game.__table_args__ (uq_games_matchup)
  - apps/api/app/models.py PowerRating.__table_args__ (uq_power_ratings_...)
  - scripts/ingest_sports_historical.py games upsert at line 701
  - scripts/ingest_sports_historical.py power_ratings upsert at line 564
Both code on_conflict literals are CI-enforced against the model constraints
by tests in apps/api/tests/test_b1_2b_bundle.py.

Pre-migration global-duplicate sanity check (executed 2026-05-28) returned
zero duplicate groups across the 5-column tuple set on the 101,811 existing
power_ratings rows, so the constraint applies cleanly without data work.

Downgrade: drops the constraint. No data is lost on rollback since the
constraint is purely a uniqueness gate.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '12094aa3805e'
down_revision: Union[str, Sequence[str], None] = 'dc98fac605a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE power_ratings
        ADD CONSTRAINT uq_power_ratings_team_week_season_source_snapshot
        UNIQUE NULLS NOT DISTINCT (team_id, week_number, season_year, source, snapshot_date);
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE power_ratings "
        "DROP CONSTRAINT IF EXISTS uq_power_ratings_team_week_season_source_snapshot;"
    )

"""add_source_and_snapshot_to_power_ratings

Revision ID: d5e2a8f3b1c0
Revises: c3d7f9a1b2e4
Create Date: 2026-05-23 00:00:00.000000

Adds provenance to power_ratings so engine-computed and LHSAA-official rows
can coexist. Engine and LHSAA rows have different identity semantics, so the
3-column unique constraint is replaced by two partial unique indexes:

  - engine: UNIQUE(team_id, week_number, season_year) WHERE source = 'engine'
  - lhsaa : UNIQUE(team_id, season_year, source, snapshot_date) WHERE source <> 'engine'
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd5e2a8f3b1c0'
down_revision: Union[str, None] = 'c3d7f9a1b2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE power_ratings ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'engine';")
    op.execute("ALTER TABLE power_ratings ADD COLUMN IF NOT EXISTS snapshot_date DATE;")

    # Drop the auto-named 3-column unique constraint by introspection. The
    # initial migration (a5a94be6e8d8) created it inline so the name is
    # auto-generated and may differ if any environment was hand-touched.
    op.execute("""
        DO $$
        DECLARE c text;
        BEGIN
          SELECT conname INTO c
          FROM pg_constraint
          WHERE conrelid = 'power_ratings'::regclass
            AND contype = 'u'
            AND (
              SELECT array_agg(attname ORDER BY attname)
              FROM pg_attribute
              WHERE attrelid = 'power_ratings'::regclass
                AND attnum = ANY(conkey)
            ) = ARRAY['season_year','team_id','week_number']::name[];
          IF c IS NOT NULL THEN
            EXECUTE format('ALTER TABLE power_ratings DROP CONSTRAINT %I', c);
          END IF;
        END $$;
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS power_ratings_engine_uniq
        ON power_ratings (team_id, week_number, season_year)
        WHERE source = 'engine';
    """)
    # NULLS NOT DISTINCT so "Final" snapshots (snapshot_date IS NULL) collide
    # on re-run — without it, Postgres treats each NULL as unique and we'd
    # silently insert duplicate Final rows. Requires Postgres 15+; Supabase is fine.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS power_ratings_lhsaa_uniq
        ON power_ratings (team_id, season_year, source, snapshot_date)
        NULLS NOT DISTINCT
        WHERE source <> 'engine';
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS power_ratings_lhsaa_uniq;")
    op.execute("DROP INDEX IF EXISTS power_ratings_engine_uniq;")
    op.execute("""
        ALTER TABLE power_ratings
        ADD CONSTRAINT power_ratings_team_id_week_number_season_year_key
        UNIQUE (team_id, week_number, season_year);
    """)
    op.execute("ALTER TABLE power_ratings DROP COLUMN IF EXISTS snapshot_date;")
    op.execute("ALTER TABLE power_ratings DROP COLUMN IF EXISTS source;")

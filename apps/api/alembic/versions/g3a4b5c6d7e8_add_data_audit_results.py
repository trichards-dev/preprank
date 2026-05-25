"""add_data_audit_results

Revision ID: g3a4b5c6d7e8
Revises: f8b1c2d3e4f5
Create Date: 2026-05-25 00:00:00.000000

Adds data_audit_results — per-run, per-(sport, season) audit-trail rows for
the Phase 0 data sanity audit (TASK 2 of v2 validation plan).

Each run of `python -m scripts.audit` generates a single run_id (uuid) and
writes one row per (sport, season, check_name). status is one of
{'pass','warn','fail','info'}; structured detail (metrics, anomaly lists,
threshold values) lives in the details JSONB column.

RLS enabled with no anon policies — API/superuser only.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'g3a4b5c6d7e8'
down_revision: Union[str, None] = 'f8b1c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS data_audit_results (
          id BIGSERIAL PRIMARY KEY,
          run_id UUID NOT NULL,
          sport_id INTEGER REFERENCES sports(id),
          season_year INTEGER,
          check_name TEXT NOT NULL,
          status TEXT NOT NULL CHECK (status IN ('pass','warn','fail','info')),
          details JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS data_audit_results_run_idx
          ON data_audit_results (run_id, created_at DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS data_audit_results_sport_season_check_idx
          ON data_audit_results (sport_id, season_year, check_name);
    """)
    op.execute("ALTER TABLE data_audit_results ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE data_audit_results FORCE ROW LEVEL SECURITY;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS data_audit_results;")

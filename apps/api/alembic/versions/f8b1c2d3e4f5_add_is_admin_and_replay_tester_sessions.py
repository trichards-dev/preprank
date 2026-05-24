"""add_is_admin_and_replay_tester_sessions

Revision ID: f8b1c2d3e4f5
Revises: e7a3b1d9c4f5
Create Date: 2026-05-24 00:00:00.000000

Two related changes to support the internal Replay QA admin tool:
  1. users.is_admin BOOLEAN NOT NULL DEFAULT false — gates the /admin/* routes
  2. replay_tester_sessions — capture table for the family testers'
     feedback during historical-week replays.

RLS: replay_tester_sessions has RLS enabled with no anon policies — only
the API (postgres superuser) and service role can read/write. The
require_admin() dependency in the API enforces user.is_admin at the
endpoint layer.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'f8b1c2d3e4f5'
down_revision: Union[str, None] = 'e7a3b1d9c4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false;"
    )
    op.execute("""
        CREATE TABLE IF NOT EXISTS replay_tester_sessions (
          id SERIAL PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          sport_id INTEGER NOT NULL REFERENCES sports(id),
          season_year INTEGER NOT NULL,
          week_number INTEGER NOT NULL,
          task_text TEXT NOT NULL,
          task_completed BOOLEAN NOT NULL DEFAULT false,
          time_to_complete_seconds INTEGER,
          bug_found BOOLEAN NOT NULL DEFAULT false,
          bug_severity INTEGER,
          feature_gap_text TEXT,
          screenshot_url TEXT,
          created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS replay_sessions_user_idx
          ON replay_tester_sessions (user_id, created_at DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS replay_sessions_sport_season_week_idx
          ON replay_tester_sessions (sport_id, season_year, week_number);
    """)
    op.execute("ALTER TABLE replay_tester_sessions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE replay_tester_sessions FORCE ROW LEVEL SECURITY;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS replay_tester_sessions;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_admin;")

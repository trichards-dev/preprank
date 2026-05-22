"""enable_rls_policies

Revision ID: c3d7f9a1b2e4
Revises: 8f3a1c2d4e5b
Create Date: 2026-05-22 00:00:00.000000

RLS policy model:
  - Public read (anon SELECT): sports, schools, teams, games, power_ratings,
    hype_scores, athletes, athlete_stats, pickem_contests
  - No direct access (API/service role only): users, user_favorites, notifications,
    refresh_tokens, pickem_entries, pickem_badges, simulations, projected_ratings,
    game_predictions, game_impact_analysis, alembic_version
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c3d7f9a1b2e4'
down_revision: Union[str, None] = '8f3a1c2d4e5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables the anon role can SELECT freely (public sports data)
PUBLIC_READ_TABLES = [
    "sports",
    "schools",
    "teams",
    "games",
    "power_ratings",
    "hype_scores",
    "athletes",
    "athlete_stats",
    "pickem_contests",
]

# All tables — RLS enabled on everything, no anon access except the list above
ALL_TABLES = PUBLIC_READ_TABLES + [
    "users",
    "user_favorites",
    "notifications",
    "refresh_tokens",
    "pickem_entries",
    "pickem_badges",
    "simulations",
    "projected_ratings",
    "game_predictions",
    "game_impact_analysis",
    "alembic_version",
]


def upgrade() -> None:
    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")

    for table in PUBLIC_READ_TABLES:
        op.execute(f"""
            CREATE POLICY "{table}_anon_select"
            ON {table}
            FOR SELECT
            TO anon
            USING (true);
        """)


def downgrade() -> None:
    for table in PUBLIC_READ_TABLES:
        op.execute(f'DROP POLICY IF EXISTS "{table}_anon_select" ON {table};')

    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

"""add_games_unique_constraint

Revision ID: dc98fac605a9
Revises: g3a4b5c6d7e8
Create Date: 2026-05-28 14:13:06.398494

Adds UniqueConstraint(home_team_id, away_team_id, sport_id, season_year,
game_date) to the games table, named `uq_games_matchup`. Bundled with two
code changes that ship together (must NOT deploy separately):

  - apps/api/app/models.py Game model gains a matching UniqueConstraint in
    __table_args__ — the ORM declaration is the source of truth.
  - scripts/ingest_sports_historical.py replaces plain INSERT with UPSERT
    using on_conflict on the same five columns. Drift between the constraint
    columns and the on_conflict target = silent no-op = corruption returns
    invisibly. The test
    apps/api/tests/test_b1_2b_bundle.py::test_constraint_columns_match_scraper_on_conflict
    enforces parity at CI time.

Cleanup history (executed before this migration applied):
  - 2026-05-28: 5,205 duplicate Softball 2024 rows removed via Workstream
    B1.2b cleanup Call C (atomic DO block, MCP implicit transaction).
    All run-duplicates from orchestrator re-runs, identical scores within
    groups (no doubleheaders lost). Backup table retained:
    games_backup_softball_2024_pre_dedup (8,085 rows).

  - 2026-05-28: 2 spurious Girls Basketball 2022 rows (ids 34717, 34718)
    removed. MaxPreps source-of-truth check confirmed Northlake Christian
    and Parkview Baptist played NO game on 2021-12-21 — both rows describe
    a non-existent game. Backup table retained:
    games_backup_gbb_2022_spurious (2 rows).

Pre-migration global-duplicate sanity check (Call C step 6) returned zero
duplicate groups across the entire games table, so the constraint applies
cleanly without further data work.

Backup tables are NOT dropped here. They remain in place until the full
Workstream B1.2b run signs off, at which point a separate cleanup migration
drops them. Do NOT bundle that drop into this migration.

Downgrade: drops the constraint. Backup tables remain untouched on rollback
since they were created outside the migration.

Known limitation: the constraint treats one game per matchup-per-day as
canonical. Real-world doubleheaders (two games same teams same day with
distinct times) exist in the LHSAA source — currently collapsed upstream by
the scraper's in-memory deduplicate() function, which keys by
(sorted school pair, date). Doubleheader recovery (parser update to capture
game_time, schema column add, constraint extension) is parked as backlog
post engine candidate-final. See claude-memory/apps/preprank/open-questions.md.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'dc98fac605a9'
down_revision: Union[str, Sequence[str], None] = 'g3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE games
        ADD CONSTRAINT uq_games_matchup
        UNIQUE (home_team_id, away_team_id, sport_id, season_year, game_date);
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE games DROP CONSTRAINT IF EXISTS uq_games_matchup;")

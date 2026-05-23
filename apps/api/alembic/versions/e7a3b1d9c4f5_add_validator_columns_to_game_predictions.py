"""add_validator_columns_to_game_predictions

Revision ID: e7a3b1d9c4f5
Revises: d5e2a8f3b1c0
Create Date: 2026-05-23 00:00:00.000000

Adds provenance columns to game_predictions so engine validator runs can
co-store predictions alongside product simulation outputs:
  - config_label: which validator config produced this prediction ('baseline',
    'phase-2a', 'phase-2b', etc.). Defaults to 'baseline' so existing rows
    (if any) get a sensible tag.
  - run_id: UUID that groups predictions from a single validator run.

simulation_id is relaxed to nullable because validator runs don't simulate;
they predict directly from power-rating + win_probability_v2.

Unique index on (game_id, config_label, run_id) keeps re-running a single
validator config idempotent at the row level.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e7a3b1d9c4f5'
down_revision: Union[str, None] = 'd5e2a8f3b1c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE game_predictions
          ADD COLUMN IF NOT EXISTS config_label TEXT NOT NULL DEFAULT 'baseline',
          ADD COLUMN IF NOT EXISTS run_id UUID;
    """)
    op.execute("ALTER TABLE game_predictions ALTER COLUMN simulation_id DROP NOT NULL;")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS game_predictions_game_config_run_uniq
          ON game_predictions (game_id, config_label, run_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS game_predictions_config_run_idx
          ON game_predictions (config_label, run_id);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS game_predictions_config_run_idx;")
    op.execute("DROP INDEX IF EXISTS game_predictions_game_config_run_uniq;")
    # Note: we don't re-enforce NOT NULL on simulation_id during downgrade because
    # nullable rows from validator runs may exist. Operator should clean those up first.
    op.execute("ALTER TABLE game_predictions DROP COLUMN IF EXISTS run_id;")
    op.execute("ALTER TABLE game_predictions DROP COLUMN IF EXISTS config_label;")

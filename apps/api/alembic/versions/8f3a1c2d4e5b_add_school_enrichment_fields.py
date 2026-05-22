"""add_school_enrichment_fields

Revision ID: 8f3a1c2d4e5b
Revises: 2e507355448f
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8f3a1c2d4e5b'
down_revision: Union[str, None] = '2e507355448f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('schools', sa.Column('mascot', sa.String(100), nullable=True))
    op.add_column('schools', sa.Column('mascot_url', sa.String(500), nullable=True))
    op.add_column('schools', sa.Column('color1', sa.String(10), nullable=True))
    op.add_column('schools', sa.Column('color2', sa.String(10), nullable=True))
    op.add_column('schools', sa.Column('maxpreps_uuid', sa.String(50), nullable=True))
    op.create_index('ix_schools_maxpreps_uuid', 'schools', ['maxpreps_uuid'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_schools_maxpreps_uuid', table_name='schools')
    op.drop_column('schools', 'maxpreps_uuid')
    op.drop_column('schools', 'color2')
    op.drop_column('schools', 'color1')
    op.drop_column('schools', 'mascot_url')
    op.drop_column('schools', 'mascot')

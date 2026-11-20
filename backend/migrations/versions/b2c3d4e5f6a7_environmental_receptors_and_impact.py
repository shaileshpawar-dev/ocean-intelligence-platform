"""Add marine_receptors and candidate_environmental_impacts tables (Phase 17).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-12 14:00:00.000000+00:00

Changes:
1. Creates marine_receptors table for Marine Protected Areas (MPAs), coral reefs,
   mangroves, and critical coastal infrastructure (desalination/cooling intakes).
2. Creates candidate_environmental_impacts table storing spatial exposure distances,
   composite vulnerability indices (0-100), and priority mitigation actions.
3. Fully additive and non-destructive to existing database baseline.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. marine_receptors
    op.create_table(
        'marine_receptors',
        sa.Column('receptor_id', sa.String(length=64), primary_key=True),
        sa.Column('name', sa.String(length=128), nullable=False, index=True),
        sa.Column('category', sa.String(length=64), nullable=False, index=True),
        sa.Column('jurisdiction', sa.String(length=128), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('boundary_geojson', sa.JSON(), nullable=True),
        sa.Column('vulnerability_weight', sa.Float(), nullable=False, server_default='0.80'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_marine_receptors_geo', 'marine_receptors', ['latitude', 'longitude'])

    # 2. candidate_environmental_impacts
    op.create_table(
        'candidate_environmental_impacts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('candidate_id', sa.String(length=64), sa.ForeignKey('sar_candidates.candidate_id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('receptor_id', sa.String(length=64), sa.ForeignKey('marine_receptors.receptor_id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('distance_km', sa.Float(), nullable=False),
        sa.Column('estimated_arrival_hours', sa.Float(), nullable=True),
        sa.Column('impact_severity', sa.String(length=32), nullable=False, server_default='LOW', index=True),
        sa.Column('vulnerability_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('priority_action', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_cand_env_impact_cand', 'candidate_environmental_impacts', ['candidate_id', 'distance_km'])


def downgrade() -> None:
    op.drop_table('candidate_environmental_impacts')
    op.drop_table('marine_receptors')

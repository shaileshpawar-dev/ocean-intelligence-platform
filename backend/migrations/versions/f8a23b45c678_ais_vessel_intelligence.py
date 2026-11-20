"""Add AIS vessel tables and candidate vessel association (Phase 15).

Revision ID: f8a23b45c678
Revises: e7f12a34b567
Create Date: 2026-11-12 12:00:00.000000+00:00

Changes:
1. Creates vessels table for commercial vessel registry and risk profiling.
2. Creates vessel_positions table for timestamped AIS ping trajectories.
3. Creates candidate_vessel_associations table connecting SAR slick candidates to proximate vessel tracks.
4. Fully additive and non-destructive to existing SAR and optical baseline.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8a23b45c678'
down_revision: Union[str, None] = 'e7f12a34b567'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. vessels table
    op.create_table(
        'vessels',
        sa.Column('mmsi', sa.String(length=16), primary_key=True),
        sa.Column('imo', sa.String(length=16), nullable=True, index=True),
        sa.Column('name', sa.String(length=128), nullable=False, index=True),
        sa.Column('callsign', sa.String(length=16), nullable=True),
        sa.Column('vessel_type', sa.String(length=64), nullable=False, index=True),
        sa.Column('flag_country', sa.String(length=64), nullable=False, index=True),
        sa.Column('length_m', sa.Float(), nullable=True),
        sa.Column('width_m', sa.Float(), nullable=True),
        sa.Column('draught_m', sa.Float(), nullable=True),
        sa.Column('risk_profile', sa.String(length=64), nullable=False, server_default='STANDARD'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # 2. vessel_positions table
    op.create_table(
        'vessel_positions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('mmsi', sa.String(length=16), sa.ForeignKey('vessels.mmsi', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('latitude', sa.Float(), nullable=False, index=True),
        sa.Column('longitude', sa.Float(), nullable=False, index=True),
        sa.Column('speed_knots', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('heading_deg', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('nav_status', sa.String(length=64), nullable=False, server_default='Under way using engine'),
        sa.Column('destination', sa.String(length=128), nullable=True),
    )
    op.create_index('ix_vessel_pos_mmsi_time', 'vessel_positions', ['mmsi', 'timestamp'])
    op.create_index('ix_vessel_pos_geo', 'vessel_positions', ['latitude', 'longitude'])

    # 3. candidate_vessel_associations table
    op.create_table(
        'candidate_vessel_associations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('candidate_id', sa.String(length=64), sa.ForeignKey('sar_candidates.candidate_id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('mmsi', sa.String(length=16), sa.ForeignKey('vessels.mmsi', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('association_type', sa.String(length=64), nullable=False, server_default='PROXIMATE_TRANSIT', index=True),
        sa.Column('spatial_distance_km', sa.Float(), nullable=False),
        sa.Column('temporal_offset_minutes', sa.Float(), nullable=False),
        sa.Column('interpolated_lat', sa.Float(), nullable=False),
        sa.Column('interpolated_lon', sa.Float(), nullable=False),
        sa.Column('association_score', sa.Float(), nullable=False),
        sa.Column('is_primary_suspect', sa.Boolean(), nullable=False, server_default=sa.text('false'), index=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_cand_vessel_assoc_cand', 'candidate_vessel_associations', ['candidate_id', 'spatial_distance_km'])


def downgrade() -> None:
    op.drop_table('candidate_vessel_associations')
    op.drop_table('vessel_positions')
    op.drop_table('vessels')

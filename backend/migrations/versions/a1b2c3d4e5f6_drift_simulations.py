"""Add drift_simulations table for Lagrangian oil-spill trajectory modelling (Phase 16).

Revision ID: a1b2c3d4e5f6
Revises: f8a23b45c678
Create Date: 2026-11-12 13:00:00.000000+00:00

Changes:
1. Creates drift_simulations table storing particle trajectory envelopes,
   weathering mass balances, and shoreline beaching risk assessments.
2. Completely additive and non-destructive to existing database baseline.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f8a23b45c678'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'drift_simulations',
        sa.Column('simulation_id', sa.String(length=64), primary_key=True),
        sa.Column('candidate_id', sa.String(length=64), sa.ForeignKey('sar_candidates.candidate_id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('origin_lat', sa.Float(), nullable=False),
        sa.Column('origin_lon', sa.Float(), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_hours', sa.Integer(), nullable=False, server_default='48'),
        sa.Column('oil_type', sa.String(length=64), nullable=False, server_default='Medium Crude'),
        sa.Column('spill_volume_m3', sa.Float(), nullable=False, server_default='50.0'),
        sa.Column('wind_speed_ms', sa.Float(), nullable=False),
        sa.Column('wind_direction_deg', sa.Float(), nullable=False),
        sa.Column('current_speed_ms', sa.Float(), nullable=False, server_default='0.20'),
        sa.Column('current_direction_deg', sa.Float(), nullable=False, server_default='90.0'),
        sa.Column('evaporated_pct', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('floating_pct', sa.Float(), nullable=False, server_default='100.0'),
        sa.Column('beached_pct', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('dispersed_pct', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('beaching_risk_level', sa.String(length=32), nullable=False, server_default='LOW'),
        sa.Column('time_to_shore_hours', sa.Float(), nullable=True),
        sa.Column('trajectory_geojson', sa.JSON(), nullable=True),
        sa.Column('mass_balance_timeline', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_drift_sim_candidate', 'drift_simulations', ['candidate_id', 'created_at'])


def downgrade() -> None:
    op.drop_table('drift_simulations')

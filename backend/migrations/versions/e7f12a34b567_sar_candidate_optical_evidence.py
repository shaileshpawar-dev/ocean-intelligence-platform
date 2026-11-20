"""Add sar_candidate_optical_evidence table for Sentinel-2 optical data.

Revision ID: e7f12a34b567
Revises: d4e1f7a83c29
Create Date: 2026-11-12 11:00:00.000000+00:00

Changes:
1. Creates sar_candidate_optical_evidence table storing collocated Sentinel-2 L2A
   imagery metadata, chip quality screening fractions (water, cloud, shadow),
   NDCI/NDTI environmental indicators, and local rendered product paths.
2. Completely additive and non-destructive to existing SAR candidate baseline.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f12a34b567'
down_revision: Union[str, None] = 'd4e1f7a83c29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sar_candidate_optical_evidence',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('candidate_id', sa.Integer(), sa.ForeignKey('sar_candidates.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scene_id', sa.String(length=128), nullable=False),
        sa.Column('platform', sa.String(length=32), nullable=False, server_default='sentinel-2'),
        sa.Column('acquisition_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('temporal_offset_hours', sa.Float(), nullable=False),
        sa.Column('temporal_window', sa.String(length=32), nullable=False, server_default='primary_3d'),
        sa.Column('scene_cloud_cover_pct', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('tile_id', sa.String(length=32), nullable=True),
        sa.Column('local_water_fraction', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('local_cloud_fraction', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('local_shadow_fraction', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('local_valid_pixel_fraction', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('mean_ndci', sa.Float(), nullable=True),
        sa.Column('p90_ndci', sa.Float(), nullable=True),
        sa.Column('mean_ndti', sa.Float(), nullable=True),
        sa.Column('mean_swir_ratio', sa.Float(), nullable=True),
        sa.Column('optical_quality_flag', sa.String(length=48), nullable=False),
        sa.Column('rgb_thumbnail_path', sa.String(length=256), nullable=True),
        sa.Column('false_color_path', sa.String(length=256), nullable=True),
        sa.Column('scl_mask_path', sa.String(length=256), nullable=True),
        sa.Column('ndci_map_path', sa.String(length=256), nullable=True),
        sa.Column('summary_json', sa.JSON(), nullable=True),
        sa.Column('processing_status', sa.String(length=32), nullable=False, server_default='completed'),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index('ix_sar_cand_opt_candidate_id', 'sar_candidate_optical_evidence', ['candidate_id'])
    op.create_index('ix_sar_cand_opt_scene_id', 'sar_candidate_optical_evidence', ['scene_id'])
    op.create_index('ix_sar_cand_opt_acq_time', 'sar_candidate_optical_evidence', ['acquisition_timestamp'])
    op.create_index('ix_sar_cand_opt_flag', 'sar_candidate_optical_evidence', ['optical_quality_flag'])
    op.create_index('ix_sar_cand_opt_status', 'sar_candidate_optical_evidence', ['processing_status'])
    op.create_index('ix_cand_opt_time', 'sar_candidate_optical_evidence', ['candidate_id', 'acquisition_timestamp'])
    op.create_index('ix_cand_opt_scene', 'sar_candidate_optical_evidence', ['candidate_id', 'scene_id'])


def downgrade() -> None:
    op.drop_index('ix_cand_opt_scene', table_name='sar_candidate_optical_evidence')
    op.drop_index('ix_cand_opt_time', table_name='sar_candidate_optical_evidence')
    op.drop_index('ix_sar_cand_opt_status', table_name='sar_candidate_optical_evidence')
    op.drop_index('ix_sar_cand_opt_flag', table_name='sar_candidate_optical_evidence')
    op.drop_index('ix_sar_cand_opt_acq_time', table_name='sar_candidate_optical_evidence')
    op.drop_index('ix_sar_cand_opt_scene_id', table_name='sar_candidate_optical_evidence')
    op.drop_index('ix_sar_cand_opt_candidate_id', table_name='sar_candidate_optical_evidence')
    op.drop_table('sar_candidate_optical_evidence')

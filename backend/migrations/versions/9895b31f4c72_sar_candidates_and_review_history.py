"""sar_candidates_and_review_history

Revision ID: 9895b31f4c72
Revises: a99e0a129f57
Create Date: 2026-11-03 11:46:36.162616+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '9895b31f4c72'
down_revision: str | None = 'a99e0a129f57'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create sar_candidates table
    op.create_table(
        'sar_candidates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('candidate_id', sa.String(length=64), nullable=False),
        sa.Column('image_name', sa.String(length=128), nullable=False),
        sa.Column('safe_scene', sa.String(length=256), nullable=True),
        sa.Column('subset', sa.String(length=16), nullable=False),
        sa.Column('cluster', sa.String(length=32), nullable=False),
        sa.Column('component_id', sa.Integer(), nullable=True),
        sa.Column('split', sa.String(length=64), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('is_coastal', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('acquisition_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('detector_name', sa.String(length=64), server_default='sar-oil-slick-v2.2', nullable=False),
        sa.Column('model_version', sa.String(length=64), server_default='2.2.0-experimental', nullable=False),
        sa.Column('raw_confidence', sa.Float(), nullable=False),
        sa.Column('confidence_is_calibrated', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('wind_speed_ms', sa.Float(), nullable=True),
        sa.Column('wind_direction_deg', sa.Float(), nullable=True),
        sa.Column('era5_source', sa.String(length=128), server_default='ECMWF ERA5 Reanalysis Archive', nullable=False),
        sa.Column('grid_latitude', sa.Float(), nullable=True),
        sa.Column('grid_longitude', sa.Float(), nullable=True),
        sa.Column('temporal_offset_minutes', sa.Float(), nullable=True),
        sa.Column('grid_distance_km', sa.Float(), nullable=True),
        sa.Column('quality_status', sa.String(length=48), server_default='reanalysis_available', nullable=False),
        sa.Column('environmental_warnings', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('screening_status', sa.String(length=48), nullable=False),
        sa.Column('retained_for_analyst_review', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('review_status', sa.String(length=48), server_default='awaiting_review', nullable=False),
        sa.Column('latest_review_decision', sa.String(length=48), nullable=True),
        sa.Column('latest_reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('latest_reviewer_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sar_candidates_candidate_id'), 'sar_candidates', ['candidate_id'], unique=True)
    op.create_index(op.f('ix_sar_candidates_image_name'), 'sar_candidates', ['image_name'], unique=False)
    op.create_index(op.f('ix_sar_candidates_safe_scene'), 'sar_candidates', ['safe_scene'], unique=False)
    op.create_index(op.f('ix_sar_candidates_subset'), 'sar_candidates', ['subset'], unique=False)
    op.create_index(op.f('ix_sar_candidates_cluster'), 'sar_candidates', ['cluster'], unique=False)
    op.create_index(op.f('ix_sar_candidates_component_id'), 'sar_candidates', ['component_id'], unique=False)
    op.create_index(op.f('ix_sar_candidates_split'), 'sar_candidates', ['split'], unique=False)
    op.create_index(op.f('ix_sar_candidates_latitude'), 'sar_candidates', ['latitude'], unique=False)
    op.create_index(op.f('ix_sar_candidates_longitude'), 'sar_candidates', ['longitude'], unique=False)
    op.create_index(op.f('ix_sar_candidates_is_coastal'), 'sar_candidates', ['is_coastal'], unique=False)
    op.create_index(op.f('ix_sar_candidates_acquisition_timestamp'), 'sar_candidates', ['acquisition_timestamp'], unique=False)
    op.create_index(op.f('ix_sar_candidates_model_version'), 'sar_candidates', ['model_version'], unique=False)
    op.create_index(op.f('ix_sar_candidates_screening_status'), 'sar_candidates', ['screening_status'], unique=False)
    op.create_index(op.f('ix_sar_candidates_retained_for_analyst_review'), 'sar_candidates', ['retained_for_analyst_review'], unique=False)
    op.create_index(op.f('ix_sar_candidates_review_status'), 'sar_candidates', ['review_status'], unique=False)
    op.create_index('ix_sar_cand_loc', 'sar_candidates', ['latitude', 'longitude'], unique=False)
    op.create_index('ix_sar_cand_screening_review', 'sar_candidates', ['screening_status', 'review_status'], unique=False)

    # 2. Create sar_candidate_reviews table
    op.create_table(
        'sar_candidate_reviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('review_id', sa.String(length=64), nullable=False),
        sa.Column('candidate_id', sa.Integer(), nullable=False),
        sa.Column('previous_status', sa.String(length=48), nullable=False),
        sa.Column('decision', sa.String(length=48), nullable=False),
        sa.Column('reviewer_id', sa.String(length=64), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('model_version', sa.String(length=64), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('evidence_references', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['candidate_id'], ['sar_candidates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sar_candidate_reviews_review_id'), 'sar_candidate_reviews', ['review_id'], unique=True)
    op.create_index(op.f('ix_sar_candidate_reviews_candidate_id'), 'sar_candidate_reviews', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_sar_candidate_reviews_decision'), 'sar_candidate_reviews', ['decision'], unique=False)
    op.create_index(op.f('ix_sar_candidate_reviews_reviewer_id'), 'sar_candidate_reviews', ['reviewer_id'], unique=False)
    op.create_index(op.f('ix_sar_candidate_reviews_reviewed_at'), 'sar_candidate_reviews', ['reviewed_at'], unique=False)
    op.create_index('ix_cand_rev_time', 'sar_candidate_reviews', ['candidate_id', 'reviewed_at'], unique=False)


def downgrade() -> None:
    op.drop_table('sar_candidate_reviews')
    op.drop_table('sar_candidates')

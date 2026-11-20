"""Harden review audit integrity (ON DELETE RESTRICT) and blind research ground truth.

Revision ID: d4e1f7a83c29
Revises: 9895b31f4c72
Create Date: 2026-11-04 15:45:00.000000+00:00

Changes:
1. Replaces ON DELETE CASCADE on sar_candidate_reviews with ON DELETE RESTRICT
   to prevent review history from disappearing if a candidate record is deleted.
2. Adds internal_sample_id and neutral_image_id to sar_candidates.
3. Blinds candidate_id (cand_s1_0001..) and image_name (patch_s1_0001.jpg)
   while preserving original provenance mappings internally in internal_sample_id.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e1f7a83c29'
down_revision: Union[str, None] = '9895b31f4c72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Foreign key hardening: replace CASCADE with RESTRICT
    op.drop_constraint(
        'sar_candidate_reviews_candidate_id_fkey',
        'sar_candidate_reviews',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'sar_candidate_reviews_candidate_id_fkey',
        'sar_candidate_reviews',
        'sar_candidates',
        ['candidate_id'],
        ['id'],
        ondelete='RESTRICT',
    )

    # 2. Add internal_sample_id and neutral_image_id columns
    op.add_column(
        'sar_candidates',
        sa.Column('internal_sample_id', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'sar_candidates',
        sa.Column('neutral_image_id', sa.String(length=128), nullable=True),
    )
    op.create_index(
        op.f('ix_sar_candidates_internal_sample_id'),
        'sar_candidates',
        ['internal_sample_id'],
        unique=False,
    )

    # 3. Data upgrade: preserve original candidate_id in internal_sample_id and assign neutral IDs
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE sar_candidates
        SET internal_sample_id = candidate_id;
    """))

    # For benchmark samples (not test acceptance samples), assign neutral cand_s1_XXXX IDs
    conn.execute(sa.text("""
        UPDATE sar_candidates
        SET 
            candidate_id = 'cand_s1_' || lpad(id::text, 4, '0'),
            neutral_image_id = 'patch_s1_' || lpad(id::text, 4, '0') || '.jpg'
        WHERE split != 'test_acceptance_phase13_3';
    """))

    # For test acceptance records, assign neutral image IDs
    conn.execute(sa.text("""
        UPDATE sar_candidates
        SET neutral_image_id = 'patch_' || substr(candidate_id, 6) || '.jpg'
        WHERE split = 'test_acceptance_phase13_3';
    """))


def downgrade() -> None:
    # 1. Restore candidate_id from internal_sample_id
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE sar_candidates
        SET candidate_id = internal_sample_id
        WHERE internal_sample_id IS NOT NULL;
    """))

    # 2. Drop columns and indexes
    op.drop_index(op.f('ix_sar_candidates_internal_sample_id'), table_name='sar_candidates')
    op.drop_column('sar_candidates', 'neutral_image_id')
    op.drop_column('sar_candidates', 'internal_sample_id')

    # 3. Revert foreign key to CASCADE
    op.drop_constraint(
        'sar_candidate_reviews_candidate_id_fkey',
        'sar_candidate_reviews',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'sar_candidate_reviews_candidate_id_fkey',
        'sar_candidate_reviews',
        'sar_candidates',
        ['candidate_id'],
        ['id'],
        ondelete='CASCADE',
    )

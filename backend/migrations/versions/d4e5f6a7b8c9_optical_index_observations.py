"""Store real Sentinel-2 water-quality indices.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-21 11:30:00.000000+00:00

A new table, nothing altered. These rows are measurements from Copernicus
scenes and are kept out of ``satellite_observations``, whose other rows come
from the synthetic provider -- a real index and a simulated one should not
differ only by the value of a column somebody has to remember to read.

The unique constraint on (region, date) makes the fetch idempotent: re-running
it over a window already stored inserts nothing.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "optical_index_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("ndci_mean", sa.Float(), nullable=False),
        sa.Column("ndci_p50", sa.Float(), nullable=False),
        sa.Column("ndti_mean", sa.Float(), nullable=False),
        sa.Column("ndti_p50", sa.Float(), nullable=False),
        sa.Column("fdi_mean", sa.Float(), nullable=False),
        sa.Column("fdi_p90", sa.Float(), nullable=False),
        sa.Column("water_pixels", sa.Integer(), nullable=False),
        sa.Column("total_pixels", sa.Integer(), nullable=False),
        sa.Column("max_cloud_pct", sa.Integer(), nullable=False),
        sa.Column("evidence_level", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=160), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["region_id"], ["regions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("region_id", "observed_on", name="uq_optical_cell_day"),
    )
    op.create_index(
        "ix_optical_index_observations_region_id",
        "optical_index_observations",
        ["region_id"],
    )
    op.create_index(
        "ix_optical_index_observations_observed_on",
        "optical_index_observations",
        ["observed_on"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_optical_index_observations_observed_on",
        table_name="optical_index_observations",
    )
    op.drop_index(
        "ix_optical_index_observations_region_id",
        table_name="optical_index_observations",
    )
    op.drop_table("optical_index_observations")

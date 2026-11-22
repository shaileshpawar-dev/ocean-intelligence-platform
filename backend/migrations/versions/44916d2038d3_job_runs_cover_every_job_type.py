"""Job runs cover every job type

The table recorded ingestion only, so a geometry import, a satellite pass or a
RAG reindex left no trace of whether it ran or what it did. ``job_type`` says
which kind of job a row records; existing rows are ingestion, which is what
they were. ``records_skipped`` separates "deliberately not processed" -- an
unchanged resource, a lake with no cloud-free scene -- from "rejected", which
means unusable.

Revision ID: 44916d2038d3
Revises: d9eb2c9be3fb
Create Date: 2026-09-26 14:19:28.011969+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "44916d2038d3"
down_revision: str | None = "d9eb2c9be3fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "job_type", sa.String(length=32), server_default="ingestion", nullable=False
        ),
    )
    # server_default, or the NOT NULL fails on every existing row.
    op.add_column(
        "ingestion_runs",
        sa.Column("records_skipped", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index(
        op.f("ix_ingestion_runs_job_type"), "ingestion_runs", ["job_type"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ingestion_runs_job_type"), table_name="ingestion_runs")
    op.drop_column("ingestion_runs", "records_skipped")
    op.drop_column("ingestion_runs", "job_type")

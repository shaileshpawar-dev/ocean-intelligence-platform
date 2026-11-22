"""Station keeps the source drainage columns

The River, Basin and Tributary columns as the provider published them. They
are provenance, not identity -- CWC"s River column repeats the Basin name for
most rows, so the water body has to be read from the Tributary column -- and
keeping them means that reading can be revisited without re-fetching four
million observations.

Revision ID: d9eb2c9be3fb
Revises: e5c81b6a9f30
Create Date: 2026-09-25 22:25:12.494743+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9eb2c9be3fb"
down_revision: str | None = "e5c81b6a9f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "monitoring_stations",
        sa.Column("source_river", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "monitoring_stations",
        sa.Column("source_basin", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "monitoring_stations",
        sa.Column("source_tributary", sa.String(length=160), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("monitoring_stations", "source_tributary")
    op.drop_column("monitoring_stations", "source_basin")
    op.drop_column("monitoring_stations", "source_river")

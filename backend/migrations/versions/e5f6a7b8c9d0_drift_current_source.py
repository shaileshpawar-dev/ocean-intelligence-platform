"""Record where a drift simulation's current field came from.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-21 11:25:00.000000+00:00

One nullable column. The drift engine defaults to 0.22 m/s due east when no
current is supplied, which is a placeholder; with Copernicus Marine wired in,
most runs now use a modelled current for the actual location. Those two cases
produce visually identical tracks and must not be indistinguishable in the
record, so the source is stored alongside the values.

Existing rows keep NULL: they were run before the distinction existed, and
backfilling them with either answer would be a guess.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "drift_simulations",
        sa.Column("current_source", sa.String(length=160), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("drift_simulations", "current_source")

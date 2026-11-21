"""Cache the optional AI summary on reports.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-21 10:40:00.000000+00:00

Five nullable columns on ``reports``. Additive and reversible; no existing
column is touched and no row is rewritten.

The AI text is kept apart from ``summary`` on purpose. ``summary`` is rendered
from computed values and is what the report falls back to whenever a model is
absent, slow, failing, or caught writing a figure that is not in its evidence.
Storing the two in one column would make those two kinds of prose
indistinguishable after the fact.

``ai_check`` records the number check that permitted the text to be stored.
Nothing is written unless that check passed, so it is a record of what was
verified rather than a caveat for the reader.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("ai_narrative", sa.Text(), nullable=True))
    op.add_column("reports", sa.Column("ai_model", sa.String(length=128), nullable=True))
    op.add_column(
        "reports", sa.Column("ai_fingerprint", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "reports",
        sa.Column("ai_generated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("reports", sa.Column("ai_check", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "ai_check")
    op.drop_column("reports", "ai_generated_at")
    op.drop_column("reports", "ai_fingerprint")
    op.drop_column("reports", "ai_model")
    op.drop_column("reports", "ai_narrative")

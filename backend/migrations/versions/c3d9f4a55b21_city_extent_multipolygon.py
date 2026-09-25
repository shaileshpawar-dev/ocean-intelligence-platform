"""City extent is a MultiPolygon

A city is defined here as a set of whole districts. Two districts that do not
touch (or touch only at a point) union to a MultiPolygon, so the column has to
allow one; a Polygon column rejected exactly the cities the definition exists
for.

Revision ID: c3d9f4a55b21
Revises: b1a7c0d2e3f4
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c3d9f4a55b21"
down_revision: str | None = "b1a7c0d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE cities ALTER COLUMN extent_geom TYPE geometry(MultiPolygon, 4326) "
        "USING ST_Multi(extent_geom)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE cities ALTER COLUMN extent_geom TYPE geometry(Polygon, 4326) "
        "USING ST_GeometryN(extent_geom, 1)"
    )

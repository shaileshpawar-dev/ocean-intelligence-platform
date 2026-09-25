"""Observation uniqueness includes the source

Two agencies may sample the same station, parameter and moment. Keying an
observation by (station, parameter, time) alone let one source's row block
the other's, which is exactly the silent overwrite the multi-source design
exists to prevent.

Revision ID: e5c81b6a9f30
Revises: beba5f44270e
Create Date: 2026-09-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e5c81b6a9f30"
down_revision: str | None = "beba5f44270e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "uq_observation_station_param_time"
NEW = "uq_observation_source_station_param_time"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f"ALTER TABLE water_quality_observations DROP CONSTRAINT IF EXISTS {OLD}"
        )
        op.execute(
            "ALTER TABLE water_quality_observations ADD CONSTRAINT "
            f"{NEW} UNIQUE (source_id, station_id, parameter, observed_at)"
        )
        return
    with op.batch_alter_table("water_quality_observations") as batch:
        batch.drop_constraint(OLD, type_="unique")
        batch.create_unique_constraint(
            NEW, ["source_id", "station_id", "parameter", "observed_at"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f"ALTER TABLE water_quality_observations DROP CONSTRAINT IF EXISTS {NEW}"
        )
        op.execute(
            "ALTER TABLE water_quality_observations ADD CONSTRAINT "
            f"{OLD} UNIQUE (station_id, parameter, observed_at)"
        )
        return
    with op.batch_alter_table("water_quality_observations") as batch:
        batch.drop_constraint(NEW, type_="unique")
        batch.create_unique_constraint(OLD, ["station_id", "parameter", "observed_at"])

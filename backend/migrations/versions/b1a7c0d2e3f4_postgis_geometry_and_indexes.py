"""PostGIS geometry columns, spatial indexes and query indexes

Geometry is stored twice on purpose:

* the GeoJSON text column stays as the provenance record of exactly what the
  source returned, and is what SQLite development mode reads;
* a PostGIS ``geometry(...,4326)`` column is derived from it and is what
  production queries use, with a GIST index.

``cli db sync-geometry`` fills the geometry columns; it is idempotent and can
be re-run after any import.

Revision ID: b1a7c0d2e3f4
Revises: 4442e41c4ca0
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b1a7c0d2e3f4"
down_revision: str | None = "4442e41c4ca0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, geometry type)
GEOMETRY_COLUMNS = [
    ("water_body_geometries", "geom", "Geometry"),
    ("admin_boundaries", "geom", "MultiPolygon"),
    ("monitoring_stations", "geom", "Point"),
    ("water_bodies", "centroid_geom", "Point"),
    ("cities", "extent_geom", "Polygon"),
    ("water_images", "footprint_geom", "Polygon"),
]

# Indexes that every list, map and trend query depends on. SQLite tolerated
# their absence at Phase 1 volumes; 582k observations on PostgreSQL do not.
INDEXES = [
    (
        "ix_obs_body_param_date",
        "water_quality_observations",
        "water_body_id, parameter, observed_at DESC",
    ),
    ("ix_obs_station_date", "water_quality_observations", "station_id, observed_at DESC"),
    ("ix_obs_source_date", "water_quality_observations", "source_id, observed_at DESC"),
    ("ix_bodies_state_type", "water_bodies", "state_id, water_type"),
    ("ix_bodies_status", "water_bodies", "cached_historical_status"),
    ("ix_bodies_normalized", "water_bodies", "normalized_name"),
    ("ix_bodies_geometry_status", "water_bodies", "geometry_status"),
    ("ix_stations_body", "monitoring_stations", "water_body_id"),
    ("ix_stations_state_district", "monitoring_stations", "state_id, district_id"),
    ("ix_boundaries_level_name", "admin_boundaries", "level, normalized_name"),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite keeps the GeoJSON columns and the Python geometry helpers.
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    for table, column, geom_type in GEOMETRY_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} "
            f"geometry({geom_type}, 4326)"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_{column}_gist "
            f"ON {table} USING GIST ({column})"
        )
    for name, table, columns in INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for name, _table, _columns in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    for table, column, _geom_type in GEOMETRY_COLUMNS:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_{column}_gist")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")

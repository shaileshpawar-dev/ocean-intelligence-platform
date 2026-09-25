"""Copy a SQLite database into PostgreSQL, and derive PostGIS geometry.

Phase 3 keeps SQLite for development and makes PostgreSQL the production
target. The bridge between them is this module: it moves the rows that were
built by the (slow, rate-limited) ingestion and geometry jobs into the
database a deployed container will read, so that container never has to
rebuild them.

Two steps, both idempotent and both runnable from the CLI:

``db copy-from-sqlite``
    Copies every application table in dependency order, in chunks, then
    resets the identity sequences so new inserts do not collide.

``db sync-geometry``
    Fills the PostGIS ``geometry`` columns from the stored GeoJSON and
    lat/lon columns. Runs on PostgreSQL only; on SQLite it is a no-op,
    because there the GeoJSON *is* the geometry.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import Engine, Table, create_engine, delete, func, insert, select, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Base

logger = get_logger(__name__)

CHUNK = 5_000

# Tables PostGIS itself owns; never touched by a copy.
SYSTEM_TABLES = {"spatial_ref_sys"}


def _app_tables() -> list[Table]:
    return [t for t in Base.metadata.sorted_tables if t.name not in SYSTEM_TABLES]


def _rows(source: Engine, table: Table) -> Iterator[list[dict[str, Any]]]:
    with source.connect().execution_options(stream_results=True) as conn:
        result = conn.execute(select(table))
        while batch := result.fetchmany(CHUNK):
            yield [dict(row._mapping) for row in batch]


def copy_sqlite_to_postgres(
    sqlite_url: str, target: Engine, *, truncate: bool = True
) -> dict[str, int]:
    """Copy every application table from ``sqlite_url`` into ``target``.

    ``truncate`` empties the target tables first, which makes the copy
    repeatable: running it twice gives the same database, not double rows.
    """
    if target.dialect.name == "sqlite":
        raise ValueError("target must not be SQLite; point DATABASE_URL at PostgreSQL")
    source = create_engine(sqlite_url)
    counts: dict[str, int] = {}
    tables = _app_tables()

    with target.begin() as conn:
        if truncate:
            for table in reversed(tables):
                conn.execute(delete(table))

    for table in tables:
        moved = 0
        for batch in _rows(source, table):
            if not batch:
                continue
            with target.begin() as conn:
                conn.execute(insert(table), batch)
            moved += len(batch)
        counts[table.name] = moved
        if moved:
            logger.info("table_copied", extra={"table": table.name, "rows": moved})

    _reset_sequences(target, tables)
    source.dispose()
    return counts


def _reset_sequences(target: Engine, tables: list[Table]) -> None:
    """Move each identity sequence past the copied primary keys."""
    if target.dialect.name != "postgresql":
        return
    with target.begin() as conn:
        for table in tables:
            pk = list(table.primary_key.columns)
            if len(pk) != 1 or not isinstance(pk[0].type.python_type, type):
                continue
            column = pk[0]
            if column.type.python_type is not int:
                continue
            seq = conn.execute(
                text("SELECT pg_get_serial_sequence(:t, :c)"),
                {"t": table.name, "c": column.name},
            ).scalar()
            if not seq:
                continue
            highest = conn.execute(select(func.max(column))).scalar()
            conn.execute(
                text("SELECT setval(:seq, :value, true)"),
                {"seq": seq, "value": int(highest or 0) + 1},
            )


# ---------------------------------------------------------------------------
# GeoJSON -> PostGIS
# ---------------------------------------------------------------------------
SYNC_STATEMENTS: list[tuple[str, str]] = [
    (
        "water_body_geometries",
        """
        UPDATE water_body_geometries
           SET geom = ST_SetSRID(ST_GeomFromGeoJSON(geojson), 4326)
         WHERE geojson IS NOT NULL

        """,
    ),
    (
        "admin_boundaries",
        """
        UPDATE admin_boundaries
           SET geom = ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(geojson), 4326))
         WHERE geojson IS NOT NULL

        """,
    ),
    (
        "monitoring_stations",
        """
        UPDATE monitoring_stations
           SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
         WHERE longitude IS NOT NULL AND latitude IS NOT NULL

        """,
    ),
    (
        "water_bodies",
        """
        UPDATE water_bodies
           SET centroid_geom = ST_SetSRID(ST_MakePoint(centroid_lon, centroid_lat), 4326)
         WHERE centroid_lon IS NOT NULL AND centroid_lat IS NOT NULL

        """,
    ),
    (
        "cities",
        """
        UPDATE cities
           SET extent_geom = ST_Multi(
                   ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
               )
         WHERE min_lon IS NOT NULL

        """,
    ),
    (
        "water_images",
        """
        UPDATE water_images
           SET footprint_geom = ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
         WHERE min_lon IS NOT NULL

        """,
    ),
]


def sync_geometry(db: Session) -> dict[str, int]:
    """Derive PostGIS geometry from stored GeoJSON / coordinates.

    Always recomputed rather than filled only where empty: an import that
    replaces a water body's GeoJSON must not leave the previous derived
    geometry in place. Returns rows updated per table; a no-op on SQLite.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return {}
    updated: dict[str, int] = {}
    for table, statement in SYNC_STATEMENTS:
        result = db.execute(text(statement))
        updated[table] = result.rowcount or 0
    db.commit()
    logger.info("geometry_synced", extra=updated)
    return updated


def city_extents_from_districts(db: Session) -> int:
    """Replace city bounding boxes with the union of their district polygons.

    A bounding box is a rectangle around a city; the union of the districts
    is the city as defined. Only possible on PostGIS, and only where the
    district boundaries were imported.

    The polygons are repaired with ``ST_MakeValid`` first: a few simplified
    geoBoundaries districts are not OGC-valid, and GEOS refuses to union
    those. ``cli geometry-qa`` reports them rather than hiding the repair.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return 0
    result = db.execute(
        text(
            """
            WITH city_district AS (
                SELECT c.id AS city_id, ST_Union(ST_MakeValid(b.geom)) AS shape
                  FROM cities c
                  JOIN districts d ON d.id = ANY (
                       SELECT jsonb_array_elements_text(c.district_ids::jsonb)::int
                  )
                  JOIN admin_boundaries b ON b.district_id = d.id AND b.level = 'district'
                 GROUP BY c.id
            )
            UPDATE cities
               SET extent_geom = ST_Multi(city_district.shape)
              FROM city_district
             WHERE cities.id = city_district.city_id
            """
        )
    )
    db.commit()
    return result.rowcount or 0

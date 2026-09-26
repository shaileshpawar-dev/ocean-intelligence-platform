"""Spatial queries, in SQL where PostGIS is available.

Every function here has the same contract on both backends. On PostgreSQL the
work happens in the database against a GIST index; on SQLite the caller keeps
using the Python geometry helpers in :mod:`app.water.geo`. The functions
return ``None`` when spatial SQL is unavailable, which is the caller's signal
to take its existing path -- so development stays dependency-free and
production stops shipping thousands of rows to Python to be filtered.

Distances use ``geography``, i.e. metres on the spheroid, not degrees.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.dbinfo import spatial_sql_available

BBox = tuple[float, float, float, float]  # (min_lat, min_lon, max_lat, max_lon)


def available(db: Session) -> bool:
    """Whether *this session's* database can run PostGIS SQL.

    The session's own bind is probed rather than the application engine: a
    test or an offline job can legitimately hold a session on a different
    database from the one the web app serves.
    """
    bind = db.bind if db.bind is not None else db.get_bind()
    engine = getattr(bind, "engine", bind)
    return (
        engine is not None
        and engine.dialect.name == "postgresql"
        and spatial_sql_available(engine)
    )


def bodies_within_radius(
    db: Session,
    latitude: float,
    longitude: float,
    radius_km: float,
    *,
    water_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[tuple[int, float]] | None:
    """(water_body_id, distance_km) within a true circle, nearest first.

    ``centroid_geom`` is derived by the ``db sync-geometry`` job, so a body
    ingested since the last run has none. The lat/lon columns are written at
    ingest and are the same position, so they stand in for it: without that
    fallback a fresh staging stack answered "nothing near here" for water
    bodies it was already serving, which the smoke test caught. The indexed
    branch is kept separate from the fallback so the GIST index still does the
    work for every row that has the derived column.
    """
    if not available(db):
        return None
    rows = db.execute(
        text(
            """
            SELECT id,
                   ST_Distance(
                       COALESCE(
                           centroid_geom,
                           ST_SetSRID(ST_MakePoint(centroid_lon, centroid_lat), 4326)
                       )::geography,
                       ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                   ) / 1000.0 AS km
              FROM water_bodies
             WHERE (
                     (
                       centroid_geom IS NOT NULL
                       AND ST_DWithin(
                               centroid_geom::geography,
                               ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                               :metres
                           )
                     )
                     OR (
                       centroid_geom IS NULL
                       AND centroid_lat IS NOT NULL
                       AND centroid_lon IS NOT NULL
                       AND ST_DWithin(
                               ST_SetSRID(
                                   ST_MakePoint(centroid_lon, centroid_lat), 4326
                               )::geography,
                               ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                               :metres
                           )
                     )
                   )
               AND (
                     CAST(:water_type AS text) IS NULL
                     OR water_type = CAST(:water_type AS text)
                   )
               AND (
                     CAST(:status AS text) IS NULL
                     OR cached_status = CAST(:status AS text)
                   )
             ORDER BY km
             LIMIT :limit
            """
        ),
        {
            "lat": latitude,
            "lon": longitude,
            "metres": radius_km * 1000.0,
            "water_type": water_type,
            "status": status,
            "limit": limit,
        },
    ).all()
    return [(int(r[0]), round(float(r[1]), 2)) for r in rows]


def bodies_near_city(
    db: Session,
    city_id: int,
    radius_km: float,
    *,
    limit: int = 500,
) -> list[tuple[int, float]] | None:
    """(water_body_id, distance_km) from a city's own extent, not a point.

    Distance is measured to the city polygon, so everything inside the city
    is at 0 km, which is what "in Mumbai" means.

    ``centroid_geom`` falls back to the lat/lon written at ingest, so a water
    body added since the last ``db sync-geometry`` is still found.
    """
    if not available(db):
        return None
    rows = db.execute(
        text(
            """
            SELECT w.id,
                   ST_Distance(
                       COALESCE(
                           w.centroid_geom,
                           ST_SetSRID(ST_MakePoint(w.centroid_lon, w.centroid_lat), 4326)
                       )::geography,
                       c.extent_geom::geography
                   ) / 1000.0 AS km
              FROM water_bodies w
              JOIN cities c ON c.id = :city_id
             WHERE COALESCE(
                       w.centroid_geom,
                       ST_SetSRID(ST_MakePoint(w.centroid_lon, w.centroid_lat), 4326)
                   ) IS NOT NULL
               AND c.extent_geom IS NOT NULL
               AND ST_DWithin(
                       COALESCE(
                           w.centroid_geom,
                           ST_SetSRID(ST_MakePoint(w.centroid_lon, w.centroid_lat), 4326)
                       )::geography,
                       c.extent_geom::geography,
                       :metres
                   )
             ORDER BY km
             LIMIT :limit
            """
        ),
        {"city_id": city_id, "metres": radius_km * 1000.0, "limit": limit},
    ).all()
    return [(int(r[0]), round(float(r[1]), 2)) for r in rows]


def stations_near_city(
    db: Session, city_id: int, radius_km: float, *, limit: int = 200
) -> list[tuple[int, float]] | None:
    """(station_id, distance_km) from a city's extent, nearest first.

    ``geom`` falls back to the lat/lon written at ingest, so a station added
    since the last ``db sync-geometry`` is still found.
    """
    if not available(db):
        return None
    rows = db.execute(
        text(
            """
            SELECT s.id,
                   ST_Distance(
                       COALESCE(
                           s.geom,
                           ST_SetSRID(ST_MakePoint(s.longitude, s.latitude), 4326)
                       )::geography,
                       c.extent_geom::geography
                   ) / 1000.0 AS km
              FROM monitoring_stations s
              JOIN cities c ON c.id = :city_id
             WHERE COALESCE(
                       s.geom,
                       ST_SetSRID(ST_MakePoint(s.longitude, s.latitude), 4326)
                   ) IS NOT NULL
               AND c.extent_geom IS NOT NULL
               AND ST_DWithin(
                       COALESCE(
                           s.geom,
                           ST_SetSRID(ST_MakePoint(s.longitude, s.latitude), 4326)
                       )::geography,
                       c.extent_geom::geography,
                       :metres
                   )
             ORDER BY km
             LIMIT :limit
            """
        ),
        {"city_id": city_id, "metres": radius_km * 1000.0, "limit": limit},
    ).all()
    return [(int(r[0]), round(float(r[1]), 2)) for r in rows]


def station_clusters(
    db: Session, bbox: BBox | None, cell_degrees: float, *, state_code: str | None = None
) -> list[dict] | None:
    """Stations grouped on a grid, aggregated in SQL.

    ``ST_SnapToGrid`` does the grouping the Python path did by hand, but
    without sending every station to the application first.
    """
    if not available(db):
        return None
    rows = db.execute(
        text(
            """
            SELECT COUNT(*)                       AS n,
                   AVG(s.latitude)                AS lat,
                   AVG(s.longitude)               AS lon,
                   MIN(s.id)                      AS one_id,
                   MIN(s.name)                    AS one_name,
                   MAX(s.latest_observed_at)      AS latest,
                   ARRAY_REMOVE(
                       ARRAY_AGG(DISTINCT w.cached_historical_status), NULL
                   )                              AS statuses
              FROM monitoring_stations s
              LEFT JOIN water_bodies w ON w.id = s.water_body_id
              LEFT JOIN states st ON st.id = s.state_id
             WHERE s.geom IS NOT NULL
               AND s.geo_quality <> 'missing'
               AND (
                     CAST(:bbox_absent AS boolean)
                     OR s.geom && ST_MakeEnvelope(
                            :min_lon, :min_lat, :max_lon, :max_lat, 4326
                        )
                   )
               AND (
                     CAST(:state_code AS text) IS NULL
                     OR UPPER(st.code) = UPPER(CAST(:state_code AS text))
                   )
             GROUP BY ST_SnapToGrid(s.geom, :cell, :cell)
            """
        ),
        {
            "bbox_absent": bbox is None,
            "min_lat": bbox[0] if bbox else 0,
            "min_lon": bbox[1] if bbox else 0,
            "max_lat": bbox[2] if bbox else 0,
            "max_lon": bbox[3] if bbox else 0,
            "state_code": state_code,
            "cell": cell_degrees,
        },
    ).all()
    return [
        {
            "count": int(r.n),
            "latitude": float(r.lat),
            "longitude": float(r.lon),
            "station_id": int(r.one_id),
            "station_name": r.one_name,
            "latest_observed_at": r.latest,
            "statuses": list(r.statuses or []),
        }
        for r in rows
    ]


def state_containing(db: Session, latitude: float, longitude: float) -> str | None:
    """The state code whose boundary contains a point, by ST_Contains."""
    if not available(db):
        return None
    return db.execute(
        text(
            """
            SELECT st.code
              FROM admin_boundaries b
              JOIN states st ON st.id = b.state_id
             WHERE b.level = 'state'
               AND ST_Contains(b.geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
             LIMIT 1
            """
        ),
        {"lat": latitude, "lon": longitude},
    ).scalar_one_or_none()


def geometry_ids_in_bbox(
    db: Session,
    bbox: BBox,
    *,
    water_type: str | None = None,
    status: str | None = None,
    state_code: str | None = None,
    limit: int = 800,
) -> list[int] | None:
    """Water-body ids whose stored geometry intersects the viewport."""
    if not available(db):
        return None
    rows = db.execute(
        text(
            """
            SELECT g.water_body_id
              FROM water_body_geometries g
              JOIN water_bodies w ON w.id = g.water_body_id
              LEFT JOIN states st ON st.id = w.state_id
             WHERE g.geom && ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
               AND (
                     CAST(:water_type AS text) IS NULL
                     OR w.water_type = CAST(:water_type AS text)
                   )
               AND (
                     CAST(:status AS text) IS NULL
                     OR w.cached_historical_status = CAST(:status AS text)
                   )
               AND (
                     CAST(:state_code AS text) IS NULL
                     OR UPPER(st.code) = UPPER(CAST(:state_code AS text))
                   )
             ORDER BY w.observation_count DESC
             LIMIT :limit
            """
        ),
        {
            "min_lat": bbox[0],
            "min_lon": bbox[1],
            "max_lat": bbox[2],
            "max_lon": bbox[3],
            "water_type": water_type,
            "status": status,
            "state_code": state_code,
            "limit": limit,
        },
    ).all()
    return [int(r[0]) for r in rows]


def simplified_geometry(
    db: Session, water_body_id: int, tolerance_deg: float, places: int = 5
) -> str | None:
    """Server-side simplified GeoJSON for one water body, or ``None``."""
    if not available(db):
        return None
    return db.execute(
        text(
            """
            SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, :tol), :places)
              FROM water_body_geometries
             WHERE water_body_id = :id AND geom IS NOT NULL
             LIMIT 1
            """
        ),
        {"id": water_body_id, "tol": max(tolerance_deg, 0.0), "places": places},
    ).scalar_one_or_none()


def simplified_geometries(
    db: Session,
    water_body_ids: Sequence[int],
    tolerance_deg: float,
    places: int = 5,
) -> dict[int, str]:
    """Simplified GeoJSON for many water bodies, in one query.

    This is what the map's geometry layer draws. Simplifying in the database
    means a national request carries the vertices the client will actually
    plot instead of every vertex OpenStreetMap holds, and no full shape is
    parsed in Python on the way.
    """
    if not available(db) or not water_body_ids:
        return {}
    rows = db.execute(
        text(
            """
            SELECT water_body_id,
                   ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, :tol), :places)
                       AS geojson
              FROM water_body_geometries
             WHERE geom IS NOT NULL
               AND water_body_id = ANY(:ids)
            """
        ),
        {
            "tol": max(tolerance_deg, 0.0),
            "places": places,
            "ids": list(water_body_ids),
        },
    ).all()
    return {row.water_body_id: row.geojson for row in rows if row.geojson}


def station_distance_to_geometry(
    db: Session, station_id: int, water_body_id: int
) -> float | None:
    """Metres from a station to its water body's geometry."""
    if not available(db):
        return None
    return db.execute(
        text(
            """
            SELECT ST_Distance(s.geom::geography, g.geom::geography)
              FROM monitoring_stations s, water_body_geometries g
             WHERE s.id = :station_id AND g.water_body_id = :body_id
             LIMIT 1
            """
        ),
        {"station_id": station_id, "body_id": water_body_id},
    ).scalar_one_or_none()

# PostgreSQL / PostGIS migration plan

The water domain runs on SQLite locally. The schema was written so moving to
PostgreSQL + PostGIS is a storage change, not a redesign. This is the plan;
it has **not** been executed.

## What is already portable

- SQLAlchemy 2.0 models with no SQLite-specific types. JSON columns map to
  `JSONB`; timestamps are timezone-aware.
- `DATABASE_URL` selects the engine (`backend/app/core/config.py`).
- Geometry is stored as GeoJSON text plus explicit `min_/max_lat/lon`
  columns, which every viewport query filters on. Those queries work
  unchanged on PostgreSQL with a B-tree index; PostGIS makes them faster and
  exact.

## Steps

1. **Provision** PostgreSQL 16 + PostGIS 3.4 (`CREATE EXTENSION postgis;`).
2. **Add geometry columns** alongside the GeoJSON (keep GeoJSON as the
   provenance record of what the source returned):
   - `water_body_geometries.geom geometry(Geometry, 4326)`
   - `admin_boundaries.geom geometry(MultiPolygon, 4326)`
   - `monitoring_stations.geom geometry(Point, 4326)`
   - `water_bodies.centroid geometry(Point, 4326)`
   - `cities.extent geometry(Polygon, 4326)` (from the district union, not the bbox)
   Populate with `ST_SetSRID(ST_GeomFromGeoJSON(geojson), 4326)` and
   `ST_MakePoint(longitude, latitude)`.
3. **Indexes**: `GIST` on every `geom`; B-tree on `state_id`, `water_type`,
   `cached_historical_status`, `observed_at`, `(water_body_id, parameter,
   observed_at)`.
4. **Introduce Alembic.** The current `init_db()` uses `create_all`, which
   does not alter existing tables. The first revision is the current schema;
   the second adds the geometry columns.
5. **Copy data** with a one-off script reading SQLite through SQLAlchemy and
   bulk-inserting (`COPY` via `psycopg`). 582k observations copy in minutes.
6. **Swap Python geometry for SQL where it pays**, keeping `app/water/geo.py`
   as the SQLite fallback:

   | Python (`geo.py` / services) | PostGIS |
   |---|---|
   | bbox prefilter + `haversine_km` in `water_bodies_near` | `ST_DWithin(geom::geography, point::geography, r)` |
   | `contains_point` (district parent vote) | `ST_Contains` / `ST_Area(ST_Intersection)` |
   | `distance_km` (station ↔ geometry) | `ST_Distance(geography)` |
   | `clip_lines` (monitored reaches) | `ST_Intersection(geom, ST_Union(windows))` |
   | `simplify` + `round_geometry` (display) | `ST_SimplifyPreserveTopology` + `ST_AsGeoJSON(geom, 5)`, or vector tiles via `ST_AsMVT` |
   | city bbox distance | `ST_Distance` to the true district union |
7. **Vector tiles (optional)**: serve boundaries and water geometry as MVT
   from PostGIS (`ST_AsMVT`) instead of GeoJSON once feature counts grow.
8. **Verify** with the existing test suite pointed at a PostGIS test database
   plus parity tests comparing Python and SQL results for distances and
   containment on the real data.

## Risks

- SQLite stores naive datetimes; the code normalises to UTC on read
  (`_as_utc`). PostgreSQL `timestamptz` removes that need; keep the helper
  until every row is migrated.
- The status cache columns (`cached_status`, `cached_historical_status`) must
  be refreshed after migration (`cli refresh-status`).

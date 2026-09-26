# PostgreSQL / PostGIS migration plan

**Status: executed in Phase 3.** PostgreSQL 16 + PostGIS 3.4 is the
production target; SQLite remains the development and test backend. This
document is now both the record of what was done and the runbook for doing
it again in a new environment.

## What is already portable

- SQLAlchemy 2.0 models with no SQLite-specific types. JSON columns map to
  `JSONB`; timestamps are timezone-aware.
- `DATABASE_URL` selects the engine (`backend/app/core/config.py`).
- Geometry is stored as GeoJSON text plus explicit `min_/max_lat/lon`
  columns, which every viewport query filters on. Those queries work
  unchanged on PostgreSQL with a B-tree index; PostGIS makes them faster and
  exact.

## What was done

| Step | Outcome |
|---|---|
| PostGIS provisioned | `postgis/postgis:16-3.4` locally; RDS + PostGIS in production |
| Alembic introduced | `4442e41c4ca0` initial schema, then PostGIS geometry, city extent, source characteristics, observation key |
| Geometry columns | `water_body_geometries.geom`, `admin_boundaries.geom`, `monitoring_stations.geom`, `water_bodies.centroid_geom`, `cities.extent_geom`, `water_images.footprint_geom`, each with a GIST index |
| Query indexes | observation (body, parameter, date), (station, date), (source, date); water-body state/type/status/name; station body and state/district; boundary level/name |
| Data moved | `cli db copy-from-sqlite` — the whole database in ~2.5 min |
| Geometry derived | `cli db sync-geometry` — GeoJSON kept as the provenance record, PostGIS derived from it |
| Queries moved to SQL | `app/services/spatial.py`: radius, city distance, viewport, clustering, containment, station-to-geometry distance |
| Verified | `tests/test_postgis.py` builds a throwaway database, runs the migrations and exercises every geometry type, the GIST indexes and each spatial operation |

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
   as the SQLite fallback (done — `app/services/spatial.py` returns ``None``
   when PostGIS is absent and the caller takes the Python path):

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

## `create_all` is not the schema

The six geometry columns are added by hand-written migrations, not by the
SQLAlchemy models:

| Table | Column | Type |
|---|---|---|
| `water_bodies` | `centroid_geom` | Point |
| `water_body_geometries` | `geom` | Geometry |
| `monitoring_stations` | `geom` | Point |
| `admin_boundaries` | `geom` | MultiPolygon |
| `cities` | `extent_geom` | MultiPolygon |
| `water_images` | `footprint_geom` | Polygon |

They are deliberately outside the models — they are PostgreSQL-only, derived
from the stored GeoJSON, and Alembic's autogenerate is told to ignore them —
so **a database created by `create_all` (what `init_db()` does) has the PostGIS
extension and none of these columns**. Such a database answers
`SELECT postgis_full_version()` happily and fails every spatial query on a
column that is not there.

The start-up probe therefore checks `geometry_columns` for all six, not just
the extension:

- fewer than six → `spatial_sql` is reported false, the application uses the
  Python fallback paths, and the label says so
  ("PostgreSQL 16.4 + PostGIS 3.4, but 0 of 6 geometry columns exist");
- in `ENVIRONMENT=production` that state is fatal, naming `db upgrade` as the
  fix.

`python -m app.water.cli db upgrade` (the compose `migrate` job) is the only
supported way to create or update the schema. Verified on a fresh database:
the chain from base to head produces exactly those six registered geometry
columns.

## Risks

- SQLite stores naive datetimes; the code normalises to UTC on read
  (`_as_utc`). PostgreSQL `timestamptz` removes that need; keep the helper
  until every row is migrated.
- The status cache columns (`cached_status`, `cached_historical_status`) must
  be refreshed after migration (`cli refresh-status`).
- The test suite drops every table at teardown, so it must never be pointed at
  a real database. `conftest` overwrites `DATABASE_URL` with its own temporary
  SQLite file and refuses to run otherwise; `scripts/check_test_isolation.sh`
  proves it against the live server. Use `TEST_POSTGIS_URL` to exercise
  PostGIS: those tests create a throwaway database and drop only that.

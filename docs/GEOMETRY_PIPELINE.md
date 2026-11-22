# Geometry pipeline

How a CPCB or CWC water body acquires a real shape, without making thousands
of public API requests.

```
OSM regional extract (.osm.pbf, Geofabrik, ODbL)
        │  cli extract-osm          one streaming pass, offline afterwards
        ▼
named water features (.ndjson: element, names, tags, bbox, geometry)
        │  cli import-geometry      name cores → candidates → proximity →
        ▼                           connectivity/containment → merge → validate
water_body_geometries (GeoJSON + provenance)
        │  cli db sync-geometry     ST_GeomFromGeoJSON
        ▼
PostGIS geometry(…, 4326) + GIST index
        │  cli geometry-qa
        ▼
map, detail pages, spatial answers
```

## Why an extract instead of the API

Phase 2 asked Overpass once per water body. That is thousands of requests
against a shared free service: it rate-limited us, blocked us repeatedly, a
national pass took hours, and a deployment could never depend on it. One
Geofabrik extract (`india-latest.osm.pbf`, ~1.7 GB) holds the same data, and
matching against it is a local join.

| | Phase 2 (Overpass) | Phase 3 (extract) |
|---|---|---|
| Requests for a national pass | ~1,000+ | 1 download |
| Wall clock | hours, with failures | ~13 min extract + **47 s** matching |
| Matched bodies | 119 | 303 |
| Repeatable offline | no | yes |

## Step 1 — `extract-osm`

One streaming pass with `pyosmium`, keeping only **named** water features:

* `waterway` ∈ river, stream, canal, drain, tidal_channel → lines
* `natural=water`, `landuse=reservoir`, `water=*` → areas, with multipolygon
  relations assembled by osmium

Output for India: **41,970 line features and 31,066 area features** (145 MB
of GeoJSON lines, vs 1.7 GB of PBF), plus a `.meta.json` recording the source
file, licence and extraction time. The node cache goes to disk for a
country-sized extract; RAM stays bounded.

## Step 2 — `import-geometry`

Per water body, offline:

1. **Name cores** — type words removed ("Mithi River" → MITHI), platform
   qualifiers dropped ("Ganga River (Bihar)" → GANGA), known variants added
   (Ganges, Kaveri, Son, Sutlej). Matching runs against every OSM name key
   (`name`, `name:en`, `alt_name`, …).
2. **Type affinity** — a canal may only match `waterway=canal`, a river only
   river/stream/tidal_channel. Without this "Krishna Canal" adopted the
   Krishna River's segments.
3. **Proximity** — a candidate is accepted only if a monitoring station is on
   or near it (rivers ≤ 2 km, lakes ≤ 1 km).
4. **Connectivity (lines)** — starting from segments anchored by a station,
   the course is followed through segments sharing an endpoint (~11 m
   tolerance). This extends a river along its real course and never joins a
   disconnected river of the same name.
5. **Containment (areas)** — the nearest same-named polygon to each station;
   if two fit equally well the body is recorded `ambiguous` and gets no
   geometry.
6. **Merge** — lines into a MultiLineString, areas into a (Multi)Polygon;
   coordinates rounded to 5 dp.

Outcomes are recorded per body in `water_bodies.geometry_status`: `matched`,
`no_candidates`, `not_near_stations`, `ambiguous`, `no_station_coordinates`,
`name_too_generic`, `unsupported_type`. The detail page shows the reason.

## Provenance

Every stored geometry carries: source (`OpenStreetMap bulk extract
(Geofabrik)`), the OSM element ids it merged, the licence (ODbL), when it was
retrieved, the extract file as `version`, the confidence (`high` when every
station is within the "on" distance, else `medium`), the match method and the
notes behind it. Stations carry `relationship_type`
(`within_geometry`/`on_geometry`/`near_geometry`/`name_match_only`) and
`geometry_distance_m`.

## Step 3 — `db sync-geometry`

Derives the PostGIS columns from the stored GeoJSON (`ST_GeomFromGeoJSON`),
station points from lat/lon, and city extents from the **union of their
district polygons** (`ST_Union(ST_MakeValid(...))` — a few simplified
geoBoundaries districts are not OGC-valid and GEOS refuses to union them).
Always recomputed, so a re-import never leaves a stale shape behind.

## Step 4 — `geometry-qa`

Reports, and only repairs with `--fix`:

| Check | What it catches |
|---|---|
| `unparseable_geojson`, `unsupported_type` | corrupt storage |
| `degenerate`, `zero_area_polygon` | zero-length lines, empty rings |
| `implausible_extent` (> 3,000 km) | a match that swallowed the wrong feature |
| `outside_india` | a coordinate-order or projection error |
| `stale_bbox_columns` | bbox columns disagreeing with the geometry |
| `station_far_from_geometry` (> 25 km) | a station attached to the wrong body |
| `duplicate_source_element` | two bodies claiming the same OSM way |
| `invalid_geometry` (PostGIS `ST_IsValid`) | self-intersections |
| `wrong_srid` | anything not EPSG:4326 |

The first national run surfaced two real defects, both now fixed and
regression-tested: the canal/river type collision above, and stations named
for a tributary ("Purna at Gopalkheda") attached to the main river 70 km
away, which identity now resolves to the tributary.

## Refreshing

```bash
curl -L -o data/raw/osm/india-latest.osm.pbf \
     https://download.geofabrik.de/asia/india-latest.osm.pbf
cli extract-osm --pbf data/raw/osm/india-latest.osm.pbf
cli import-geometry --file data/processed/india-water.ndjson
cli db sync-geometry && cli geometry-qa
```

Neither the extract nor the `.ndjson` is committed; both are rebuilt by these
commands and ignored by git.

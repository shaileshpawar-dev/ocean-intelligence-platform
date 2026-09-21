# Water data model

The central entity is the **water body**, not the pollution event. A river has
a location and a monitoring history and stays meaningful to look up when
nothing has been measured for years; a pollution event is something that may
or may not have happened to it.

## Hierarchy

```
State ── District ── WaterBody ── MonitoringStation ── WaterQualityObservation
                         │
                         ├── RiverStretch   (only where CPCB's criterion supports one)
                         └── WaterEvidence  (non-measurement evidence)
```

Districts double as the "city" unit. The source keys everything to districts,
and the places people search for — Mumbai, Pune, Bengaluru — are districts in
that data. A separate city table would require city boundaries the source
never supplied.

## Tables (`backend/app/models/water.py`)

| Table | Holds | Notes |
|---|---|---|
| `data_sources` | One row per provider | Declared cadence, last success, last error, availability |
| `states`, `districts` | Geography | District centroid = mean of its stations (derived, labelled as such) |
| `water_bodies` | Canonical entity | Type, centroid, aliases, `match_method`, `match_confidence`, plus cached counters and two cached statuses |
| `river_stretches` | Segments | Schema in place; not yet populated — see limitations |
| `monitoring_stations` | Sampling points | Coordinates with `geo_quality` (`ok`/`suspect`/`missing`) |
| `water_quality_observations` | One parameter, one station, one time | Long format; see below |
| `water_evidence` | Satellite, image, report, inference evidence | Typed by `WaterEvidenceType`; no rows yet |
| `ingestion_runs` | Audit per run | Seen/valid/rejected/inserted/duplicate counts, errors |
| `water_body_status_history` | Status over time | Schema in place |

### Why observations are long-format

One row per parameter, not one row per sample with forty nullable columns.
Sources publish very different parameter sets, and a wide table would be
mostly NULL and need a migration whenever a source adds a column.

Each row keeps `value` (as published), `normalized_value` (canonical unit, or
NULL when no exact conversion exists), `raw_value` (the cell verbatim),
`quality_flag`, `source_reference` (resource id and row id), and both
`observed_at` and `retrieved_at` — when it was measured and when the platform
fetched it are different facts.

Uniqueness is `(station_id, parameter, observed_at)`, which is what makes
ingestion idempotent.

## Evidence vocabulary

`WaterEvidenceType`: `MEASURED`, `SATELLITE_OBSERVED`, `IMAGE_DETECTED`,
`REPORTED`, `INFERRED`, `FORECAST`, `RETRIEVED`. It sits alongside the marine
pipeline's `EvidenceLevel` rather than replacing it: a laboratory BOD value
and a SAR dark formation are different kinds of claim.

## Identity resolution (`water/matching.py`)

Because the source's `River` column is empty, identity comes from station
names such as `GODAVARI AT NASIK D/S GADGEBABA MAHARAJ NAGAR NASHIK`. Rules,
in order of confidence:

| Method | Confidence | When |
|---|---|---|
| `source_field` | 1.0 | Source populated `River`/`Tributary` |
| `station_name_parse` | 0.75 | Name carries a type keyword (river, lake, beel, tank, creek, dam, …), including regional terms |
| `type_propagated` | 0.6 | No keyword, but the same name is typed elsewhere in the corpus |
| `unclassified` | 0.4 | Nothing establishes a type; shown as "Unclassified" |

Groundwater stations (`GROUND WATER AT…`, `BORE WELL…`) and municipal assets
(`OVER HEAD TANK…`) are recognised and never typed as surface water.

**Merge rules.** Rivers are keyed nationally (they cross states); lakes,
ponds and wells per state (their names repeat). A same-named candidate more
than 500 km away starts a separate, state-qualified body — which is why the
Ganga in West Bengal is currently a separate record from the Ganga in Uttar
Pradesh (Bihar is not yet ingested to bridge them).

**Corpus-wide reconcile.** After each run, untyped bodies are merged into a
same-named typed body when within the distance guard, or retyped in place.
This is what makes Delhi's `YAMUNA AT …` and Uttar Pradesh's `YAMUNA RIVER …`
one water body. Names claimed by conflicting types are left alone rather than
resolved by vote.

Validated against 1,162 real station names: 55% explicit keyword, 12% type
propagated, 32% unclassified (names such as `ERODE-2` that genuinely do not
identify a water body), 1% unidentified.

## Geometry: why not PostGIS yet

Positions are plain `latitude`/`longitude` columns with composite indexes.
PostGIS types would stop the platform running on SQLite, which the local
workflow and the current container deployment depend on. Bounding-box
queries are exact in SQL; radius queries pre-filter by box in SQL and apply
exact haversine distance in Python, so results are true circles.

Migration path: add a `geography(Point)` column populated from lat/lon,
a GiST index, and swap the two query helpers in `water_service.py` for
`ST_DWithin`/`ST_MakeEnvelope`. Nothing above the service layer changes.
PostGIS is **not** implemented and is not claimed.

## Postgres

`DATABASE_URL=postgresql+psycopg://…` is supported by the engine setup and
`psycopg[binary]` is a dependency. The water schema uses only portable types
(JSON, not JSONB). It has **not** been run against Postgres in this session.

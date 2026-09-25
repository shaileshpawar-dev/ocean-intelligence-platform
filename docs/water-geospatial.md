# India Water Intelligence V2 — geospatial foundation

Live counts are in [DATASET_COVERAGE.md](DATASET_COVERAGE.md), generated from
the database. This document explains how each layer is built and what it
refuses to do.

## 1. Coverage

`python -m app.water.cli ingest --all` loads every state the CPCB/NWDP
catalogue lists (35 state/UT codes, 211 queryable resources). Forward-dated
placeholder resources (2026–2030) are empty and skipped. A state the source
lists but which yields no rows is reported as such, never dropped.
`cli coverage --markdown docs/DATASET_COVERAGE.md` regenerates the report;
`GET /water-coverage` serves it (cached five minutes) and the Data sources
page shows it.

Newest data: most state extracts end in 2020–2021; ten Meghalaya stations
have samples to January 2025. The national "latest date" is therefore not the
date of the data in general, and the UI never implies it is.

## 2. Canonical identity (`matching.py`, `ingestion.py`)

Layered and deterministic; no language model is involved.

1. **Source field** — a populated `River`/`Tributary` column wins (empty in
   the current source).
2. **Station-name parse** — the water body is the name before the first
   position marker (`AT`, `D/S`, `U/S`, `MIDSTREAM`, `UPSTREAM`,
   `DOWNSTREAM`, `NEAR`…). The rest is kept as the station's
   `position_descriptor` ("At Nasik D/S Gadgebaba Maharaj Nagar Nashik"), so
   sampling positions never become separate water bodies.
3. **Canonical spelling** — `BRAHAMPUTRA → BRAHMAPUTRA`, `KAVERI → CAUVERY`,
   `TAPTI → TAPI` … the original stays as an alias.
4. **Type propagation** — a name seen elsewhere with a keyword ("river") types
   the same name without one.
5. **Proximity** — rivers are keyed nationally but a station > 500 km from a
   body's centroid starts a state-qualified body; lakes, ponds and wells are
   keyed per state (names like "Rani Talab" repeat across India).
6. **Reconcile (after every ingest)** — untyped bodies join a same-named typed
   body nearby; drains (`… NALLAH`) join a same-named river within 25 km;
   **river and canal fragments join when their nearest stations are within
   150 km**, transitively. That last rule fixed the national ingest splitting
   the Ganga into four state bodies and the Yamuna into two; distant namesakes
   (Amravati in Tamil Nadu and in Gujarat) stay separate. The connected river
   takes the plain name, distant namesakes are qualified by state, slugs never
   change and every former name is an alias.
7. **Unresolved** — labels that name no water body (`ERODE-2`) are typed
   `other` with confidence 0.4 and labelled "Unclassified".

Every body records `match_method`, `match_confidence`, `aliases` and
`source_ids`. Regression tests: Mithi (five positional labels, one river),
Yamuna, Ganga, Brahmaputra spellings, Rani Talab in two states, Amravati,
cross-state fragment linking (`test_water_identity.py`).

## 3. Geometry

**Phase 3 replaced the per-body Overpass calls with a bulk pipeline.** The
full design is in [GEOMETRY_PIPELINE.md](GEOMETRY_PIPELINE.md); in short:
one Geofabrik regional extract is read once (`cli extract-osm`), and matching
runs entirely offline (`cli import-geometry`) by name cores, water-type
affinity, station proximity and — for rivers — connectivity along shared
endpoints. A national pass takes seconds instead of hours and makes no
network requests.

Storage is unchanged: GeoJSON plus full provenance in
`water_body_geometries`, with the PostGIS `geom` column derived from it
(`cli db sync-geometry`) and indexed with GIST. `cli geometry-qa` validates
what was stored.

### Sources checked

| Source | Result |
|---|---|
| **OpenStreetMap regional extract (Geofabrik)** | Used. Named rivers, canals, lakes, reservoirs; ODbL. |
| OpenStreetMap via Overpass API | Phase 2 approach; still supported for one-off refreshes, no longer used for bulk. |
| **NRSC Bhuvan** WMS (`basemap:waterbody_DEM`) | Map overlay only: WFS is disabled, so it cannot supply vector shapes. |
| **geoBoundaries** IND ADM1 / ADM2 | State and district boundaries (see §5). |
| India-WRIS / WBIS | Unreachable from this environment (connection reset at the transport layer); not used. |

## 4. River stretches

`river_stretches` carries `derivation` (default `source_defined`),
`official_stretch_id`, `source`, `assessment_year`, `source_reference`.
No stretch is created from station spacing; none exists until an official
table is imported.

## 5. Boundaries and cities

- `cli import-boundaries` — geoBoundaries IND ADM1 (DataMeet / ECI,
  CC BY 2.5 IN, 2011, 36 units) and ADM2 (Pathways / LGD, ODbL, 2021, 735
  districts), pinned to one commit. States join CPCB codes by ISO 3166-2
  (`IN-CT → CG`, `IN-OR → OD`, `IN-TG → TS`, `IN-UT → UK`, `IN-DH → DN/DD`).
  Districts get their state by a **vote of their vertices** — a centroid test
  put Kamrup Metropolitan in Meghalaya because the 2011 and 2021 files do not
  share edges. Boundaries are for navigation, not the legal boundaries of
  India, and the map says so.
- `cli import-cities` — 35 cities, each an explicit grouping of whole
  districts with a note ("Greater Mumbai is exactly the Mumbai City and
  Mumbai Suburban districts"; "Pune city lies within Pune district; the whole
  district is used"). Position and extent come only from the district
  polygons. No municipal boundary is invented.

## 6. Map

`/app/map`, all layers fetched per viewport (bbox + zoom) with limits:

| Group | Layers |
|---|---|
| Hydrology | Matched rivers (lines) and lakes (polygons), zoom ≥ 6; Bhuvan WMS raster |
| Monitoring | CPCB stations, clustered server-side on a zoom-sized grid (singles from zoom 11); water bodies without geometry as points |
| Status | Latest measured status: marker colour, river casing, lake outline. **Water stays blue.** |
| Boundaries | States (hover, click to select and filter), districts of the selected state |
| Evidence | Satellite scenes, on water-body pages |

The layer catalogue (sources, attributions, WMS endpoint) is served by
`GET /map/layers`. Search ranks cities, then water bodies, districts, states
and stations; a query that reads as a question ("polluted rivers near
Mumbai") offers "Ask" and hands off to the Q&A. The detail panel docks beside
the map on desktop and becomes a bottom sheet on phones. Empty views say that
an empty area means no station in the source, not clean water.

Performance: boundaries are cached as serialised bytes and gzip-compressed
(national states 185 KB → 55 KB on the wire); geometry is simplified and
rounded per zoom for display only.

## 7. Satellite evidence (`satellite.py`)

One complete path, for lakes and reservoirs with a matched polygon:
Sentinel-2 L2A via Microsoft Planetary Computer (STAC search + data API).

- The tile must **contain** the whole lake.
- Over the lake's own polygon, the Scene Classification Layer must show
  ≥ 80% water and ≤ 5% cloud/cirrus. Tile-level cloud cover is not trusted:
  scenes reported as 1% cloudy had cirrus over exactly the lake.
- Every scene tried is stored with its rejection reason.
- Stored: scene id, acquisition date, true-colour image URLs, bbox, licence,
  and **NDTI** = (B04 − B03)/(B04 + B03), median over the polygon, labelled
  *"Satellite-derived turbidity proxy (NDTI, uncalibrated)"*,
  `SATELLITE_OBSERVED`, no unit, `calibrated: false`, with its caveat.
  It is never compared with a standard or placed beside CPCB laboratory
  turbidity as if comparable.

### Persistence

The **evidence** is in the database (`water_images`): scene id, sensor,
acquisition date, footprint, cover fractions, the derived index and its
provenance. Only the *picture* is a URL, rendered on demand by the imagery
service. So:

- a fresh container shows every processed scene immediately, with no
  reprocessing and no downloads at start-up;
- if the imagery service is unreachable, the record still reads correctly
  and the page simply has no picture;
- no image binaries sit in PostgreSQL. If a deployment wants to stop
  depending on the external renderer, the chips belong in S3 (see
  [PRODUCTION_ARCHITECTURE.md](PRODUCTION_ARCHITECTURE.md)); nothing else
  changes, because the row already carries the metadata.

Rivers are not attempted (centrelines; 10 m pixels do not isolate most
channels). Example outcomes: Hussain Sagar accepted a 16 Jun 2026 scene
after rejecting three monsoon scenes for 26–34% cirrus; Rajsamand Lake was
refused because only ~1% of its full-capacity outline was water on clear
days.

## 8. Q&A geography (`rag.py`, pipeline `water-rag-2.0.0`)

- Curated cities resolve by name or alias and stand in for their districts.
- "near X" is measured from the city's **extent** (0 km inside it), default
  25 km; "within N km of X" uses N; "in X" means within the extent.
- "monitoring stations near X" answers with stations (`MEASURED`).
- "high-concern …" filters strictly to `HIGH_CONCERN` / `POLLUTED_STRETCH`.
- Status answers carry `evidence_layers`: MEASURED, REFERENCE_COMPARISON
  (standard and basis, or why none), SOURCE_CLASSIFICATION, DERIVED_STATUS
  (dated, "not a statement about today") and SATELLITE_OBSERVED (proxy,
  "not a measurement") when present.
- No language model produces any value; unmatched places are refused.

# Implementation summary — OceanAI India Water Intelligence

Branch `feature/india-water-intelligence`, built on `main` at `738f1ca`
(the published v1). **Nothing was deployed and the public v1 was not
changed.** Phase 2 (below) builds on Phase 1 (further down, kept as the
record of that change).

---

# Phase 2 — V2 geospatial foundation

## P2.1 Summary

Phase 2 turns a seven-state prototype into a national, geospatially honest
platform:

- **All 35 CPCB state/UT codes** ingested from the live NWDP API — 211
  resources, **582,192 observations, 4,000 stations, 2,595 water bodies**,
  zero ingestion errors. Station counts cross-checked against the source
  (Goa 64/64, Sikkim 12/12).
- **No default standard.** Rivers are compared against the EP Rules 1986
  bathing-water criteria (what CPCB uses for polluted river stretches);
  everything else shows "Reference comparison unavailable" unless a
  designated use is recorded or chosen. `POLLUTED_STRETCH` only from an
  imported official classification (import path built; no data loadable).
- **Four evidence layers** separated end to end: MEASURED,
  REFERENCE_COMPARISON, SOURCE_CLASSIFICATION, DERIVED_STATUS; satellite
  values are a fifth, `SATELLITE_OBSERVED`, uncalibrated proxy.
- **Real geometry** from OpenStreetMap matched to stations (lines for rivers,
  polygons for lakes), with provenance; **boundaries** from geoBoundaries;
  **35 cities** as documented district groupings; a rebuilt **map** with a
  layer catalogue, server clustering, state selection and the NRSC Bhuvan
  water raster; **Sentinel-2** evidence for lakes with strict per-lake
  checks; **Q&A** that understands cities, distances and stations.

## P2.2 What was built, by requirement

| Req | Delivered |
|---|---|
| 2A–2B coverage | National ingest; per-plan error isolation; `cli coverage`, `GET /water-coverage`, `docs/DATASET_COVERAGE.md`, coverage table in the UI |
| 2C–2D identity | Position markers incl. MIDSTREAM/UPSTREAM/DOWNSTREAM kept as `position_descriptor`; canonical spellings; per-state keying for local features; drain→river and **cross-state river/canal linking** (Ganga: 4 state fragments → one 85-station river; Yamuna 2 → 1); leading-article fix; regression tests (Mithi, Yamuna, Ganga, Brahmaputra, Rani Talab, Amravati) |
| 2E source verification | Bhuvan, OSM, geoBoundaries, Planetary Computer, EP 1986 PDF verified live; PRS report, CPCB DBU PDF, Bhuvan WFS, WRIS/WBIS documented as inaccessible |
| 2F–2H geometry | `water_body_geometries` with provenance; OSM matching by name + station proximity; monitored reaches; `ambiguous` instead of guessing; station `relationship_type` + distance |
| 2I river stretches | Model with `derivation`, official id, source, year; no stretch invented |
| 2J PRS | `source_classifications` + validated CSV importer (`cli import-classifications`); no rows |
| 2K–2N standards/status | `reference_catalog.py` + DB tables; explicit selection order; desirable levels; engine 2.0 with `NO_APPLICABLE_REFERENCE`; explanations only from stored facts |
| 2O–2T map | Lines/polygons, water blue, status casing/outline, clusters, viewport + zoom + filters + limits, layer control (Hydrology / Monitoring / Status / Boundaries / Evidence) |
| 2U–2W geography | State boundaries (select, hover, search, zoom, filter), district outlines, curated cities |
| 2X detail | Geometry map with stations, docked panel on desktop, bottom sheet on phones |
| 2Y–2AA imagery | `water_images`; Sentinel-2 L2A path; NDTI proxy clearly labelled, never beside lab values as comparable |
| 2AB–2AD RAG | City/extent distances, "within N km", stations near X, strict high-concern, state listings, evidence layers per answer |
| 2AE–2AH UX | "Latest available observation" / "Current condition: cannot be established"; sources panel by role; data quality with visible factors and rule |
| 2AI–2AJ search/empty | Cities first; question-shaped queries hand off to Q&A; honest empty states |
| 2AK benchmark | Below |
| 2AL PostGIS | `docs/POSTGIS_MIGRATION.md` (plan, not executed) |

## P2.3 Real-data outcomes (snapshot at time of writing)

| Layer | Result |
|---|---|
| Geometry | Matching is limited by the public Overpass service (rate limits, resets). Snapshot: 93 bodies matched (lakes 53, ponds 12, reservoirs 6, rivers 21, canal 1), 189 with no named OSM feature near their stations, 3 not near stations, 1 ambiguous, 65 source errors pending retry, the rest not yet attempted. River shapes are re-matched after fragment merges. |
| Satellite | Hussain Sagar: 16 Jun 2026 scene accepted (89.5% water, 0% cloud) after three monsoon scenes rejected for 26–34% cirrus. Rajsamand: refused, ~1% of its full outline was water on clear days. |
| Boundaries | 36 states (34 linked to CPCB codes), 735 districts, all with a parent state; 35 cities positioned |
| Standards | 6 standards, their thresholds seeded to the DB |
| Classifications | 0 (source inaccessible) |

## P2.4 Defects found by testing against real data (all fixed, with tests)

1. Centroid merge rule split long rivers into state fragments → station-linking reconcile.
2. Overpass server-side key regex caused timeouts/blocks → indexed keys + local name matching.
3. `out tags geom` dropped relation members; no multipolygon lake could match → `out geom`.
4. Platform qualifiers ("(Bihar)") and `re.escape` spaces broke name queries.
5. "Sagar" stripped from proper names (Hussain Sagar) → two-reading name cores.
6. District parent by centroid misplaced Kamrup Metropolitan → vertex vote.
7. City answers returned HTTP 500 (ORM object in the trace) → JSON-safe trace; HTTP-level tests.
8. "The River" parsed from "THE RIVER ASHWANI …"; common words resolving to bodies.
9. `httpx` missing from runtime requirements; image crashed on start.
10. Boundary cache path unwritable in the container → `WATER_CACHE_DIR`.
11. "rivers in Goa" unanswered; state listings truncated by a pre-filter row limit.
12. Reference tables empty after the first national ingest (seeding added after it started).
13. Zero-width first map request; overlapping controls with the docked panel.

## P2.5 Verification

| Check | Result |
|---|---|
| Backend pytest | **415 passed** |
| Ruff check + format | Pass |
| TypeScript `tsc --noEmit` | Pass |
| ESLint `--max-warnings 0` | Pass |
| Vite production build | Pass |
| Docker build | Pass (`oceanai-backend:v2-local`, local only) |
| Container | Healthy, non-root (uid 1000); bootstrap from the live source; boundaries/cities import inside; all Phase 2 endpoints 200; SPA served |
| Browser (desktop) | Map layers, geometry, clusters, state selection, Bhuvan WMS, search → city, search → Q&A, docked panel, detail page, Q&A evidence layers |
| Browser (375 px) | Bottom sheet, focused feature kept visible above it |
| Secret scan | No credentials in the 73 changed files; no `.env`, key or DB files tracked |

## P2.6 Benchmark (10 runs, TestClient, median ms)

Before = Phase 1 database (7 states, 177k observations); after = national
(582k observations, 3.3× the data). Not like-for-like.

| Route | Before | After |
|---|---|---|
| `/map/stations` whole India | 2,218 | 352 |
| `/map/near` Delhi 25 km | 112 | 17 |
| `/water-bodies/mithi-river` | 23 | 36 (adds geometry, quality, sources, imagery) |
| `/map/water-bodies` whole India | 28 | 140 (2× the features) |
| `/search?q=ganga` | 22 | 73 (adds cities) |
| `POST /water/ask` (polluted rivers near Mumbai) | 60 | 152 (city extent search) |
| `/water-overview` | 56 | 187 |
| `/boundaries/states?zoom=4` | — | 52 (cached; 185 KB, 55 KB gzipped) |
| `/map/geometries` Mumbai / India | — | 19 / 121 |
| `/map/station-clusters` India z5 | — | 280 |
| `/water-coverage` | — | 3 (cached; 887 uncached) |

## P2.7 Deployment readiness

**NOT READY for public deployment.** The build is sound and verified
locally, but:

1. Geometry and imagery are populated by long-running jobs against rate-
   limited public services and are incomplete; a deployed container starting
   from SQLite would have none of it. Production needs a persistent database
   (PostgreSQL, ideally PostGIS) seeded from this run, not per-container
   bootstrap.
2. A national ingest takes ~12 minutes; `WATER_BOOTSTRAP_STATES` suits one or
   two states, not all 35, on an ephemeral task.
3. Outbound calls to Overpass, geoBoundaries and Planetary Computer have not
   been verified from inside AWS (Fargate egress, NAT).
4. The deployment would replace the public v1 demo, which requires an
   explicit go-ahead.

Ready for: local use, review, and a staging deployment against a persistent
database.

## P2.8 Recommended Phase 3

1. Persistent PostgreSQL + PostGIS (plan in `docs/POSTGIS_MIGRATION.md`),
   with Alembic; move spatial queries to SQL.
2. Batch geometry matching (one Overpass query per region, local assignment)
   or an OSM extract for India to remove the rate-limit bottleneck; finish
   river geometry.
3. Obtain the CPCB PRS table (RTI/official data request) and designated-use
   records; import through the existing validated paths.
4. Scheduled ingestion with change detection; status history population.
5. IS 10500 for groundwater; coastal/marine criteria.
6. Station-to-reach matching along river geometry (upstream/downstream order).
7. Staging deployment behind HTTPS, then a reviewed cut-over from v1.

---

# Phase 1 record

## 1. Executive summary

OceanAI now answers "what is known about this Indian water body, when was it
measured, against which standard, and where did the number come from?" It
ingests **real CPCB surface-water data** from the National Water Data Portal
(verified public API), resolves 1,190 monitoring stations into 765 water
bodies across seven states, judges them against cited CPCB criteria, shows
them on a full-screen India map, and answers questions from stored records
with citations that fly the map to the evidence.

The single most important finding shaped everything: **the newest CPCB data
published anywhere is from 2021.** The platform therefore reports every water
body's present status as *no recent data*, and separately shows what the last
measurement found, always with its date.

## 2. What changed

A new water domain (`backend/app/water/`), 10 tables, a service layer, 20 API
endpoints, 9 frontend pages, a grounded Q&A pipeline, a sync CLI, startup
bootstrap for ephemeral containers, 109 tests, and five focused docs. Marine
v1 code is untouched apart from shared shell navigation and the move of its
map to `/app/ocean-map`.

## 3. Existing features preserved

All 205 original tests pass unmodified. SAR detection, two-stage refinement,
YOLO (checkpoint-driven class resolution), risk engine, forecasting, marine
RAG and its `no_evidence` gate, the marine agent workflow, reports, MLOps
pages and the evidence ladder are unchanged and reachable.

## 4. New features

India water map; water-body, state, city (district), station, standards and
data-source pages; dual status; "why this status?"; per-parameter cards with
cited limits; gap-aware trend charts; unified search with official place
renamings; true-circle and district-proximity spatial search; grounded water
Q&A with map actions; ingestion CLI and bootstrap; data-quality reporting.

## 5. Architecture

```
NWDP CKAN API → NWDPCPCBProvider → ingestion (validate, normalise, match,
dedupe, reconcile, denormalise, log) → SQLite/Postgres → water_service →
FastAPI /api/v1 → React (map, pages, Q&A)
                                   ↘ water.rag (IDENTIFY→OBSERVE→RESEARCH→ANALYZE→REPORT)
```

## 6. Data model

`data_sources`, `states`, `districts`, `water_bodies`, `river_stretches`,
`monitoring_stations`, `water_quality_observations` (long format, unique on
station+parameter+time), `water_evidence`, `ingestion_runs`,
`water_body_status_history`. New enums: `WaterBodyType`, `WaterEvidenceType`,
`WaterStatus`, `QualityFlag`. Lat/lon columns with composite indexes; PostGIS
not implemented. See `docs/data-model.md`.

## 7. Data sources

**Integrated:** CPCB Surface Water Quality (Manual) via NWDP — 315 resources,
public, no key, verified live. **Not integrated** (documented, no stubs):
CPCB real-time dashboard, Bhuvan/NRSC, MPCB, CWC, Sentinel for inland water,
data.gov.in. See `docs/data-sources.md`.

## 8. APIs added

`GET /water-bodies`, `/water-bodies/{slug}`, `/{slug}/parameters`,
`/{slug}/trend`, `/{slug}/stations`, `/{slug}/sources`, `/stations`,
`/stations/{id}`, `/map/water-bodies`, `/map/stations`, `/map/near`,
`/states`, `/states/{slug}`, `/cities/{slug}`, `/search`, `/water-overview`,
`/water-standards`, `/water-parameters`, `/water-quality-report`;
`POST /water/ask`. No existing endpoint changed.

## 9. Frontend routes

Added `/app/india`, `/app/map` (now the water map), `/app/ai`,
`/app/water/:slug`, `/app/state/:slug`, `/app/city/:slug`,
`/app/stations/:stationId`, `/app/standards`, `/app/data-quality`. Changed:
marine map moved from `/app/map` to `/app/ocean-map`.

## 10. Map

Full-bleed Leaflet map; per-viewport bbox loading with server-side caps;
markers coloured by dated status with a legend saying so; unknown in grey;
water-type and status filters; station layer; search with fly-to and panel;
`?highlight`, `?bbox`, `?focus` deep links; bottom sheet on mobile.
Not built: clustering, boundary and basin layers.

## 11. Water quality

43 canonical parameters with alias resolution against the published headers
(including typos), exact unit normalisation only, censored-value and
unparseable flags, missing tokens never converted to zero.

## 12. Status engine

Six bands, no score. Freshness gate (cadence-relative) → insufficient-data
gate → national polluted-stretch criterion → severity from breaches. CPCB
classes A–E with source and URL on every threshold; class C default;
dissolved oxygen judged as a minimum. See `docs/water-status-engine.md`.

## 13. Satellite / YOLO / SAR

Preserved unchanged for the marine pipeline. **Not connected to water
bodies:** no satellite, image or SAR evidence is attached to any inland water
body. The `water_evidence` table and `SATELLITE_OBSERVED`/`IMAGE_DETECTED`
types exist so it can be added without schema change. Nothing was fabricated
to fill the gap.

## 14. RAG changes

Marine RAG unchanged. Corpus extended with summaries of the two CPCB criteria
documents and a freshness methodology note (22 seed documents). New
`water/rag.py` answers from database records rather than passages.

## 15. Agent changes

The water Q&A is a bounded five-stage pipeline with every tool call recorded
in a trace; no planner, no loop, no language model on the value path. The
marine agent workflow is unchanged.

## 16. Evidence and provenance

Every observation keeps `source_reference` (CKAN resource and row id),
`observed_at`, `retrieved_at`, raw value and quality flag. Every Q&A citation
carries date, source and reference and links to the map. Collection responses
keep the existing provenance envelope.

## 17. Testing performed

Offline unit and integration tests; the live adapter exercised against the
real portal; browser verification of map, detail, India, Q&A and citation
flows on desktop and 375 px mobile; Docker build, startup bootstrap from the
real source, and restart.

## 18. Test results

| Check | Result |
|---|---|
| Backend pytest | **314 passed** (205 original + 73 water domain + 36 water pipeline) |
| Ruff check / format | Pass (repository-wide) |
| TypeScript `tsc --noEmit` | Pass |
| ESLint `--max-warnings 0` | Pass |
| Vite production build | Pass |
| Docker build | Pass — `oceanai-backend:water-v2`, 315 MB |
| Container bootstrap | Maharashtra, 25,507 observations, 11 s, from the live source |
| Container restart | Data retained; bootstrap correctly skipped |
| Browser console | No errors (three `ERR_CONNECTION_REFUSED` occurred only while the server was deliberately stopped) |

## 19. Performance (local, 177k observations, 10 runs)

| Route | Median | p90 |
|---|---|---|
| `/health` | 3.2 ms | 4.1 ms |
| `/search?q=ganga` | 12.6 ms | 18.8 ms |
| `/map/water-bodies` whole India | 17.3 ms | 18.2 ms |
| `/map/water-bodies` Mumbai bbox | 3.5 ms | 4.0 ms |
| `/water-bodies/mithi-river` | 8.0 ms | 8.5 ms |
| `/water-bodies/mithi-river/trend` | 3.4 ms | 4.4 ms |
| `/map/near` Delhi 25 km | 32.9 ms | 35.4 ms |
| `POST /water/ask` | 14.4 ms | 15.3 ms |
| `/water-overview` | 12.0 ms | 14.4 ms |

Known inefficiency: `summarise_body` issues per-row lookups for state and
district, and the parameter-filter Q&A path reads latest parameters per body.
Both are fine at seven states and should be batched before all 35 are loaded.

## 20. Deployment

**Not deployed.** The live ALB still serves v1. Docker is verified locally,
and `WATER_BOOTSTRAP_STATES` lets an ephemeral Fargate task rebuild water data
from the source on start. The NWDP call has not been verified from inside
Fargate. Left for an explicit go-ahead because it replaces the public demo.

## 21. Environment variables

New: `WATER_BOOTSTRAP_STATES` (optional). Existing ones unchanged. The water
source needs no credential.

## 22. Known limitations

Newest data 2021; seven of 35 states ingested; SQLite on ephemeral storage in
production; no river-stretch derivation; no status-history population; no
imagery; no clustering or boundary layers; Postgres untested; PostGIS absent.

## 23. Data-source limitations

Empty `River` column; placeholder 2026–2030 resources; SQL endpoint disabled;
inconsistent district spellings; conductivity header/unit mismatch; CPCB
criteria PDFs unreachable directly (expired certificate) — values verified
from independent sources.

## 24. Scientific limitations

Monthly grab samples, not continuous monitoring. Status reflects one
designated use (class C by default). Trend answers compare annual means and
are not statistical tests. No satellite claim is made about any inland water
body.

## 25. Intentionally not implemented

Fake real-time data; any stub provider for an unreachable source; a 0–100
pollution score; LLM-generated values; user-reported issues; pollution-source
attribution; authentication; new microservices.

## 26. Self-directed improvements

- Dual status (present vs dated) instead of an all-grey or misleading map.
- Corpus-wide reconcile pass so a river is one record across states.
- Station-based geography filters (rivers first seen in another state).
- District proximity from a district's own stations, not an averaged point.
- Official place-rename aliases (Bengaluru/Bangalore, Chennai/Madras, …).
- Gap-breaking trend charts; "assessed as at the observation date" wording.
- Groundwater and municipal-asset detection so neither is typed as surface water.
- Ingestion startup bootstrap and a cadence-respecting sync CLI.
- Water contract tests added to CI's scientific-integrity job.

Bugs found and fixed by testing against real data: case-sensitive position
markers leaking into names; naive/aware datetime mismatch breaking
idempotency; CSS class collision with the marine map; present-tense data
behind a historical heading; a trace step that claimed a filter it never
applied; mobile control overlap.

## 27. Files changed

Backend: `app/water/{parameters,standards,freshness,status,matching,ingestion,rag,cli}.py`,
`app/water/providers/{base,nwdp_cpcb,__init__}.py` + bundled catalogue,
`app/models/{water,enums,__init__}.py`, `app/services/water_service.py`,
`app/api/routes/water.py`, `app/main.py`, `app/core/config.py`,
`app/rag/corpus.py`, `tests/test_water_{domain,pipeline}.py`.
Frontend: `lib/waterTypes.ts`, `lib/api.ts`, `components/water.tsx`,
`components/{Shell,ui}.tsx`, `App.tsx`, `main.tsx`, `styles/water.css`,
pages `IndiaWaterMap`, `IndiaOverview`, `WaterBodyDetail`, `StatePage`,
`CityPage`, `StationDetail`, `WaterStandards`, `DataSources`, `WaterAI`.
Docs: `data-sources.md`, `data-model.md`, `water-status-engine.md`,
`water-map-and-ai.md`, `limitations.md`, `deployment.md`, `README.md`,
`.env.example`, `.github/workflows/ci.yml`.

## 28. Database migration

No migration tool is in use; `init_db()` creates new tables on start and
leaves existing ones alone. An existing SQLite database from v1 gains the
water tables automatically. For a clean water rebuild, delete the database
file and re-ingest.

## 29. Local run

```bash
pip install -r backend/requirements-dev.txt
cd frontend && npm install && npm run build && cd ../backend
python -m app.water.cli ingest --states MH DL KA
uvicorn app.main:app --port 8000        # open /app/map
```

## 30. Production deployment

Build and push a new immutable tag to `oceanai/backend`, register task
definition revision 2 adding `WATER_BOOTSTRAP_STATES=MH,DL,KA` (and
`CORS_ORIGINS` if a domain is added), update service `oceanai-api`, and watch
`/api/v1/water-overview` until observations appear. Roll back by pointing the
service at revision 1.

## 31. Recommended next steps

1. Deploy V2 (after go-ahead) and verify NWDP reachability from Fargate.
2. Move production to RDS PostgreSQL; then add PostGIS via the documented path.
3. Ingest the remaining 28 states and batch the per-row lookups first.
4. Derive river stretches from station order along each river.
5. Add marker clustering once feature density requires it.

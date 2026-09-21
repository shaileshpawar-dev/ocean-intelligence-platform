# Implementation summary — OceanAI India Water Intelligence (V2)

Branch `feature/india-water-intelligence`, built on top of `main` at `738f1ca`
(the published v1). Nothing was deployed; see §20.

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

# Ingestion and jobs

Every expensive thing the platform does is an explicit job. The web
application reads what the jobs produced; it never produces it on demand.

    ingest-water-data     CPCB and CWC observations (public CKAN API)
    extract-osm           one pass over an OSM regional extract
    import-geometry       match those features to water bodies, offline
    fetch-imagery         Sentinel-2 scenes for matched lake polygons
    import-boundaries     geoBoundaries states and districts
    import-cities         curated city → district groupings
    import-classifications  official polluted-stretch tables (CSV)
    seed-standards        reference standards into the database
    reconcile             join river fragments split across states
    refresh-status        recompute cached statuses
    geometry-qa           validate stored geometry
    coverage              regenerate DATASET_COVERAGE.md
    db upgrade|copy-from-sqlite|sync-geometry

All are subcommands of `python -m app.water.cli`, all safe to re-run.

## Sources

| Key | Agency | Parameters | Coverage | Notes |
|---|---|---|---|---|
| `cpcb_nwdp` | Central Pollution Control Board | physical, chemical, biological | 35 states/UTs, mostly to 2021 | `River` column empty: identity from station names |
| `cwc_nwdp` | Central Water Commission | physical, chemical, biological | 29 states, **to 2025** | `River`/`Tributary` populated: identity from the source field |

Both are published on the National Water Data Portal (CKAN), public and
unauthenticated. They are stored side by side: an observation belongs to one
source, and no source overwrites another.

## Incremental sync

A resource is skipped when the portal reports the same row count as the last
successful ingest:

```
cli ingest --all --provider cwc_nwdp        # incremental (default)
cli ingest --all --provider cwc_nwdp --full # re-read everything
```

`source_resource_state` holds, per resource: the last row count, when it was
ingested, how many records it produced, its newest observation and its last
status. A monthly re-run therefore costs one request per unchanged resource
instead of paging 2.8M rows.

## Repairing identity after the rule changes

An ordinary ingest never re-points a station that already has a water body.
That is deliberate: the reconcile pass moves stations between bodies when it
merges river fragments, and an ingest that undid that would fight it on every
run.

When the identity rule itself changes — as it did once geometry QA showed that
CWC's `River` column is a basin label — the correction is explicit:

```
cli ingest --all --provider cwc_nwdp --full --reassign-identity
```

Every station whose water body now resolves differently is moved, and each
move is recorded in `ingestion_runs.detail.reassignments` as
`station: old body -> new body`, with the count in the run summary. Run
`reconcile`, `import-geometry`, `db sync-geometry`, `refresh-status` and
`geometry-qa` afterwards, in that order: reassignment changes which bodies
exist, which changes what geometry and statuses mean.

The three source drainage columns are stored verbatim on each station
(`source_river`, `source_basin`, `source_tributary`), so the next revision of
the rule can be reasoned about, and its effect measured, without re-fetching
four million observations.

## Order for a new environment

```bash
cli db upgrade                                   # schema
cli seed-standards                               # reference catalogue
cli ingest --all --provider cpcb_nwdp            # ~12 min
cli ingest --all --provider cwc_nwdp             # ~2 h (first time)
cli reconcile                                    # join cross-state rivers
cli import-boundaries && cli import-cities       # geoBoundaries
cli extract-osm --pbf data/raw/osm/india-latest.osm.pbf
cli import-geometry --file data/processed/india-water.ndjson
cli db sync-geometry                             # GeoJSON -> PostGIS
cli fetch-imagery                                # Sentinel-2, slow
cli geometry-qa                                  # validate
cli coverage --markdown docs/DATASET_COVERAGE.md
```

Or, on an existing SQLite database, skip the ingests:

```bash
cli db upgrade
cli db copy-from-sqlite --sqlite-url sqlite:///data/oip.db   # ~2.5 min
cli db sync-geometry
```

## Staging smoke test

```bash
docker compose up -d db
docker compose run --rm migrate                     # schema to head
docker compose run --rm jobs python -m app.water.cli db copy-from-sqlite \
    --sqlite-url sqlite:////app/data/oip.db
docker compose up -d backend
curl -s localhost:8000/api/v1/health                # names the backend
docker compose restart backend                      # data must survive
curl -s localhost:8000/api/v1/water-coverage        # same counts
```

The restart is the point of the exercise: the container must come back
serving the same data without re-importing anything.

## What a job records

Each run writes an `ingestion_runs` row: run id, source, start and finish,
status, records seen/valid/rejected/inserted/duplicate, stations and water
bodies created, errors, and the plans skipped as unchanged. A failure in one
resource is recorded against that resource and the run continues.

## The real-time feed

`cli sync-water-data --provider cpcb_rtwqms --all` reads CPCB's automatic
analysers from `rtwqmsdb1.cpcb.gov.in` -- plain JSON behind the public
dashboard, no key. 40 stations, 6 states, hourly, nine ingested parameters.

Three things make it behave differently from the manual extracts:

* **No cursor.** A live feed returns 40 records whether the readings are an
  hour or a month old, so `resource_total` reports nothing and every run
  re-reads. That is safe because the uniqueness key is (source, station,
  parameter, observed_at): a second run in the same hour inserts nothing, and
  the next hour inserts one row per series. Verified twice against the live
  feed: 356 seen, 0 inserted, 356 duplicates, and zero duplicate groups across
  4.6M rows.
* **Identity comes from geometry.** Twenty-seven of the forty stations are
  named for a place ("Road Bridge on Gandak, Hajipur", "Sahebganj"), so the
  station is attached to the mapped river it stands within a kilometre of,
  recorded as `spatial_nearest_geometry` with the distance. A label that names
  a *corroborated* water body still wins. 38 of 40 resolve to named rivers;
  two are more than 1.7 km from anything mapped and stay unclassified.
* **Outages are recorded, not raised.** The feed intermittently returns a
  truncated body. Three retries with backoff, then the run is marked failed
  against the source, the previous data is untouched, and
  `GET /api/v1/water-jobs` shows the failure.

## Jobs and their schedules

| Command | Cadence | Why |
|---|---|---|
| `sync-water-data --provider cpcb_rtwqms --all` | hourly | the analysers publish hourly |
| `sync-water-data --provider cpcb_nwdp --all` | weekly | monthly extracts at most; unchanged resources cost one request each |
| `sync-water-data --provider cwc_nwdp --all` | weekly | as above |
| `import-geometry --file <extract>` | after an ingest that created water bodies | matches new bodies, and re-matches anything a merge left `stale_after_merge` |
| `process-satellite --limit N` | weekly | Sentinel-2 revisits every five days; most passes are rejected for cloud |
| `archive-evidence` | after `process-satellite` | copies rendered scenes into the object store |
| `reindex-water-rag` | on deploy | seeds reference regions and the research corpus, and builds the index |
| `db upgrade` | before any deploy that carries a migration | the web container never migrates |

Every one of them writes a row in `ingestion_runs` with its type, counts and
errors. `cli jobs` and `GET /api/v1/water-jobs` report them, including when
each kind last succeeded -- the question that matters for a scheduled system.

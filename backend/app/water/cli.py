"""Command-line entry points for water data.

    python -m app.water.cli ingest --states MH DL KA
    python -m app.water.cli ingest --all --provider cwc_nwdp
    python -m app.water.cli ingest --all
    python -m app.water.cli refresh-status
    python -m app.water.cli health
    python -m app.water.cli seed-standards
    python -m app.water.cli db upgrade | current | copy-from-sqlite | sync-geometry
    python -m app.water.cli extract-osm --pbf data/raw/osm/india-latest.osm.pbf
    python -m app.water.cli import-geometry --file data/processed/india-water.ndjson
    python -m app.water.cli geometry-qa
    python -m app.water.cli reconcile
    python -m app.water.cli import-boundaries [--offline]
    python -m app.water.cli import-cities
    python -m app.water.cli coverage [--markdown PATH]
    python -m app.water.cli import-classifications --file prs.csv --year 2025 \
        --reference "CPCB PRS report 2025, Annexure I"
    python -m app.water.cli fetch-imagery [--slug hussain-sagar-lake] [--limit N]
    python -m app.water.cli fetch-geometry [--state MH] [--slug mithi-river] [--limit N]

This is the manual sync the platform uses in place of a scheduler. CPCB
publishes monthly at best, and the extracts on the portal currently lag by
years, so a cron job firing daily would only re-confirm that nothing changed.
A manual command, run when the source is known to have published, respects the
source's actual cadence. ``ingest`` is idempotent, so running it again is safe.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.core.logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from alembic.config import Config


def _ingest(
    states: list[str] | None,
    provider: str = "cpcb_nwdp",
    *,
    incremental: bool = True,
    reassign_identity: bool = False,
) -> int:
    from app.services.water_service import refresh_cached_statuses
    from app.water.ingestion import ingest_provider

    init_db()
    with SessionLocal() as db:
        from app.water.reference_seed import seed_reference_standards

        seed_reference_standards(db)
        summary = ingest_provider(
            db,
            provider,
            states=states,
            incremental=incremental,
            reassign_identity=reassign_identity,
        )
        summary["statuses_refreshed"] = refresh_cached_statuses(db)
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["status"] != "failed" else 1


def _refresh() -> int:
    from app.services.water_service import refresh_cached_statuses

    init_db()
    with SessionLocal() as db:
        print(f"Refreshed {refresh_cached_statuses(db)} water-body statuses.")
    return 0


def _reconcile() -> int:
    from sqlalchemy import select

    from app.models.water import WaterBody
    from app.services.water_service import refresh_cached_statuses
    from app.water.ingestion import (
        _recompute_denormalised,
        link_river_fragments,
        prune_empty_bodies,
    )

    init_db()
    with SessionLocal() as db:
        linked = link_river_fragments(db)
        touched = set(
            db.scalars(select(WaterBody.id).where(WaterBody.id.in_(linked["touched"])))
        )
        _recompute_denormalised(db, touched, set())
        db.commit()
        print(
            json.dumps(
                {
                    "river_fragments_linked": linked["merged"],
                    # Records left holding nothing after an identity change.
                    "empty_bodies_pruned": prune_empty_bodies(db),
                    "statuses_refreshed": refresh_cached_statuses(db),
                }
            )
        )
    return 0


def _alembic_config() -> Config:
    """Alembic configuration anchored at the backend directory."""
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    return config


def _db(action: str, sqlite_url: str | None) -> int:
    """Migrations and the SQLite -> PostgreSQL transfer."""
    from alembic import command

    from app.core.database import SessionLocal, engine
    from app.core.dbinfo import backend_info
    from app.db.transfer import (
        city_extents_from_districts,
        copy_sqlite_to_postgres,
        sync_geometry,
    )

    info = backend_info()
    print(f"Database backend: {info.label}")

    if action == "current":
        command.current(_alembic_config(), verbose=True)
        return 0
    if action == "upgrade":
        command.upgrade(_alembic_config(), "head")
        print("Schema at head.")
        return 0
    if action == "copy-from-sqlite":
        if not sqlite_url:
            print("--sqlite-url is required, e.g. sqlite:///../data/oip.db")
            return 2
        counts = copy_sqlite_to_postgres(sqlite_url, engine)
        print(json.dumps({k: v for k, v in counts.items() if v}, indent=2))
        return 0
    if action == "sync-geometry":
        with SessionLocal() as db:
            updated = sync_geometry(db)
            extents = city_extents_from_districts(db)
        print(json.dumps({**updated, "city_extents": extents}, indent=2))
        return 0
    print(f"Unknown db action {action!r}.")
    return 2


def _extract_osm(pbf: str, out: str | None, cache: str | None) -> int:
    """One pass over an OSM extract, writing named water features."""
    from app.water.osm_extract import write_features

    pbf_path = Path(pbf)
    if not pbf_path.exists():
        print(f"{pbf_path} not found. Download a regional extract first, e.g.")
        print("  curl -L -o data/raw/osm/india-latest.osm.pbf \\")
        print("       https://download.geofabrik.de/asia/india-latest.osm.pbf")
        return 2
    out_path = Path(out) if out else pbf_path.with_suffix(".water.ndjson")
    # A country-sized extract holds more node locations than fit comfortably
    # in memory, so the cache goes on disk unless told otherwise.
    if cache is None:
        big = pbf_path.stat().st_size > 400_000_000
        cache = (
            f"sparse_file_array,{out_path.with_suffix('.nodecache')}"
            if big
            else "flex_mem"
        )
    print(
        f"Reading {pbf_path.name} ({pbf_path.stat().st_size / 1e6:.0f} MB), cache={cache}"
    )
    meta = write_features(pbf_path, out_path, cache=cache)
    print(json.dumps(meta, indent=2))
    return 0


def _import_geometry(
    path: str, water_types: list[str] | None, limit: int | None, only_missing: bool
) -> int:
    """Match bulk OSM water features to water bodies, with no network calls."""
    from app.water.geometry_import import import_geometry

    file_path = Path(path)
    if not file_path.exists():
        print(f"{file_path} not found. Run 'extract-osm' first.")
        return 2
    from app.water.jobs import GEOMETRY, record_job

    init_db()
    with (
        SessionLocal() as db,
        record_job(db, GEOMETRY, source_key="osm_extract") as counters,
    ):
        summary = import_geometry(
            db,
            file_path,
            water_types=water_types,
            limit=limit,
            only_missing=only_missing,
        )
        counters.records_seen = summary.get("bodies_considered", 0)
        counters.records_inserted = summary.get("matched", 0)
        counters.records_skipped = (
            summary.get("no_candidates", 0)
            + summary.get("not_near_stations", 0)
            + summary.get("no_station_coordinates", 0)
        )
        counters.records_rejected = summary.get("ambiguous", 0) + summary.get(
            "name_too_generic", 0
        )
        counters.detail = summary
    print(json.dumps(summary, indent=2))
    return 0


def _geometry_qa(fix: bool) -> int:
    """Report geometry that fails validation."""
    from app.water.geometry_qa import run_checks

    init_db()
    with SessionLocal() as db:
        report = run_checks(db, repair=fix)
    print(json.dumps(report, indent=2, default=str))
    return 0


def _seed_standards() -> int:
    from app.water.reference_seed import seed_reference_standards

    init_db()
    with SessionLocal() as db:
        print(f"Seeded {seed_reference_standards(db)} reference standards.")
    return 0


def _import_boundaries(offline: bool) -> int:
    from app.water.boundaries import import_boundaries

    init_db()
    with SessionLocal() as db:
        print(json.dumps(import_boundaries(db, offline=offline), indent=2))
    return 0


def _import_cities() -> int:
    from app.water.cities import import_cities

    init_db()
    with SessionLocal() as db:
        print(json.dumps(import_cities(db), indent=2))
    return 0


def _coverage(markdown: str | None) -> int:
    from pathlib import Path

    from app.water.coverage import coverage_report, render_markdown

    init_db()
    with SessionLocal() as db:
        report = coverage_report(db)
    if markdown:
        Path(markdown).write_text(render_markdown(report), encoding="utf-8")
        print(f"Wrote {markdown}")
    else:
        print(json.dumps(report["totals"], indent=2))
    return 0


def _fetch_geometry(
    state: str | None,
    slugs: list[str] | None,
    limit: int | None,
    water_types: list[str] | None = None,
) -> int:
    from app.water.geometry import prefetch

    init_db()
    with SessionLocal() as db:
        counts = prefetch(
            db, state_code=state, slugs=slugs, limit=limit, water_types=water_types
        )
    print(json.dumps(counts, indent=2))
    return 0


def _import_classifications(path: str, source: str, year: int, reference: str) -> int:
    from pathlib import Path

    from app.services.water_service import refresh_cached_statuses
    from app.water.classifications import import_prs_csv

    init_db()
    with SessionLocal() as db:
        report = import_prs_csv(
            db,
            Path(path),
            source=source,
            assessment_year=year,
            source_reference=reference,
        )
        summary = report.to_dict()
        summary["statuses_refreshed"] = refresh_cached_statuses(db)
    print(json.dumps(summary, indent=2))
    return 0 if not report.rejected else 1


def _fetch_imagery(slugs: list[str] | None, limit: int | None) -> int:
    from sqlalchemy import select

    from app.models.water import WaterBody
    from app.models.water_geo import WaterBodyGeometry
    from app.water.jobs import SATELLITE, record_job
    from app.water.satellite import fetch_imagery

    init_db()
    counts: dict[str, int] = {}
    with (
        SessionLocal() as db,
        record_job(db, SATELLITE, source_key="sentinel2_l2a") as counters,
    ):
        query = (
            select(WaterBody)
            .join(WaterBodyGeometry, WaterBodyGeometry.water_body_id == WaterBody.id)
            .where(WaterBodyGeometry.geometry_type.in_(["Polygon", "MultiPolygon"]))
            .order_by(WaterBody.observation_count.desc())
        )
        if slugs:
            query = select(WaterBody).where(WaterBody.slug.in_(slugs))
        if limit:
            query = query.limit(limit)
        bodies = db.scalars(query).all()
        for body in bodies:
            outcome = fetch_imagery(db, body)
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            print(f"{body.slug}: {outcome.status} -- {outcome.detail}")
        counters.records_seen = len(bodies)
        counters.records_inserted = counts.get("retrieved", 0)
        # A lake with no cloud-free scene over it is skipped, not failed:
        # nothing was wrong, the sky was in the way.
        counters.records_skipped = counts.get("no_scene", 0)
        counters.records_rejected = sum(
            n for status, n in counts.items() if status not in {"retrieved", "no_scene"}
        )
        counters.detail = dict(counts)
    print(json.dumps(counts, indent=2))
    return 0


def _reindex_water_rag() -> int:
    """Seed the reference regions and the research corpus, and check retrieval.

    This is what start-up used to do on every boot. On a server database it is
    a job instead: the rows are the same for every task, so one writer is
    enough, and a container must not be the thing that writes them.
    """
    from app.demo.seed import bootstrap
    from app.rag.service import build_index, corpus_size, ingest_seed_corpus
    from app.water.jobs import RAG_INDEX, record_job

    init_db()
    with SessionLocal() as db, record_job(db, RAG_INDEX, source_key="seed_corpus") as c:
        bootstrap(db)
        summary = ingest_seed_corpus(db)
        documents, chunks = corpus_size(db)
        # Build the index once here so a broken corpus fails in the job rather
        # than on a user's first question.
        index = build_index(db)
        summary["indexed_chunks"] = len(index.chunks)
        c.records_seen = summary.get("seed_documents", 0)
        c.records_inserted = summary.get("chunks_written", 0)
        c.detail = {**summary, "documents": documents, "chunks": chunks}
    print(json.dumps(summary, indent=2))
    return 0


def _jobs(limit: int, job_type: str | None) -> int:
    """Recent job runs, newest first."""
    from sqlalchemy import select

    from app.models.water import IngestionRun

    init_db()
    with SessionLocal() as db:
        query = select(IngestionRun).order_by(IngestionRun.started_at.desc())
        if job_type:
            query = query.where(IngestionRun.job_type == job_type)
        rows = db.scalars(query.limit(limit)).all()
        runs = [
            {
                "job_id": r.run_id,
                "job_type": r.job_type,
                "source": r.source_key,
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "seconds": (
                    round((r.finished_at - r.started_at).total_seconds(), 1)
                    if r.finished_at and r.started_at
                    else None
                ),
                "records_seen": r.records_seen,
                "records_inserted": r.records_inserted,
                "records_updated": r.records_updated,
                "records_skipped": r.records_skipped,
                "records_duplicate": r.records_duplicate,
                "records_rejected": r.records_rejected,
                "errors": r.errors,
            }
            for r in rows
        ]
    print(json.dumps(runs, indent=2))
    return 0


def _archive_evidence(limit: int | None) -> int:
    """Copy rendered scene images into the object store, once each.

    The pictures are rendered on demand by an external service, which is why
    the platform works with an empty store. This makes the evidence survive
    that service: the bytes go to the object store and the reference goes
    beside the metadata. Already-archived scenes are skipped, so it is safe to
    re-run over everything.
    """
    from sqlalchemy import select

    from app.core.objects import get_object_store
    from app.models.water_geo import WaterImage
    from app.water.jobs import SATELLITE, record_job
    from app.water.satellite import archive_scene_image

    init_db()
    store = get_object_store()
    with (
        SessionLocal() as db,
        record_job(db, SATELLITE, source_key="evidence_archive") as c,
    ):
        query = select(WaterImage).order_by(WaterImage.acquisition_date.desc())
        if limit:
            query = query.limit(limit)
        images = list(db.scalars(query))
        archived = skipped = failed = 0
        for image in images:
            before = (image.image_metadata or {}).get("object")
            result = archive_scene_image(db, image)
            if before is not None:
                skipped += 1
            elif result is not None:
                archived += 1
            else:
                failed += 1
        c.records_seen = len(images)
        c.records_inserted = archived
        c.records_skipped = skipped
        c.records_rejected = failed
        c.detail = {"backend": store.backend, "bucket": store.bucket}
    print(
        json.dumps(
            {
                "scenes": len(images),
                "archived": archived,
                "already_archived": skipped,
                "unavailable": failed,
                "backend": store.backend,
            },
            indent=2,
        )
    )
    return 0


def _health() -> int:
    from app.water.providers import all_providers

    worst = 0
    for provider in all_providers():
        ok, detail = provider.health()
        # The same four states the Data Sources page uses, so the two cannot
        # disagree about the same feed. A server that answers and refuses is
        # not down: reporting it as DOWN here while the page says "Sync
        # paused" would leave a reader unsure which to believe.
        if ok is None:
            label, rank = "UNKN  ", 1
        elif ok:
            label, rank = "LIVE  ", 0
        elif "403" in detail or "forbidden" in detail.lower():
            label, rank = "PAUSED", 1
        else:
            label, rank = "DOWN  ", 2
        worst = max(worst, rank)
        print(f"{provider.info.key:14} {label} {detail}")
    return 0 if worst == 0 else 1


def bootstrap_in_background() -> threading.Thread | None:
    """Ingest configured states at start-up if the water tables are empty.

    Returns the worker thread, or ``None`` when bootstrapping is disabled or
    unnecessary. A failure is logged and leaves the platform serving an empty
    but honest water section -- it never blocks start-up or health checks.
    """
    states = [s.strip().upper() for s in settings.water_bootstrap_states.split(",")]
    states = [s for s in states if s]
    if not states:
        return None

    from sqlalchemy import func, select

    from app.models.water import WaterQualityObservation

    with SessionLocal() as db:
        existing = db.scalar(select(func.count(WaterQualityObservation.id))) or 0
    if existing:
        return None

    def run() -> None:
        try:
            from app.services.water_service import refresh_cached_statuses
            from app.water.ingestion import ingest_provider

            with SessionLocal() as db:
                summary = ingest_provider(db, "cpcb_nwdp", states=states)
                refresh_cached_statuses(db)
            logger.info("water_bootstrap_complete", extra={"summary": summary})
        except Exception:
            logger.exception("water_bootstrap_failed", extra={"states": states})

    thread = threading.Thread(target=run, name="water-bootstrap", daemon=True)
    thread.start()
    logger.info("water_bootstrap_started", extra={"states": states})
    return thread


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch."""
    parser = argparse.ArgumentParser(prog="app.water.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    # Two spellings of one command. "sync-water-data" is the name the
    # deployment uses -- a scheduler runs a command, and "ingest" alone does
    # not say what it ingests -- while "ingest" is what the Phase 2 and
    # Phase 3 documentation says, so both work.
    for _name, _help in (
        ("ingest", "Ingest water-quality observations from a provider."),
        (
            "sync-water-data",
            "Ingest water-quality observations (the scheduled job's name).",
        ),
    ):
        ingest = sub.add_parser(_name, help=_help)
        group = ingest.add_mutually_exclusive_group(required=True)
        group.add_argument("--states", nargs="+", help="State codes, e.g. MH DL KA.")
        group.add_argument("--all", action="store_true", help="All 35 states (slow).")
        ingest.add_argument(
            "--full",
            action="store_true",
            help="Re-read every resource, ignoring the stored row counts.",
        )
        ingest.add_argument(
            "--reassign-identity",
            action="store_true",
            help=(
                "Move stations whose water body the current identity rule "
                "resolves differently, and list every move. For use after the "
                "rule changes; an ordinary ingest never re-points a station."
            ),
        )
        ingest.add_argument(
            "--provider",
            default="cpcb_nwdp",
            help="Registered provider key (cpcb_nwdp, cwc_nwdp).",
        )

    jobs = sub.add_parser("jobs", help="Recent job runs (any type), newest first.")
    jobs.add_argument("--limit", type=int, default=10)
    jobs.add_argument(
        "--type",
        dest="job_type",
        help="ingestion, geometry, satellite, rag_index or boundaries.",
    )

    sub.add_parser(
        "reindex-water-rag",
        help="Seed reference regions and the research corpus, then build the index.",
    )

    archive = sub.add_parser(
        "archive-evidence",
        help="Copy rendered satellite images into the object store.",
    )
    archive.add_argument("--limit", type=int, help="At most this many scenes.")

    sub.add_parser("refresh-status", help="Recompute cached water-body statuses.")
    sub.add_parser("health", help="Probe every registered provider.")
    sub.add_parser("seed-standards", help="Write the reference catalogue to the DB.")
    imp = sub.add_parser(
        "import-geometry", help="Match bulk OSM features to water bodies (offline)."
    )
    imp.add_argument("--file", required=True, help="Extract .ndjson from extract-osm.")
    imp.add_argument("--type", nargs="+", help="Only these water types.")
    imp.add_argument("--limit", type=int)
    imp.add_argument(
        "--only-missing", action="store_true", help="Skip bodies already matched."
    )
    qa = sub.add_parser("geometry-qa", help="Validate stored geometry.")
    qa.add_argument(
        "--fix", action="store_true", help="Repair what can be repaired, and log it."
    )
    osm = sub.add_parser(
        "extract-osm", help="Extract named water features from an OSM .pbf extract."
    )
    osm.add_argument("--pbf", required=True)
    osm.add_argument("--out", help="Output .ndjson (default: alongside the .pbf).")
    osm.add_argument("--cache", help="osmium node cache, e.g. flex_mem.")
    db_parser = sub.add_parser("db", help="Migrations and database transfer.")
    db_parser.add_argument(
        "action",
        choices=["upgrade", "current", "copy-from-sqlite", "sync-geometry"],
    )
    db_parser.add_argument(
        "--sqlite-url", help="Source for copy-from-sqlite, e.g. sqlite:///data/oip.db"
    )
    sub.add_parser("reconcile", help="Join river fragments split across states.")
    boundaries = sub.add_parser(
        "import-boundaries", help="Import geoBoundaries state and district polygons."
    )
    boundaries.add_argument(
        "--offline", action="store_true", help="Use cached files only; never download."
    )
    sub.add_parser("import-cities", help="Rebuild cities from the curated definitions.")
    classifications = sub.add_parser(
        "import-classifications",
        help="Import an official polluted-river-stretch table (CSV).",
    )
    classifications.add_argument("--file", required=True)
    classifications.add_argument(
        "--source", default="Central Pollution Control Board (PRS assessment)"
    )
    classifications.add_argument("--year", type=int, required=True)
    classifications.add_argument(
        "--reference", required=True, help="Where the table was taken from."
    )
    # Same command, two names: "process-satellite" is what the scheduler runs.
    for _name, _help in (
        ("fetch-imagery", "Retrieve Sentinel-2 scenes for matched lakes."),
        (
            "process-satellite",
            "Retrieve and score Sentinel-2 scenes (the scheduled job's name).",
        ),
    ):
        imagery = sub.add_parser(_name, help=_help)
        imagery.add_argument("--slug", nargs="+", help="Only these water bodies.")
        imagery.add_argument("--limit", type=int, help="At most this many bodies.")
    geometry = sub.add_parser(
        "fetch-geometry", help="Match OSM geometry to water bodies (Overpass)."
    )
    geometry.add_argument("--state", help="Only this state code.")
    geometry.add_argument("--slug", nargs="+", help="Only these water bodies.")
    geometry.add_argument("--limit", type=int, help="At most this many bodies.")
    geometry.add_argument("--type", nargs="+", help="Only these water types.")
    coverage = sub.add_parser("coverage", help="Report what the database holds.")
    coverage.add_argument("--markdown", help="Write DATASET_COVERAGE.md to this path.")

    args = parser.parse_args(argv)
    if args.command in {"ingest", "sync-water-data"}:
        return _ingest(
            None if args.all else [s.upper() for s in args.states],
            args.provider,
            incremental=not args.full,
            reassign_identity=args.reassign_identity,
        )
    if args.command == "jobs":
        return _jobs(args.limit, args.job_type)
    if args.command == "reindex-water-rag":
        return _reindex_water_rag()
    if args.command == "archive-evidence":
        return _archive_evidence(args.limit)
    if args.command == "refresh-status":
        return _refresh()
    if args.command == "reconcile":
        return _reconcile()
    if args.command == "import-geometry":
        return _import_geometry(args.file, args.type, args.limit, args.only_missing)
    if args.command == "geometry-qa":
        return _geometry_qa(args.fix)
    if args.command == "extract-osm":
        return _extract_osm(args.pbf, args.out, args.cache)
    if args.command == "db":
        return _db(args.action, args.sqlite_url)
    if args.command == "seed-standards":
        return _seed_standards()
    if args.command == "import-boundaries":
        return _import_boundaries(args.offline)
    if args.command == "import-cities":
        return _import_cities()
    if args.command == "import-classifications":
        return _import_classifications(args.file, args.source, args.year, args.reference)
    if args.command in {"fetch-imagery", "process-satellite"}:
        return _fetch_imagery(args.slug, args.limit)
    if args.command == "fetch-geometry":
        return _fetch_geometry(args.state, args.slug, args.limit, args.type)
    if args.command == "coverage":
        return _coverage(args.markdown)
    return _health()


if __name__ == "__main__":
    sys.exit(main())

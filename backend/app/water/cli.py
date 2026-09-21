"""Command-line entry points for water data.

    python -m app.water.cli ingest --states MH DL KA
    python -m app.water.cli ingest --all
    python -m app.water.cli refresh-status
    python -m app.water.cli health

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

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.core.logging import get_logger

logger = get_logger(__name__)


def _ingest(states: list[str] | None) -> int:
    from app.services.water_service import refresh_cached_statuses
    from app.water.ingestion import ingest_provider

    init_db()
    with SessionLocal() as db:
        summary = ingest_provider(db, "cpcb_nwdp", states=states)
        summary["statuses_refreshed"] = refresh_cached_statuses(db)
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["status"] != "failed" else 1


def _refresh() -> int:
    from app.services.water_service import refresh_cached_statuses

    init_db()
    with SessionLocal() as db:
        print(f"Refreshed {refresh_cached_statuses(db)} water-body statuses.")
    return 0


def _health() -> int:
    from app.water.providers import all_providers

    ok_all = True
    for provider in all_providers():
        ok, detail = provider.health()
        ok_all &= ok
        print(f"{provider.info.key:14} {'OK  ' if ok else 'DOWN'} {detail}")
    return 0 if ok_all else 1


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

    ingest = sub.add_parser("ingest", help="Ingest CPCB observations from NWDP.")
    group = ingest.add_mutually_exclusive_group(required=True)
    group.add_argument("--states", nargs="+", help="State codes, e.g. MH DL KA.")
    group.add_argument("--all", action="store_true", help="All 35 states (slow).")

    sub.add_parser("refresh-status", help="Recompute cached water-body statuses.")
    sub.add_parser("health", help="Probe every registered provider.")

    args = parser.parse_args(argv)
    if args.command == "ingest":
        return _ingest(None if args.all else [s.upper() for s in args.states])
    if args.command == "refresh-status":
        return _refresh()
    return _health()


if __name__ == "__main__":
    sys.exit(main())

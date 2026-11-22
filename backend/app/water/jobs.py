"""Job bookkeeping shared by every offline job.

The web application serves; everything expensive happens in a job. Phase 3
recorded only ingestion runs, so a geometry import, a satellite pass or a RAG
reindex left no trace of whether it ran, how long it took or what it did.

One row per run, in ``ingestion_runs`` (``job_type`` says which kind), so that
a single query answers "when did each job last succeed, and what did it do?".

The contract of :func:`record_job`:

* the row exists from the moment the job starts, so a job killed mid-run is
  visible as ``running`` rather than missing;
* a failure is recorded with its message and re-raised -- the caller decides
  whether to exit non-zero, and **no data is deleted**, so the last good
  ingest stays queryable after a failed one;
* the counters are whatever the job chooses to report, and the bookkeeping
  never invents them.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.water import IngestionRun

logger = get_logger(__name__)

# The job kinds this platform runs. Ingestion keeps its historical name so the
# Phase 2 and Phase 3 rows still mean what they say.
INGESTION = "ingestion"
GEOMETRY = "geometry"
SATELLITE = "satellite"
RAG_INDEX = "rag_index"
BOUNDARIES = "boundaries"


@dataclass
class JobCounters:
    """What a job reports about itself. Every field is optional."""

    records_seen: int = 0
    records_valid: int = 0
    records_inserted: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    records_rejected: int = 0
    records_duplicate: int = 0
    detail: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def apply(self, run: IngestionRun) -> None:
        """Copy the counters onto the run row."""
        run.records_seen = self.records_seen
        run.records_valid = self.records_valid
        run.records_inserted = self.records_inserted
        run.records_updated = self.records_updated
        run.records_skipped = self.records_skipped
        run.records_rejected = self.records_rejected
        run.records_duplicate = self.records_duplicate
        run.detail = {**(run.detail or {}), **self.detail}
        run.warnings = [*(run.warnings or []), *self.warnings]


def new_job_id() -> str:
    """A short, sortable-enough identifier for one run."""
    return uuid.uuid4().hex[:16]


@contextmanager
def record_job(
    db: Session, job_type: str, *, source_key: str = "internal"
) -> Iterator[JobCounters]:
    """Record one job run, whatever happens to it.

    Yields the counters for the job to fill in. On success the row is marked
    ``success``; on an exception it is marked ``failed`` with the message, and
    the exception is re-raised. Existing data is never touched by this
    bookkeeping: a failed run leaves the previous good data exactly as it was.
    """
    run_id = new_job_id()
    run = IngestionRun(
        run_id=run_id,
        job_type=job_type,
        source_key=source_key,
        started_at=datetime.now(UTC),
        status="running",
        errors=[],
        warnings=[],
        detail={},
    )
    db.add(run)
    db.commit()

    counters = JobCounters()
    try:
        yield counters
    except Exception as exc:
        # Roll back *first*. The session may be in a failed transaction that
        # rejects every further statement, and a rollback also discards
        # anything set on the row beforehand -- which is how an earlier
        # version of this wrote "running" over its own failure. So: clear the
        # transaction, re-read the row, then record the failure.
        db.rollback()
        failed = db.scalar(select(IngestionRun).where(IngestionRun.run_id == run_id))
        if failed is not None:
            failed.finished_at = datetime.now(UTC)
            failed.status = "failed"
            failed.errors = [f"{type(exc).__name__}: {exc}"[:500]]
            counters.apply(failed)
            db.commit()
        logger.error(
            "job_failed",
            extra={
                "job_id": run_id,
                "job_type": job_type,
                "error": str(exc)[:200],
            },
        )
        raise
    else:
        run.finished_at = datetime.now(UTC)
        run.status = "success"
        counters.apply(run)
        db.add(run)
        db.commit()
        logger.info(
            "job_complete",
            extra={
                "job_id": run_id,
                "job_type": job_type,
                "source": source_key,
                "seconds": round((run.finished_at - run.started_at).total_seconds(), 1),
                "records_seen": counters.records_seen,
                "records_inserted": counters.records_inserted,
                "records_skipped": counters.records_skipped,
            },
        )

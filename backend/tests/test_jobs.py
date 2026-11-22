"""Every offline job leaves a record, and a failed one destroys nothing.

Phase 3 tracked ingestion only, so a geometry import or a satellite pass left
no trace of whether it ran. These tests pin the three things an operator needs
from that record: it exists while the job is running, it is honest about
failure, and a failure leaves the previous data alone.
"""

from __future__ import annotations

import pytest
from app.models.water import IngestionRun
from app.water.jobs import GEOMETRY, SATELLITE, record_job
from sqlalchemy import select


def _runs(db) -> list[IngestionRun]:
    return list(db.scalars(select(IngestionRun).order_by(IngestionRun.started_at)))


class TestJobRecording:
    def test_a_successful_job_is_recorded_with_its_counters(self, db):
        with record_job(db, GEOMETRY, source_key="osm_extract") as counters:
            counters.records_seen = 1244
            counters.records_inserted = 405
            counters.records_skipped = 748
            counters.detail = {"extract": "india-latest.osm.pbf"}

        run = _runs(db)[-1]
        assert run.job_type == GEOMETRY
        assert run.source_key == "osm_extract"
        assert run.status == "success"
        assert run.finished_at is not None
        assert (run.records_seen, run.records_inserted, run.records_skipped) == (
            1244,
            405,
            748,
        )
        assert run.detail["extract"] == "india-latest.osm.pbf"

    def test_the_row_exists_while_the_job_is_still_running(self, db):
        """A job killed halfway must be visible, not missing."""
        with record_job(db, SATELLITE) as counters:
            counters.records_seen = 1
            in_flight = db.scalar(
                select(IngestionRun).where(IngestionRun.job_type == SATELLITE)
            )
            assert in_flight is not None
            assert in_flight.status == "running"
            assert in_flight.finished_at is None

    def test_job_types_are_distinguished(self, db):
        with record_job(db, GEOMETRY):
            pass
        with record_job(db, SATELLITE):
            pass
        assert {r.job_type for r in _runs(db)} == {GEOMETRY, SATELLITE}


class TestJobFailure:
    def test_a_failure_is_recorded_and_re_raised(self, db):
        with (
            pytest.raises(ValueError, match="provider unreachable"),
            record_job(db, GEOMETRY, source_key="osm_extract") as counters,
        ):
            counters.records_seen = 10
            raise ValueError("provider unreachable")

        run = _runs(db)[-1]
        assert run.status == "failed"
        assert run.finished_at is not None
        assert "provider unreachable" in run.errors[0]
        assert run.records_seen == 10, "what it managed before failing is kept"

    def test_a_failed_job_leaves_existing_data_alone(self, db):
        """The point of recording a failure instead of exiting silently."""
        from app.models.water import DataSource

        db.add(DataSource(key="keepme", name="Existing", organisation="Org"))
        db.commit()

        with pytest.raises(RuntimeError), record_job(db, GEOMETRY):
            raise RuntimeError("boom")

        survivors = db.scalars(select(DataSource)).all()
        assert [s.key for s in survivors] == ["keepme"]

    def test_the_last_successful_run_is_still_findable_after_a_failure(self, db):
        with record_job(db, GEOMETRY) as counters:
            counters.records_inserted = 405
        with pytest.raises(RuntimeError), record_job(db, GEOMETRY):
            raise RuntimeError("the next night's run failed")

        last_success = db.scalar(
            select(IngestionRun)
            .where(IngestionRun.job_type == GEOMETRY, IngestionRun.status == "success")
            .order_by(IngestionRun.finished_at.desc())
        )
        assert last_success is not None
        assert last_success.records_inserted == 405


class TestJobsEndpoint:
    def test_it_reports_runs_and_when_each_kind_last_succeeded(self, client, db):
        with record_job(db, GEOMETRY, source_key="osm_extract") as counters:
            counters.records_inserted = 405

        payload = client.get("/api/v1/water-jobs").json()
        assert payload["runs"], "the run just recorded must be listed"
        newest = payload["runs"][0]
        assert newest["job_type"] == GEOMETRY
        assert newest["records_inserted"] == 405
        assert newest["duration_seconds"] is not None
        assert GEOMETRY in payload["last_success_by_job"]

    def test_it_can_be_filtered_by_job_type(self, client, db):
        with record_job(db, GEOMETRY):
            pass
        with record_job(db, SATELLITE):
            pass
        payload = client.get(f"/api/v1/water-jobs?job_type={SATELLITE}").json()
        assert {r["job_type"] for r in payload["runs"]} == {SATELLITE}

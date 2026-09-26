"""When a source goes away, nothing is lost and nothing is invented.

The real-time feed is the one source that can make the platform say "right
now", and it is also the one most likely to be briefly unavailable -- it has
already returned a truncated body during this work. So the behaviour when it
fails matters as much as the behaviour when it works:

* the last stored reading stays exactly where it is;
* the application keeps answering, from what it has;
* the failure is recorded against the source, so its state is visible;
* no observation appears that the source did not publish.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.models.water import DataSource, IngestionRun, WaterQualityObservation
from app.water import providers as provider_registry
from app.water.freshness import Cadence
from app.water.ingestion import ingest_provider
from app.water.providers.base import (
    FetchPlan,
    ObservationRow,
    ProviderInfo,
    ProviderUnavailableError,
    WaterDataProvider,
)
from sqlalchemy import func, select

GOOD = datetime(2026, 9, 26, 13, 30, tzinfo=UTC)


def _row() -> ObservationRow:
    return ObservationRow(
        station_name="River Ganga at Chausa",
        parameter_key="bod",
        observed_at=GOOD,
        value=2.52,
        normalized_value=2.52,
        unit="mg/L",
        normalized_unit="mg/L",
        latitude=25.5193,
        longitude=83.9007,
        state_name="Bihar",
        state_code="BR",
        source_reference="test:bod:1",
    )


class _Flaky(WaterDataProvider):
    """A live feed that can be told to fall over, at either stage."""

    fail_planning = False
    fail_fetch = False

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            key="flaky_realtime",
            name="Flaky Real-Time Agency",
            organisation="Flaky",
            cadence=Cadence.HOURLY,
            source_type="government",
            observation_method="continuous_sensor",
        )

    def plans(self, *, states: list[str] | None = None) -> list[FetchPlan]:
        if type(self).fail_planning:
            raise ProviderUnavailableError("feed returned a truncated body")
        return [FetchPlan(identifier="one", description="one", state_code="BR")]

    def resource_total(self, plan: FetchPlan) -> int | None:
        return None

    def fetch(self, plan: FetchPlan) -> Iterator[ObservationRow]:
        if type(self).fail_fetch:
            raise ProviderUnavailableError("connection reset mid-page")
        yield _row()


@pytest.fixture
def flaky(monkeypatch):
    _Flaky.fail_planning = False
    _Flaky.fail_fetch = False
    monkeypatch.setitem(provider_registry.PROVIDERS, "flaky_realtime", _Flaky)
    return _Flaky


def _observations(db) -> int:
    return db.scalar(select(func.count(WaterQualityObservation.id))) or 0


class TestTheFeedGoesAway:
    def test_a_planning_failure_is_recorded_not_raised(self, db, flaky):
        ingest_provider(db, "flaky_realtime")
        assert _observations(db) == 1

        flaky.fail_planning = True
        summary = ingest_provider(db, "flaky_realtime")

        assert summary["status"] == "failed"
        assert "truncated body" in summary["errors"][0]
        assert _observations(db) == 1, "the stored reading is untouched"

    def test_a_fetch_failure_leaves_the_previous_data_alone(self, db, flaky):
        ingest_provider(db, "flaky_realtime")
        before = _observations(db)

        flaky.fail_fetch = True
        summary = ingest_provider(db, "flaky_realtime")

        assert summary["status"] in {"failed", "partial"}
        assert _observations(db) == before

    def test_the_source_is_marked_unavailable_so_its_state_is_visible(self, db, flaky):
        ingest_provider(db, "flaky_realtime")
        flaky.fail_planning = True
        ingest_provider(db, "flaky_realtime")

        source = db.scalar(select(DataSource).where(DataSource.key == "flaky_realtime"))
        assert source.is_available is False
        assert source.last_error

    def test_nothing_is_invented_while_the_source_is_down(self, db, flaky):
        ingest_provider(db, "flaky_realtime")
        stored = db.scalars(select(WaterQualityObservation)).all()
        assert len(stored) == 1
        assert stored[0].observed_at.replace(tzinfo=UTC) == GOOD

        flaky.fail_planning = True
        ingest_provider(db, "flaky_realtime")

        after = db.scalars(select(WaterQualityObservation)).all()
        assert len(after) == 1
        assert after[0].observed_at.replace(tzinfo=UTC) == GOOD, (
            "no fresher timestamp appeared while the source was unreachable"
        )

    def test_recovery_resumes_without_duplicating(self, db, flaky):
        ingest_provider(db, "flaky_realtime")
        flaky.fail_planning = True
        ingest_provider(db, "flaky_realtime")
        flaky.fail_planning = False
        summary = ingest_provider(db, "flaky_realtime")

        assert summary["status"] == "success"
        assert summary["records_inserted"] == 0
        assert summary["records_duplicate"] == 1
        assert _observations(db) == 1

    def test_every_attempt_is_in_the_job_record(self, db, flaky):
        ingest_provider(db, "flaky_realtime")
        flaky.fail_planning = True
        ingest_provider(db, "flaky_realtime")

        runs = db.scalars(
            select(IngestionRun)
            .where(IngestionRun.source_key == "flaky_realtime")
            .order_by(IngestionRun.started_at)
        ).all()
        assert [r.status for r in runs] == ["success", "failed"]
        assert runs[1].errors

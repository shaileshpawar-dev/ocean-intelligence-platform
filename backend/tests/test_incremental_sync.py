"""Running ingestion twice must not duplicate a single observation.

Two separate mechanisms have to hold for that to be true, and they are tested
separately here because they fail differently:

* **the uniqueness key** -- (source, station, parameter, observed_at) -- which
  is what stops a duplicate row even when the provider hands back the same
  record twice;
* **the resource cursor** -- the stored row count per resource -- which is
  what stops the second run from paging four million rows to discover it had
  nothing to do.

A provider that stops reporting a row count still has to be safe: the first
mechanism does not depend on the second.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from app.models.water import SourceResourceState, WaterQualityObservation
from app.water import providers as provider_registry
from app.water.freshness import Cadence
from app.water.ingestion import ingest_provider
from app.water.providers.base import (
    FetchPlan,
    ObservationRow,
    ProviderInfo,
    WaterDataProvider,
)
from sqlalchemy import func, select

WHEN = datetime(2025, 4, 21, 8, 30, tzinfo=UTC)


def _row(parameter: str, value: float, when: datetime) -> ObservationRow:
    return ObservationRow(
        station_name="TEST RIVER AT SOMEWHERE",
        parameter_key=parameter,
        observed_at=when,
        value=value,
        normalized_value=value,
        unit="mg/L",
        normalized_unit="mg/L",
        latitude=19.05,
        longitude=72.85,
        state_name="Maharashtra",
        state_code="MH",
        source_reference=f"test:{parameter}:{when.isoformat()}",
    )


class _Counting(WaterDataProvider):
    """A provider that records how often it was actually paged."""

    fetches = 0
    rows_per_fetch = 3
    total_rows: int | None = 3

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            key="counting_source",
            name="Counting Agency",
            organisation="Counting",
            cadence=Cadence.MONTHLY,
            source_type="government",
        )

    def plans(self, *, states: list[str] | None = None) -> list[FetchPlan]:
        return [FetchPlan(identifier="res-1", description="one", state_code="MH")]

    def resource_total(self, plan: FetchPlan) -> int | None:
        return self.total_rows

    def fetch(self, plan: FetchPlan) -> Iterator[ObservationRow]:
        type(self).fetches += 1
        for index in range(self.rows_per_fetch):
            yield _row("bod", 2.0 + index, WHEN + timedelta(days=index))


@pytest.fixture
def provider(monkeypatch):
    _Counting.fetches = 0
    _Counting.rows_per_fetch = 3
    _Counting.total_rows = 3
    monkeypatch.setitem(provider_registry.PROVIDERS, "counting_source", _Counting)
    return _Counting


def _observations(db) -> int:
    return db.scalar(select(func.count(WaterQualityObservation.id))) or 0


class TestRunningTwice:
    def test_the_second_run_inserts_nothing_new(self, db, provider):
        first = ingest_provider(db, "counting_source")
        assert first["records_inserted"] == 3
        after_first = _observations(db)

        second = ingest_provider(db, "counting_source")
        assert second["records_inserted"] == 0
        assert _observations(db) == after_first == 3

    def test_the_second_run_does_not_page_the_source_at_all(self, db, provider):
        ingest_provider(db, "counting_source")
        assert provider.fetches == 1
        ingest_provider(db, "counting_source")
        assert provider.fetches == 1, "unchanged row count means nothing to read"

    def test_the_skip_is_counted_not_hidden(self, db, provider):
        ingest_provider(db, "counting_source")
        second = ingest_provider(db, "counting_source")
        assert second["plans_completed"] == 0
        from app.models.water import IngestionRun

        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_id == second["run_id"])
        )
        assert run.records_skipped == 1
        assert run.detail["plans_skipped_unchanged"] == 1

    def test_the_cursor_is_stored_per_resource(self, db, provider):
        ingest_provider(db, "counting_source")
        state = db.scalar(
            select(SourceResourceState).where(
                SourceResourceState.source_key == "counting_source"
            )
        )
        assert state.resource_id == "res-1"
        assert state.last_total == 3
        assert state.last_ingested_at is not None


class TestDuplicatesAreImpossibleAnyway:
    def test_forcing_a_full_re_read_still_inserts_nothing(self, db, provider):
        """--full bypasses the cursor; the uniqueness key must still hold."""
        ingest_provider(db, "counting_source")
        second = ingest_provider(db, "counting_source", incremental=False)
        assert provider.fetches == 2, "the source really was read again"
        assert second["records_inserted"] == 0
        assert second["records_duplicate"] == 3
        assert _observations(db) == 3

    def test_a_provider_with_no_row_count_is_still_safe(self, db, provider):
        """No cursor available, so every run re-reads -- and still no duplicates."""
        provider.total_rows = None
        ingest_provider(db, "counting_source")
        ingest_provider(db, "counting_source")
        assert provider.fetches == 2
        assert _observations(db) == 3

    def test_new_records_still_arrive_when_the_source_grows(self, db, provider):
        ingest_provider(db, "counting_source")
        provider.rows_per_fetch = 5
        provider.total_rows = 5
        third = ingest_provider(db, "counting_source")
        assert third["records_inserted"] == 2, "only the two new days"
        assert _observations(db) == 5

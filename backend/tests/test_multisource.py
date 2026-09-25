"""Two sources on one water body: kept apart, newest named, never blended.

The situation is real: CPCB's published extract for a river stops in 2021
while the Central Water Commission sampled the same river in 2025. The
platform must show both, say which is newer, and never average them into a
single number or draw one line through both.

The fixtures here are two fake providers over the same station labels.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.models.water import WaterBody
from app.services import water_service as ws
from app.water import providers as provider_registry
from app.water.freshness import Cadence
from app.water.ingestion import ingest_provider
from app.water.providers.base import (
    FetchPlan,
    ObservationRow,
    ProviderInfo,
    WaterDataProvider,
)
from app.water.rag import answer
from sqlalchemy import select

OLD = datetime(2021, 12, 2, 8, 30, tzinfo=UTC)
NEW = datetime(2025, 4, 21, 8, 30, tzinfo=UTC)


def _row(parameter: str, value: float, when: datetime) -> ObservationRow:
    return ObservationRow(
        station_name="MITHI RIVER MAHIM BANDRA MUMBAI",
        parameter_key=parameter,
        observed_at=when,
        value=value,
        normalized_value=value,
        unit="mg/L",
        normalized_unit="mg/L",
        latitude=19.0517,
        longitude=72.8484,
        state_name="Maharashtra",
        state_code="MH",
        district="Mumbai Suburban",
        source_reference=f"test:{parameter}:{when.date()}",
    )


class _Older(WaterDataProvider):
    """Stands in for CPCB: thorough, but stops years ago."""

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            key="older_source",
            name="Older Agency Water Quality",
            organisation="Older Agency",
            cadence=Cadence.MONTHLY,
            source_type="government",
            observation_method="manual_grab_sample",
        )

    def plans(self, *, states: list[str] | None = None) -> list[FetchPlan]:
        return [FetchPlan(identifier="old", description="old", state_code="MH")]

    def fetch(self, plan: FetchPlan) -> Iterator[ObservationRow]:
        yield _row("bod", 12.0, OLD)
        yield _row("dissolved_oxygen", 1.5, OLD)


class _Newer(WaterDataProvider):
    """Stands in for CWC: fewer parameters, but recent."""

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            key="newer_source",
            name="Newer Agency Water Quality",
            organisation="Newer Agency",
            cadence=Cadence.MONTHLY,
            source_type="government",
            observation_method="manual_grab_sample",
        )

    def plans(self, *, states: list[str] | None = None) -> list[FetchPlan]:
        return [FetchPlan(identifier="new", description="new", state_code="MH")]

    def fetch(self, plan: FetchPlan) -> Iterator[ObservationRow]:
        yield _row("bod", 2.0, NEW)


@pytest.fixture
def two_sources(db, monkeypatch):
    """One water body measured by two agencies, years apart."""
    monkeypatch.setitem(provider_registry.PROVIDERS, "older_source", _Older)
    monkeypatch.setitem(provider_registry.PROVIDERS, "newer_source", _Newer)
    ingest_provider(db, "older_source")
    ingest_provider(db, "newer_source")
    ws.refresh_cached_statuses(db)
    return db


def _mithi(db) -> WaterBody:
    return db.scalar(select(WaterBody).where(WaterBody.slug == "mithi-river"))


class TestBothSourcesKept:
    def test_neither_source_overwrites_the_other(self, two_sources):
        body = _mithi(two_sources)
        sources = ws.latest_by_source(two_sources, body)
        assert {s["key"] for s in sources} == {"older_source", "newer_source"}
        # Newest first.
        assert sources[0]["key"] == "newer_source"
        assert sources[0]["latest_observed_at"].startswith("2025-04-21")
        assert sources[1]["latest_observed_at"].startswith("2021-12-02")

    def test_both_rows_exist_for_the_same_parameter(self, two_sources):
        body = _mithi(two_sources)
        trend = ws.parameter_trend(two_sources, body.slug, "bod")
        by_source = {p["source"] for p in trend["points"]}
        assert by_source == {"older_source", "newer_source"}
        assert len(trend["points"]) == 2

    def test_status_uses_the_newest_value_and_says_whose(self, two_sources):
        body = _mithi(two_sources)
        result = ws.compute_status(two_sources, body, as_of_observation=True)
        bod = next(m for m in result.measurements if m.parameter_key == "bod")
        assert bod.value == 2.0, "the 2025 reading, not the 2021 one"
        assert bod.source == "Newer Agency Water Quality"
        # The older agency's dissolved oxygen is still used: it is the only
        # measurement of that parameter.
        oxygen = next(
            m for m in result.measurements if m.parameter_key == "dissolved_oxygen"
        )
        assert oxygen.source == "Older Agency Water Quality"

    def test_detail_names_the_newest_source(self, two_sources):
        detail = ws.get_water_body_detail(two_sources, "mithi-river")
        newest = detail["availability"]["newest_source"]
        assert newest["name"] == "Newer Agency Water Quality"
        assert newest["latest_observed_at"].startswith("2025-04-21")
        older = detail["availability"]["older_sources"]
        assert older[0]["name"] == "Older Agency Water Quality"


class TestAnswersExplainTheConflict:
    def test_answer_states_both_dates_and_does_not_blend(self, two_sources):
        payload = answer(
            two_sources, "What is the latest available status of Mithi River?"
        )
        section = payload["sections"][0]
        assert "Newer Agency" in section["newest_source"]
        assert "2025" in section["newest_source"]
        assert "Older Agency" in section["newest_source"]
        limitations = " ".join(payload["limitations"])
        assert "more than one agency" in limitations
        assert "never combined" in limitations

    def test_measured_layer_breaks_down_by_source(self, two_sources):
        payload = answer(two_sources, "What is the status of Mithi River?")
        layers = payload["sections"][0]["evidence_layers"]
        by_source = {s["name"]: s for s in layers["MEASURED"]["by_source"]}
        assert set(by_source) == {
            "Newer Agency Water Quality",
            "Older Agency Water Quality",
        }
        assert by_source["Newer Agency Water Quality"]["latest"].startswith("2025")

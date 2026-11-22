"""The summary cache must be fast, and must never be able to be wrong.

A water body's page asked its whole history four times per request: the
latest measurement of every parameter, the per-source counts, the per-source
recency, and the span and month count behind the data-quality panel. On the
Ganga's 347,672 observations that was 647 ms. The refresh-status job now
computes those once and stores them.

A cache that can serve a stale answer would be worse than a slow page, so
these tests pin the three properties that make it safe: it matches what the
live computation returns, it notices when it is out of date, and every reader
falls back rather than trusting it blindly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models.water import (
    DataSource,
    MonitoringStation,
    WaterBody,
    WaterQualityObservation,
)
from app.services import water_service as ws
from sqlalchemy import select

OLD = datetime(2021, 12, 2, 8, 30, tzinfo=UTC)
NEW = datetime(2026, 9, 26, 13, 30, tzinfo=UTC)


@pytest.fixture
def body_with_two_sources(db) -> WaterBody:
    """One river, two agencies, several parameters and dates."""
    lab = DataSource(
        key="lab", name="Lab Agency", organisation="Labs", expected_cadence="monthly"
    )
    sensor = DataSource(
        key="sensor",
        name="Sensor Agency",
        organisation="Sensors",
        expected_cadence="hourly",
    )
    db.add_all([lab, sensor])
    body = WaterBody(
        slug="cached-river",
        name="Cached River",
        normalized_name="CACHED",
        water_type="river",
        match_confidence=1.0,
        match_method="test",
        aliases=[],
        source_ids={},
    )
    db.add(body)
    db.flush()
    station = MonitoringStation(
        station_code="C:1",
        name="Cached at Test",
        slug="cached-at-test",
        source_id=lab.id,
        water_body_id=body.id,
        latitude=20.0,
        longitude=78.0,
    )
    db.add(station)
    db.flush()

    rows = []
    # The lab measured three parameters across two years.
    for index, parameter in enumerate(("bod", "ph", "dissolved_oxygen")):
        for month in range(3):
            rows.append(
                WaterQualityObservation(
                    source_id=lab.id,
                    station_id=station.id,
                    water_body_id=body.id,
                    parameter=parameter,
                    observed_at=OLD + timedelta(days=30 * month),
                    value=5.0 + index,
                    normalized_value=5.0 + index,
                    unit="mg/L",
                    normalized_unit="mg/L",
                    quality_flag="ok",
                    retrieved_at=OLD,
                )
            )
    # The sensor measured one parameter, today.
    rows.append(
        WaterQualityObservation(
            source_id=sensor.id,
            station_id=station.id,
            water_body_id=body.id,
            parameter="bod",
            observed_at=NEW,
            value=2.0,
            normalized_value=2.0,
            unit="mg/L",
            normalized_unit="mg/L",
            quality_flag="ok",
            retrieved_at=NEW,
        )
    )
    db.add_all(rows)
    body.observation_count = len(rows)
    db.commit()
    return body


class TestTheCacheMatchesTheLiveComputation:
    def test_per_source_summary_is_identical(self, db, body_with_two_sources):
        live = ws.build_summary(db, body_with_two_sources)
        bulk = ws.build_all_summaries(db)[body_with_two_sources.id]

        def shape(summary: dict) -> list[tuple]:
            return sorted(
                (
                    s["key"],
                    s["observation_count"],
                    s["parameter_count"],
                    s["first_observed_at"],
                    s["latest_observed_at"],
                )
                for s in summary["sources"]
            )

        assert shape(bulk) == shape(live)

    def test_latest_measurement_per_parameter_is_identical(
        self, db, body_with_two_sources
    ):
        live = {
            m["parameter"]: m
            for m in ws.build_summary(db, body_with_two_sources)["measurements"]
        }
        bulk = {
            m["parameter"]: m
            for m in ws.build_all_summaries(db)[body_with_two_sources.id]["measurements"]
        }
        assert set(bulk) == set(live) == {"bod", "ph", "dissolved_oxygen"}
        # BOD's newest reading is the sensor's, not the lab's.
        assert bulk["bod"]["value"] == 2.0
        assert bulk["bod"]["source"] == "Sensor Agency"
        assert bulk["bod"]["observed_at"].startswith("2026-09-26")

    def test_the_newest_source_is_first(self, db, body_with_two_sources):
        summary = ws.build_all_summaries(db)[body_with_two_sources.id]
        assert [s["key"] for s in summary["sources"]] == ["sensor", "lab"]


class TestStaleness:
    def test_a_fresh_cache_is_used(self, db, body_with_two_sources):
        ws.store_summary(db, body_with_two_sources)
        db.commit()
        assert ws.summary_is_current(body_with_two_sources) is True

    def test_an_ingest_makes_it_stale(self, db, body_with_two_sources):
        ws.store_summary(db, body_with_two_sources)
        db.commit()
        body_with_two_sources.observation_count += 1
        db.commit()
        assert ws.summary_is_current(body_with_two_sources) is False

    def test_a_stale_cache_is_recomputed_not_served(self, db, body_with_two_sources):
        ws.store_summary(db, body_with_two_sources)
        db.commit()
        # A new reading arrives, as an ingest would leave it.
        source = db.scalar(select(DataSource).where(DataSource.key == "sensor"))
        station = db.scalar(select(MonitoringStation))
        db.add(
            WaterQualityObservation(
                source_id=source.id,
                station_id=station.id,
                water_body_id=body_with_two_sources.id,
                parameter="turbidity",
                observed_at=NEW + timedelta(hours=1),
                value=12.0,
                normalized_value=12.0,
                unit="NTU",
                normalized_unit="NTU",
                quality_flag="ok",
                retrieved_at=NEW,
            )
        )
        body_with_two_sources.observation_count += 1
        db.commit()

        summary = ws.summary_for(db, body_with_two_sources)
        assert "turbidity" in {m["parameter"] for m in summary["measurements"]}, (
            "a stale cache must be recomputed, not served"
        )

    def test_a_body_with_no_cache_still_answers(self, db, body_with_two_sources):
        body_with_two_sources.summary = None
        body_with_two_sources.summary_observation_count = None
        db.commit()
        summary = ws.summary_for(db, body_with_two_sources)
        assert summary["measurements"]
        assert summary["sources"]


class TestReadersUseIt:
    def test_latest_measurements_reads_the_cache(self, db, body_with_two_sources):
        ws.store_summary(db, body_with_two_sources)
        db.commit()
        measured = {
            m.parameter_key: m for m in ws.latest_measurements(db, body_with_two_sources)
        }
        assert set(measured) == {"bod", "ph", "dissolved_oxygen"}
        assert measured["bod"].value == 2.0
        assert measured["bod"].source == "Sensor Agency"

    def test_latest_by_source_reads_the_cache(self, db, body_with_two_sources):
        ws.store_summary(db, body_with_two_sources)
        db.commit()
        sources = ws.latest_by_source(db, body_with_two_sources)
        assert [s["key"] for s in sources] == ["sensor", "lab"]
        assert sources[0]["latest_observed_at"].startswith("2026-09-26")

    def test_the_detail_page_is_the_same_with_and_without_the_cache(
        self, db, body_with_two_sources
    ):
        """The cache must change the cost, never the answer."""
        body_with_two_sources.summary = None
        body_with_two_sources.summary_observation_count = None
        db.commit()
        uncached = ws.get_water_body_detail(db, "cached-river")

        ws.store_summary(db, body_with_two_sources)
        db.commit()
        cached = ws.get_water_body_detail(db, "cached-river")

        for field in ("status", "latest_observed_at", "observation_count"):
            assert cached[field] == uncached[field], field
        assert (
            cached["availability"]["newest_source"]
            == (uncached["availability"]["newest_source"])
        )
        assert [p["parameter"] for p in cached["parameters"]] == [
            p["parameter"] for p in uncached["parameters"]
        ]

    def test_refresh_status_populates_every_body(self, db, body_with_two_sources):
        body_with_two_sources.summary = None
        db.commit()
        ws.refresh_cached_statuses(db)
        db.refresh(body_with_two_sources)
        assert body_with_two_sources.summary is not None
        assert body_with_two_sources.summary_computed_at is not None
        assert body_with_two_sources.summary_observation_count == (
            body_with_two_sources.observation_count
        )

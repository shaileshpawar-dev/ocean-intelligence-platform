"""Every parameter that was measured must appear, however old it is.

The three "latest value of every parameter" queries used to read the few
thousand most recent rows and deduplicate in Python. On a real river that
window did not reach back to the last time a rarely-sampled parameter was
measured, so the parameter disappeared from the page and was then reported as
"not measured": the Teesta lost 20 of its 37 parameters, the Ganga 11 of 39.
`compute_status` used the same capped read, so a status could be computed
without the parameter that exceeds its limit.

These tests build a water body whose history is longer than the old caps
(4,000 rows for the status, 6,000 for the parameter list) and check that a
parameter measured once, at the very beginning, still comes back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models.water import (
    DataSource,
    MonitoringStation,
    WaterBody,
    WaterBodyType,
    WaterQualityObservation,
)
from app.services import water_service as ws
from sqlalchemy import insert, select

# Comfortably past both caps.
FILLER_ROWS = 6_200
START = datetime(2015, 1, 1, tzinfo=UTC)


@pytest.fixture
def long_history(db):
    """One water body with a long run of pH and a single, ancient BOD."""
    source = DataSource(key="hist", name="History Agency", organisation="History")
    db.add(source)
    body = WaterBody(
        slug="long-river",
        name="Long River",
        normalized_name="LONG",
        water_type=WaterBodyType.RIVER,
        match_confidence=1.0,
        match_method="test",
        aliases=[],
        source_ids={},
    )
    db.add(body)
    db.flush()
    station = MonitoringStation(
        station_code="LONG:1",
        name="Long River at Test",
        slug="long-river-at-test",
        source_id=source.id,
        water_body_id=body.id,
        latitude=20.0,
        longitude=78.0,
    )
    db.add(station)
    db.flush()

    rows = [
        {
            "source_id": source.id,
            "station_id": station.id,
            "water_body_id": body.id,
            "parameter": "ph",
            "observed_at": START + timedelta(hours=index + 1),
            "value": 7.2,
            "normalized_value": 7.2,
            "unit": "pH",
            "normalized_unit": "pH",
            "quality_flag": "ok",
            "retrieved_at": START,
        }
        for index in range(FILLER_ROWS)
    ]
    # The one BOD reading is the oldest row in the table, far beyond the
    # window the old code looked at.
    rows.append(
        {
            "source_id": source.id,
            "station_id": station.id,
            "water_body_id": body.id,
            "parameter": "bod",
            "observed_at": START,
            "value": 18.0,
            "normalized_value": 18.0,
            "unit": "mg/L",
            "normalized_unit": "mg/L",
            "quality_flag": "ok",
            "retrieved_at": START,
        }
    )
    db.execute(insert(WaterQualityObservation), rows)
    db.commit()
    return body


class TestNothingMeasuredIsHidden:
    def test_latest_measurements_include_the_oldest_parameter(self, db, long_history):
        measured = ws.latest_measurements(db, long_history)
        keys = {m.parameter_key for m in measured}
        assert keys == {"ph", "bod"}, (
            f"a parameter measured {FILLER_ROWS} rows ago must still be found, "
            f"got {sorted(keys)}"
        )

    def test_one_row_per_parameter_and_it_is_the_newest(self, db, long_history):
        measured = {m.parameter_key: m for m in ws.latest_measurements(db, long_history)}
        assert len(measured) == 2
        # The newest pH, not the first one inserted.
        assert measured["ph"].observed_at == START + timedelta(hours=FILLER_ROWS)
        assert measured["bod"].observed_at == START

    def test_the_status_sees_the_exceedance_it_would_have_missed(self, db, long_history):
        result = ws.compute_status(db, long_history, as_of_observation=True)
        evaluated = {m.parameter_key for m in result.measurements}
        assert "bod" in evaluated, "the failing parameter must reach the status engine"

    def test_the_page_lists_every_measured_parameter(self, db, long_history):
        listed = {p["parameter"] for p in ws.latest_parameters(db, long_history)}
        assert listed == {"ph", "bod"}

    def test_station_detail_lists_every_measured_parameter(self, db, long_history):
        station = db.scalar(
            select(MonitoringStation).where(
                MonitoringStation.water_body_id == long_history.id
            )
        )
        detail = ws.station_detail(db, station.id)
        assert detail is not None
        listed = {p["parameter"] for p in detail["parameters"]}
        assert listed == {"ph", "bod"}

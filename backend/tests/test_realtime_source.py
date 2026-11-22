"""The CPCB real-time feed: parsing it, and what it changes.

This is the first source that can answer "what is the river like now?", so
these tests cover both halves of that: reading the feed correctly, and the
platform's freshness language changing because of it -- without the historical
sources being overwritten or averaged into it.

The feed is not called. The fixtures are trimmed copies of the real payloads
fetched on 26 September 2026, including their quirks: the mojibake in station
names, the "---" unit for pH, and the hydrological series that are not water
quality.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.water.freshness import Cadence
from app.water.providers.base import FetchPlan
from app.water.providers.cpcb_rtwqms import (
    PARAMETER_MAP,
    UNMAPPED_SERIES,
    CPCBRealTimeProvider,
)

STAMP = "2026-09-26T13:30:00.000Z"

LAYER = [
    {
        "timestamp": STAMP,
        "ts_value": 8.19,
        "stationparameter_name": "pH",
        "ts_unitsymbol": "---",
        "station_id": "11799",
        "station_no": "UT67",
        "station_name": "UT67_Kheerveer Bridge,Pratapgarh",
        "station_latitude": 25.920256,
        "station_longitude": 82.027409,
        "territory_name": "Uttar Pradesh",
    },
    {
        "timestamp": STAMP,
        "ts_value": 2.72,
        "stationparameter_name": "BOD",
        "ts_unitsymbol": "mg/l",
        "station_no": "BH72",
        "station_name": "BH72_River Ganga at Chausa\u00c2\u00a0",
        "station_latitude": 25.5193,
        "station_longitude": 83.9007,
        "territory_name": "Bihar",
    },
    {
        "timestamp": STAMP,
        "ts_value": 1.19,
        "stationparameter_name": "Depth",
        "ts_unitsymbol": "m",
        "station_no": "BH72",
        "station_name": "BH72_River Ganga at Chausa",
        "station_latitude": 25.5193,
        "station_longitude": 83.9007,
        "territory_name": "Bihar",
    },
    {
        "timestamp": STAMP,
        "ts_value": 14.2,
        "stationparameter_name": "TOC",
        "ts_unitsymbol": "mg/l",
        "station_no": "BH72",
        "station_name": "BH72_River Ganga at Chausa",
        "station_latitude": 25.5193,
        "station_longitude": 83.9007,
        "territory_name": "Bihar",
    },
    {
        "timestamp": None,
        "ts_value": 7.0,
        "stationparameter_name": "pH",
        "ts_unitsymbol": "---",
        "station_no": "XX99",
        "station_name": "XX99_No timestamp",
        "station_latitude": 25.0,
        "station_longitude": 83.0,
        "territory_name": "Bihar",
    },
]

STATIONS = [
    {"station_no": "UT67", "station_name": "UT67_Kheerveer Bridge,Pratapgarh"},
    {"station_no": "BH72", "station_name": "BH72_River Ganga at Chausa\u00c2\u00a0"},
]


@pytest.fixture
def provider(monkeypatch):
    """A provider wired to the fixtures instead of the network."""
    instance = CPCBRealTimeProvider()
    monkeypatch.setattr(instance, "_records", lambda: LAYER)
    monkeypatch.setattr(instance, "_stations", lambda: STATIONS)
    return instance


class TestReadingTheFeed:
    def test_it_declares_itself_as_sensor_data_at_hourly_cadence(self, provider):
        info = provider.info
        assert info.key == "cpcb_rtwqms"
        assert info.cadence is Cadence.HOURLY
        assert info.observation_method == "continuous_sensor"
        assert "not laboratory" in (info.reliability_note or "").lower()

    def test_one_plan_per_state_present_in_the_feed(self, provider):
        codes = {p.state_code for p in provider.plans()}
        assert codes == {"UP", "BR"}

    def test_states_can_be_filtered(self, provider):
        plans = provider.plans(states=["BR"])
        assert [p.state_code for p in plans] == ["BR"]

    def test_rows_carry_value_unit_time_and_place(self, provider):
        rows = list(provider.fetch(FetchPlan("x", "Bihar", state_code="BR")))
        bod = next(r for r in rows if r.parameter_key == "bod")
        assert bod.value == 2.72
        assert bod.observed_at == datetime(2026, 9, 26, 13, 30, tzinfo=UTC)
        assert (bod.latitude, bod.longitude) == (25.5193, 83.9007)
        assert bod.agency == "CPCB"

    def test_the_station_code_prefix_and_mojibake_are_removed(self, provider):
        rows = list(provider.fetch(FetchPlan("x", "Bihar", state_code="BR")))
        assert rows[0].station_name == "River Ganga at Chausa", (
            "the identity rules must see the river, not the station code"
        )

    def test_hydrology_and_unmapped_series_are_skipped_not_guessed(self, provider):
        rows = list(provider.fetch(FetchPlan("x", "Bihar", state_code="BR")))
        assert {r.parameter_key for r in rows} == {"bod"}
        assert set(UNMAPPED_SERIES) == {"Depth", "S", "TOC"}
        assert "Depth" not in PARAMETER_MAP

    def test_a_record_with_no_timestamp_is_dropped(self, provider):
        rows = list(provider.fetch(FetchPlan("x", "Bihar", state_code="BR")))
        assert all(r.observed_at is not None for r in rows)
        assert not [r for r in rows if "No timestamp" in r.station_name]

    def test_dimensionless_ph_does_not_acquire_a_unit(self, provider):
        rows = list(provider.fetch(FetchPlan("x", "UP", state_code="UP")))
        ph = next(r for r in rows if r.parameter_key == "ph")
        assert ph.value == 8.19
        assert (ph.normalized_unit or "") in {"", "pH"}


class TestNoCheapCursor:
    def test_it_reports_no_row_count_so_a_live_feed_is_always_re_read(self, provider):
        """40 stations report 40 records whether the values are new or a month old.

        Returning a count here would let the incremental sync skip the feed
        forever. Safety comes from the uniqueness key instead.
        """
        assert provider.resource_total(FetchPlan("x", "y", state_code="BR")) is None

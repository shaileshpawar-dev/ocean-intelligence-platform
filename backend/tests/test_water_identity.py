"""Regression tests for canonical water-body identity.

Station labels mix three different things: the water body, where on it the
sample was taken, and the nearest place. Only the first may define identity.
These tests run the real ingestion pipeline over station names shaped like the
published ones and assert that sampling positions never split a water body,
that spelling variants and local drain names converge, and that same-named
features far apart stay separate.

Station names and values here are test fixtures, not observations.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.models.water import MonitoringStation, WaterBody
from app.water import providers as provider_registry
from app.water.freshness import Cadence
from app.water.ingestion import ingest_provider
from app.water.matching import resolve, sampling_descriptor
from app.water.providers.base import (
    FetchPlan,
    ObservationRow,
    ProviderInfo,
    WaterDataProvider,
)

WHEN = datetime(2021, 12, 2, 8, 30, tzinfo=UTC)


def _row(station: str, lat: float, lon: float, state: str, code: str) -> ObservationRow:
    return ObservationRow(
        station_name=station,
        parameter_key="bod",
        observed_at=WHEN,
        value=4.0,
        normalized_value=4.0,
        unit="mg/L",
        normalized_unit="mg/L",
        latitude=lat,
        longitude=lon,
        state_name=state,
        state_code=code,
        district="Test",
        source_reference=f"test:{station}",
    )


ROWS = [
    # Mithi: one river, many sampling positions, and a local drain name.
    _row("MITHI RIVER MAHIM BANDRA MUMBAI", 19.05, 72.85, "Maharashtra", "MH"),
    _row("MITHI RIVER D/S", 19.06, 72.86, "Maharashtra", "MH"),
    _row("MITHI RIVER U/S OF KURLA", 19.07, 72.87, "Maharashtra", "MH"),
    _row("MITHI RIVER MIDSTREAM", 19.065, 72.865, "Maharashtra", "MH"),
    _row("MITHI NALLAH AT KURLA", 19.08, 72.88, "Maharashtra", "MH"),
    # Yamuna across two states, one without the keyword.
    _row("YAMUNA RIVER AT MATHURA", 27.49, 77.67, "Uttar Pradesh", "UP"),
    _row("YAMUNA AT NIZAMUDDIN BRIDGE", 28.59, 77.26, "Delhi", "DL"),
    _row("YAMUNA D/S OF OKHLA BARRAGE", 28.54, 77.31, "Delhi", "DL"),
    # Ganga at two positions in one state.
    _row(
        "RIVER GANGA AT MADHYA GANGA BARRAGE BIJNOR", 29.37, 78.03, "Uttar Pradesh", "UP"
    ),
    _row("RIVER GANGA D/S NEAR CREMATION GHAT", 29.30, 78.10, "Uttar Pradesh", "UP"),
    # Spelling variants of one river.
    _row("BRAHAMPUTRA RIVER AT BOGIBEEL BRIDGE", 27.42, 94.76, "Assam", "AS"),
    _row("BRAHMAPUTRA AT GUWAHATI", 26.19, 91.75, "Assam", "AS"),
    # Same lake name in two states: must stay two lakes.
    _row("RANI TALAB", 22.3, 73.2, "Gujarat", "GJ"),
    _row("RANI TALAB", 25.4, 81.8, "Uttar Pradesh", "UP"),
    # Same river name far apart (> 500 km): must stay two rivers.
    _row("AMRAVATI RIVER AT DHARAPURAM", 10.73, 77.52, "Tamil Nadu", "TN"),
    _row("AMRAVATI RIVER AT DADHAL", 21.6, 73.0, "Gujarat", "GJ"),
]


class _Provider(WaterDataProvider):
    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            key="cpcb_nwdp", name="test", organisation="test", cadence=Cadence.MONTHLY
        )

    def plans(self, *, states: list[str] | None = None) -> list[FetchPlan]:
        # Two resources, so cross-resource reconciliation is exercised.
        return [
            FetchPlan(identifier="a", description="a"),
            FetchPlan(identifier="b", description="b"),
        ]

    def fetch(self, plan: FetchPlan) -> Iterator[ObservationRow]:
        half = len(ROWS) // 2
        yield from ROWS[:half] if plan.identifier == "a" else ROWS[half:]


@pytest.fixture
def identity_db(db, monkeypatch):
    monkeypatch.setitem(provider_registry.PROVIDERS, "cpcb_nwdp", _Provider)
    ingest_provider(db, "cpcb_nwdp")
    return db


def _bodies(db, core: str) -> list[WaterBody]:
    return db.query(WaterBody).filter(WaterBody.normalized_name == core).all()


class TestSamplingPositionsNeverSplitBodies:
    def test_mithi_is_one_river(self, identity_db):
        mithi = _bodies(identity_db, "MITHI")
        assert len(mithi) == 1
        assert mithi[0].name == "Mithi River"
        assert mithi[0].station_count == 5

    def test_positions_are_kept_on_stations(self, identity_db):
        descriptors = {
            s.name: s.position_descriptor
            for s in identity_db.query(MonitoringStation).all()
        }
        assert descriptors["MITHI RIVER D/S"] == "D/S"
        assert descriptors["MITHI RIVER U/S OF KURLA"] == "U/S Of Kurla"
        assert descriptors["MITHI RIVER MIDSTREAM"] == "Midstream"

    @pytest.mark.parametrize(
        "station",
        [
            "MITHI RIVER D/S",
            "MITHI RIVER U/S OF KURLA",
            "MITHI RIVER MIDSTREAM",
            "MITHI RIVER AT KALINA",
            "MITHI RIVER DOWNSTREAM",
            "MITHI RIVER UPSTREAM",
        ],
    )
    def test_position_words_never_enter_the_name(self, station):
        assert resolve(station).name == "Mithi River"

    def test_ganga_positions_share_one_body(self, identity_db):
        ganga = _bodies(identity_db, "GANGA")
        assert len(ganga) == 1
        assert ganga[0].station_count == 2


class TestNamesConverge:
    def test_local_drain_name_joins_the_river(self, identity_db):
        mithi = _bodies(identity_db, "MITHI")[0]
        assert "Mithi Nallah" in mithi.aliases
        assert (
            identity_db.query(WaterBody).filter(WaterBody.name == "Mithi Nallah").count()
            == 0
        )

    def test_yamuna_is_one_river_across_states(self, identity_db):
        yamuna = _bodies(identity_db, "YAMUNA")
        assert len(yamuna) == 1
        assert yamuna[0].station_count == 3

    def test_spelling_variants_converge(self, identity_db):
        brahmaputra = _bodies(identity_db, "BRAHMAPUTRA")
        assert len(brahmaputra) == 1
        assert brahmaputra[0].name == "Brahmaputra River"
        assert "Brahamputra River" in brahmaputra[0].aliases
        assert _bodies(identity_db, "BRAHAMPUTRA") == []


class TestSameNameDifferentFeature:
    def test_same_lake_name_in_two_states_stays_two(self, identity_db):
        assert len(_bodies(identity_db, "RANI")) == 2

    def test_same_river_name_far_apart_stays_two(self, identity_db):
        amravati = _bodies(identity_db, "AMRAVATI")
        assert len(amravati) == 2


class TestDescriptorParsing:
    def test_descriptor_preserves_abbreviations(self):
        match = resolve("GODAVARI AT NASIK D/S GADGEBABA")
        assert sampling_descriptor("GODAVARI AT NASIK D/S GADGEBABA", match) == (
            "At Nasik D/S Gadgebaba"
        )

    def test_no_descriptor_when_the_label_is_only_the_name(self):
        assert resolve("ABBIGERE LAKE").position is None

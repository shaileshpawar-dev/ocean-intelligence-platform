"""End-to-end tests for ingestion, the water API and the water Q&A pipeline.

These run fully offline. Ingestion is driven through a fake provider whose
rows have exactly the shape the live CPCB/NWDP adapter produces -- including
the empty ``River`` column and the station-name-embedded water body -- so the
real matching, validation, de-duplication and status code paths all execute
without the test suite depending on a government server being up.

The fixture values are test data, not observations. They are chosen to
exercise specific rules (a BOD breach, a missing parameter, an old sample),
and nothing here is presented anywhere as a real measurement.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import ClassVar

import pytest
from app.main import app
from app.models.water import (
    IngestionRun,
    MonitoringStation,
    WaterBody,
    WaterQualityObservation,
)
from app.services import water_service as ws
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
from app.water.providers.nwdp_cpcb import NWDPCPCBProvider
from app.water.rag import answer, classify_intent, resolve_entities
from fastapi.testclient import TestClient

SAMPLED = datetime(2021, 12, 2, 8, 30, tzinfo=UTC)
EARLIER = datetime(2021, 6, 3, 8, 30, tzinfo=UTC)


def _row(
    station: str, parameter: str, value: float, when: datetime, **extra
) -> ObservationRow:
    defaults = {
        "latitude": 19.0517,
        "longitude": 72.8484,
        "state_name": "Maharashtra",
        "state_code": "MH",
        "district": "MUMBAI SUBURBAN",
        "agency": "CPCB",
        "river": None,
        "source_reference": f"test:{station}:{parameter}:{when.date()}",
    }
    defaults.update(extra)
    return ObservationRow(
        station_name=station,
        parameter_key=parameter,
        observed_at=when,
        value=value,
        unit="mg/L",
        normalized_value=value,
        normalized_unit="mg/L",
        raw_value=str(value),
        **defaults,
    )


FIXTURE_ROWS = [
    _row("MITHI RIVER MAHIM BANDRA MUMBAI", "bod", 12.0, SAMPLED),
    _row("MITHI RIVER MAHIM BANDRA MUMBAI", "bod", 20.0, EARLIER),
    _row("MITHI RIVER MAHIM BANDRA MUMBAI", "dissolved_oxygen", 1.5, SAMPLED),
    _row("MITHI RIVER MAHIM BANDRA MUMBAI", "ph", 7.1, SAMPLED),
    _row(
        "SEA WATER AT JUHU BEACH JUHUGAON SANTACRUZ MUMBAI",
        "bod",
        2.0,
        SAMPLED,
        latitude=19.0891,
        longitude=72.8260,
    ),
    _row(
        "SEA WATER AT JUHU BEACH JUHUGAON SANTACRUZ MUMBAI",
        "dissolved_oxygen",
        6.5,
        SAMPLED,
        latitude=19.0891,
        longitude=72.8260,
    ),
    _row(
        "GODAVARI RIVER AT NASIK",
        "bod",
        2.0,
        SAMPLED,
        latitude=20.0,
        longitude=73.79,
        district="Nashik",
    ),
    # Implausible value: must be stored and flagged, never dropped.
    _row(
        "GODAVARI RIVER AT NASIK",
        "ph",
        780.0,
        SAMPLED,
        latitude=20.0,
        longitude=73.79,
        district="Nashik",
    ),
    # A river named with its keyword in one state...
    _row(
        "YAMUNA RIVER AT MATHURA",
        "bod",
        9.0,
        SAMPLED,
        latitude=27.49,
        longitude=77.67,
        state_name="Uttar Pradesh",
        state_code="UP",
        district="Mathura",
    ),
]

# ...and without it in another state's resource. Per-resource propagation
# cannot connect these; the corpus-wide reconcile pass must.
SECOND_RESOURCE_ROWS = [
    _row(
        "YAMUNA AT NIZAMUDDIN BRIDGE",
        "bod",
        25.0,
        SAMPLED,
        latitude=28.59,
        longitude=77.26,
        state_name="Delhi",
        state_code="DL",
        district="South",
    ),
]

ALL_ROWS = FIXTURE_ROWS + SECOND_RESOURCE_ROWS


class FakeProvider(WaterDataProvider):
    """Offline stand-in with the live adapter's row shape."""

    fail = False

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            key="cpcb_nwdp",
            name="CPCB Surface Water Quality (Manual)",
            organisation="Central Pollution Control Board (test double)",
            cadence=Cadence.MONTHLY,
        )

    def plans(self, *, states: list[str] | None = None) -> list[FetchPlan]:
        return [
            FetchPlan(identifier="fixture", description="fixture", state_code="MH"),
            FetchPlan(identifier="second", description="second", state_code="DL"),
        ]

    def fetch(self, plan: FetchPlan) -> Iterator[ObservationRow]:
        if self.fail:
            raise ProviderUnavailableError("simulated outage")
        yield from FIXTURE_ROWS if plan.identifier == "fixture" else SECOND_RESOURCE_ROWS


@pytest.fixture
def water_db(db, monkeypatch):
    """A database populated through the real ingestion pipeline."""
    FakeProvider.fail = False
    monkeypatch.setitem(provider_registry.PROVIDERS, "cpcb_nwdp", FakeProvider)
    summary = ingest_provider(db, "cpcb_nwdp")
    ws.refresh_cached_statuses(db)
    return db, summary


@pytest.fixture
def client(water_db) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
class TestIngestion:
    def test_rows_are_ingested_and_matched(self, water_db):
        db, summary = water_db
        assert summary["status"] == "success"
        assert summary["records_inserted"] == len(ALL_ROWS)
        names = {b.name for b in db.query(WaterBody).all()}
        assert "Mithi River" in names
        assert "Godavari River" in names

    def test_reingestion_is_idempotent(self, water_db, monkeypatch):
        db, _ = water_db
        again = ingest_provider(db, "cpcb_nwdp")
        assert again["records_inserted"] == 0
        assert again["records_duplicate"] == len(ALL_ROWS)
        assert db.query(WaterQualityObservation).count() == len(ALL_ROWS)

    def test_implausible_value_is_kept_and_flagged(self, water_db):
        db, _ = water_db
        ph = (
            db.query(WaterQualityObservation)
            .filter(WaterQualityObservation.value == 780.0)
            .one()
        )
        assert str(ph.quality_flag) == "suspect"

    def test_all_caps_district_is_recased(self, water_db):
        db, _ = water_db
        station = (
            db.query(MonitoringStation)
            .filter(MonitoringStation.name.like("MITHI%"))
            .one()
        )
        assert station.district_id is not None
        from app.models.water import District

        assert db.get(District, station.district_id).name == "Mumbai Suburban"

    def test_run_is_logged(self, water_db):
        db, summary = water_db
        run = db.query(IngestionRun).filter_by(run_id=summary["run_id"]).one()
        assert run.records_seen == len(ALL_ROWS)
        assert run.finished_at is not None

    def test_same_river_across_resources_is_one_water_body(self, water_db):
        """Delhi's 'YAMUNA AT ...' must join UP's 'YAMUNA RIVER ...'."""
        db, _ = water_db
        yamunas = db.query(WaterBody).filter(WaterBody.normalized_name == "YAMUNA").all()
        assert len(yamunas) == 1
        assert yamunas[0].name == "Yamuna River"
        assert yamunas[0].station_count == 2

    def test_reingestion_does_not_recreate_merged_bodies(self, water_db):
        db, _ = water_db
        again = ingest_provider(db, "cpcb_nwdp")
        assert again["water_bodies_created"] == 0
        assert (
            db.query(WaterBody).filter(WaterBody.normalized_name == "YAMUNA").count() == 1
        )

    def test_provider_outage_is_recorded_not_hidden(self, db, monkeypatch):
        FakeProvider.fail = True
        monkeypatch.setitem(provider_registry.PROVIDERS, "cpcb_nwdp", FakeProvider)
        summary = ingest_provider(db, "cpcb_nwdp")
        FakeProvider.fail = False
        assert summary["status"] == "failed"
        assert summary["errors"]
        assert summary["records_inserted"] == 0


# ---------------------------------------------------------------------------
class TestLiveAdapterParsing:
    """The real adapter's row explosion, fed a record in the published shape."""

    RECORD: ClassVar[dict] = {
        "_id": 7,
        "Station": "MITHI RIVER MAHIM BANDRA MUMBAI",
        "Agency": "CPCB",
        "State": "Maharashtra",
        "District": "Mumbai Suburban",
        "River": "-",
        "Latitude": "19.05172500",
        "Longitude": "72.84840300",
        "Data Acquisition Time": "02-12-2021 08:30",
        "Biochemical Oxygen Demand (mg/L)": "3.2",
        "Fecal Coliform (MPN/100mL)": "11000",
        "Chemical Oxygen Demand (mg/L)": None,
        "Total Coliform (MPN/100mL)": "-",
    }

    def test_explodes_only_measured_parameters(self):
        plan = FetchPlan(identifier="r", description="d", state_code="MH")
        rows = list(NWDPCPCBProvider()._explode(self.RECORD, plan, "Maharashtra"))
        keys = {r.parameter_key for r in rows}
        assert keys == {"bod", "fecal_coliform"}

    def test_parses_day_first_timestamp_and_coordinates(self):
        plan = FetchPlan(identifier="r", description="d", state_code="MH")
        row = next(NWDPCPCBProvider()._explode(self.RECORD, plan, "Maharashtra"))
        assert row.observed_at == datetime(2021, 12, 2, 8, 30, tzinfo=UTC)
        assert row.latitude == pytest.approx(19.051725)
        assert row.source_reference.endswith("#7")

    def test_catalogue_excludes_empty_forward_periods(self):
        plans = NWDPCPCBProvider().plans(states=["MH"])
        assert plans
        assert all("2026" not in p.description for p in plans)


# ---------------------------------------------------------------------------
class TestWaterApi:
    def test_detail_carries_both_statuses(self, client):
        body = client.get("/api/v1/water-bodies/mithi-river").json()
        assert body["status_detail"]["status"] == "NO_RECENT_DATA"
        historical = body["latest_available_status"]
        assert historical["status"] == "POLLUTED_STRETCH"
        assert historical["as_of"].startswith("2021-12-02")

    def test_historical_reasons_never_say_zero_days(self, client):
        body = client.get("/api/v1/water-bodies/mithi-river").json()
        text = " ".join(body["latest_available_status"]["reasons"])
        assert "0 days ago" not in text

    def test_unmeasured_parameters_are_absent_not_zero(self, client):
        params = client.get("/api/v1/water-bodies/mithi-river").json()["parameters"]
        keys = {p["parameter"] for p in params}
        assert "lead" not in keys
        assert all(p["value"] is not None for p in params)

    def test_trend_returns_only_real_points(self, client):
        trend = client.get(
            "/api/v1/water-bodies/mithi-river/trend", params={"parameter": "bod"}
        ).json()
        assert trend["point_count"] == 2
        assert trend["sufficient"] is True

    def test_bbox_filters_and_validates(self, client):
        inside = client.get(
            "/api/v1/map/water-bodies", params={"bbox": "18.9,72.7,19.2,73.0"}
        ).json()
        slugs = {i["slug"] for i in inside["items"]}
        assert "mithi-river" in slugs
        assert "godavari-river" not in slugs
        bad = client.get("/api/v1/map/water-bodies", params={"bbox": "1,2,3"})
        assert bad.status_code == 422

    def test_radius_search_is_a_circle(self, client):
        near = client.get(
            "/api/v1/map/near", params={"lat": 19.0517, "lon": 72.8484, "radius_km": 10}
        ).json()
        assert all(i["distance_km"] <= 10 for i in near["items"])
        assert "godavari-river" not in {i["slug"] for i in near["items"]}

    def test_search_finds_water_body_and_district(self, client):
        items = client.get("/api/v1/search", params={"q": "mithi"}).json()["items"]
        assert items[0]["type"] == "water_body"
        assert items[0]["href"] == "/app/water/mithi-river"

    def test_state_filter_includes_rivers_first_seen_elsewhere(self, client):
        """The Yamuna was created from a UP station; it must still be in Delhi."""
        items = client.get("/api/v1/water-bodies", params={"state": "DL"}).json()["items"]
        assert "Yamuna River" in {i["name"] for i in items}
        state = client.get("/api/v1/states/delhi").json()
        assert state["water_body_count"] == 1

    def test_unknown_water_body_is_404(self, client):
        assert client.get("/api/v1/water-bodies/atlantis").status_code == 404

    def test_overview_counts_are_ingested_counts(self, client, water_db):
        db, _ = water_db
        overview = client.get("/api/v1/water-overview").json()
        assert overview["observations"] == db.query(WaterQualityObservation).count()
        assert "historical_status_distribution" in overview


# ---------------------------------------------------------------------------
class TestWaterQuestionAnswering:
    def test_status_question_resolves_and_cites(self, water_db):
        db, _ = water_db
        result = answer(db, "What is the latest available status of Mithi River?")
        assert result["status"] == "grounded"
        assert result["resolution"]["water_bodies"] == ["Mithi River"]
        observations = [c for c in result["citations"] if c["kind"] == "observation"]
        assert observations
        assert all(c["observed_at"] for c in observations)
        assert all(c["source_reference"] for c in observations)

    def test_headline_states_the_date_and_refuses_current(self, water_db):
        db, _ = water_db
        headline = answer(db, "What is the status of Mithi River?")["headline"]
        assert "02 Dec 2021" in headline
        assert "no recent data" in headline.lower()

    def test_unmeasured_parameter_is_no_evidence(self, water_db):
        """No number may appear for a parameter nobody measured."""
        db, _ = water_db
        result = answer(db, "How much mercury is in Mithi River right now?")
        assert result["status"] == "no_evidence"
        assert "No mercury measurement" in result["headline"]
        assert not any(c["kind"] == "observation" for c in result["citations"])

    def test_unknown_place_is_refused(self, water_db):
        db, _ = water_db
        result = answer(db, "Tell me about the Thames")
        assert result["status"] == "no_evidence"
        assert result["citations"] == []
        assert result["map_action"] is None

    def test_nearby_produces_a_map_action(self, water_db):
        db, _ = water_db
        result = answer(db, "Show polluted rivers near Mumbai")
        assert result["intent"] == "nearby"
        assert result["map_action"]["type"] == "highlight"
        assert result["map_action"]["water_body_slugs"] == ["mithi-river"]

    def test_type_word_narrows_results(self, water_db):
        """'rivers' must not return the Juhu beach monitoring point."""
        db, _ = water_db
        result = answer(db, "Which water bodies near Mumbai are rivers?")
        slugs = (result.get("map_action") or {}).get("water_body_slugs", [])
        assert all("sea-water" not in s for s in slugs)

    def test_parameter_filter_uses_measured_breaches(self, water_db):
        db, _ = water_db
        result = answer(db, "Which rivers in Maharashtra have low dissolved oxygen?")
        titles = [c["title"] for c in result["citations"]]
        assert titles == ["Mithi River"]

    def test_trend_states_its_samples(self, water_db):
        db, _ = water_db
        result = answer(db, "Has the BOD of Mithi River improved?")
        assert result["intent"] == "trend"
        assert result["sections"][0]["samples_per_year"] == {"2021": 2}

    def test_compare_needs_two_bodies(self, water_db):
        db, _ = water_db
        result = answer(db, "Compare Mithi River and the Thames")
        assert result["status"] == "no_evidence"

    def test_trace_is_bounded_and_staged(self, water_db):
        db, _ = water_db
        result = answer(db, "What is the status of Mithi River?")
        stages = [t["stage"] for t in result["trace"]]
        assert stages[0] == "IDENTIFY"
        assert stages[-1] == "REPORT"
        assert len(stages) < 20
        assert result["llm_used"] is False

    def test_rivers_in_a_state_include_cross_state_rivers(self, water_db):
        db, _ = water_db
        result = answer(db, "Which rivers in Delhi have elevated BOD?")
        assert result["status"] == "grounded"
        assert [c["title"] for c in result["citations"]] == ["Yamuna River"]

    def test_official_place_rename_resolves(self, water_db):
        from app.water.matching import expand_place_aliases

        assert "BANGALORE" in expand_place_aliases("LAKES NEAR BENGALURU")
        assert expand_place_aliases("NOTHING HERE") == "NOTHING HERE"

    def test_intent_classification(self):
        assert classify_intent("compare A and B") == "compare"
        assert classify_intent("rivers near Pune") == "nearby"
        assert classify_intent("has it improved") == "trend"

    def test_longest_name_wins(self, water_db):
        db, _ = water_db
        resolution = resolve_entities(db, "status of godavari river please")
        assert [b.name for b in resolution.water_bodies] == ["Godavari River"]

    def test_api_endpoint(self, client):
        response = client.post(
            "/api/v1/water/ask", json={"question": "status of Mithi River"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "grounded"
        short = client.post("/api/v1/water/ask", json={"question": "?"})
        assert short.status_code == 422

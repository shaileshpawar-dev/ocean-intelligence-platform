"""API tests for the Phase 2 geography endpoints.

Built on the pipeline fixture (real ingestion of fixture rows), plus small
boundary files and a stubbed Overpass response. No network.
"""

from __future__ import annotations

import json

import pytest
from app.main import app
from app.models.water import WaterBody
from app.water.boundaries import import_boundaries
from app.water.cities import import_cities
from app.water.geometry import fetch_and_store
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_water_pipeline import water_db  # noqa: F401  (fixture)


def _feature(props: dict, box: tuple[float, float, float, float]) -> dict:
    x0, y0, x1, y1 = box
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


@pytest.fixture
def geo_client(water_db, tmp_path) -> TestClient:  # noqa: F811
    db, _ = water_db
    adm1 = {
        "type": "FeatureCollection",
        "features": [
            _feature({"shapeName": "Mahārāshtra", "shapeISO": "IN-MH"}, (72, 17, 76, 21)),
            _feature(
                {"shapeName": "Delhi", "shapeISO": "IN-DL"}, (76.8, 28.4, 77.4, 28.9)
            ),
            _feature({"shapeName": "Goa", "shapeISO": "IN-GA"}, (73.6, 14.9, 74.3, 15.8)),
        ],
    }
    adm2 = {
        "type": "FeatureCollection",
        "features": [
            _feature(
                {"shapeName": "Mumbai", "shapeID": "a"}, (72.80, 18.90, 72.90, 19.00)
            ),
            _feature(
                {"shapeName": "Mumbai Suburban", "shapeID": "b"},
                (72.80, 19.00, 72.98, 19.30),
            ),
            _feature({"shapeName": "Nashik", "shapeID": "c"}, (73.5, 19.8, 74.2, 20.4)),
        ],
    }
    p1, p2 = tmp_path / "a1.json", tmp_path / "a2.json"
    p1.write_text(json.dumps(adm1), encoding="utf-8")
    p2.write_text(json.dumps(adm2), encoding="utf-8")
    import_boundaries(db, state_path=p1, district_path=p2)
    import_cities(db)

    mithi = db.scalar(select(WaterBody).where(WaterBody.slug == "mithi-river"))
    river = {
        "type": "way",
        "id": 42,
        "tags": {"waterway": "river", "name": "Mithi River"},
        "geometry": [
            {"lat": 19.04, "lon": 72.84},
            {"lat": 19.0517, "lon": 72.8484},
            {"lat": 19.06, "lon": 72.86},
        ],
    }
    fetch_and_store(db, mithi, fetch=lambda q: {"elements": [river]})
    return TestClient(app)


class TestGeographyApi:
    def test_layer_catalogue_groups(self, geo_client):
        body = geo_client.get("/api/v1/map/layers").json()
        keys = [g["key"] for g in body["groups"]]
        assert keys == ["hydrology", "monitoring", "status", "boundaries", "evidence"]
        wms = body["groups"][0]["layers"][1]
        assert wms["kind"] == "wms" and "bhuvan" in wms["wms"]["url"]

    def test_state_boundaries_carry_provenance_and_links(self, geo_client):
        body = geo_client.get("/api/v1/boundaries/states?zoom=5").json()
        assert body["count"] == 3
        assert body["licence"] == "CC BY 2.5 IN"
        assert "not the official boundaries" in body["disclaimer"]
        by_name = {f["properties"]["name"]: f["properties"] for f in body["features"]}
        assert by_name["Maharashtra"]["state_code"] == "MH"
        # Goa is in the boundary file but has no water data in this fixture.
        assert by_name["Goa"]["has_water_data"] is False

    def test_districts_need_a_scope(self, geo_client):
        assert geo_client.get("/api/v1/boundaries/districts").status_code == 422
        body = geo_client.get("/api/v1/boundaries/districts?state=MH").json()
        assert {f["properties"]["name"] for f in body["features"]} == {
            "Mumbai",
            "Mumbai Suburban",
            "Nashik",
        }

    def test_geometry_layer_returns_lines_with_status(self, geo_client):
        body = geo_client.get(
            "/api/v1/map/geometries?bbox=18.9,72.7,19.3,73.1&zoom=12"
        ).json()
        assert body["count"] == 1
        f = body["features"][0]
        assert f["geometry"]["type"] == "LineString"
        assert f["properties"]["slug"] == "mithi-river"
        assert f["properties"]["latest_available_status"] == "HIGH_CONCERN"
        assert "OpenStreetMap" in body["attribution"]

    def test_geometry_outside_viewport_is_not_sent(self, geo_client):
        body = geo_client.get("/api/v1/map/geometries?bbox=10,70,11,71").json()
        assert body["count"] == 0

    def test_clusters_at_low_zoom_and_points_at_high(self, geo_client):
        low = geo_client.get("/api/v1/map/station-clusters?zoom=3").json()
        assert low["clustered"] is True
        assert sum(i.get("count", 1) for i in low["items"]) == 5
        high = geo_client.get(
            "/api/v1/map/station-clusters?zoom=13&bbox=18.9,72.7,19.2,73.0"
        ).json()
        assert high["clustered"] is False
        assert all(i["kind"] == "station" for i in high["items"])

    def test_city_detail_is_a_district_grouping(self, geo_client):
        body = geo_client.get("/api/v1/cities/mumbai-mh").json()
        assert body["kind"] == "city"
        assert "Mumbai City and Mumbai Suburban" in body["definition"]
        assert body["water_body_count"] >= 1
        assert body["bbox"] is not None

    def test_district_slug_still_resolves(self, geo_client):
        body = geo_client.get("/api/v1/cities/nashik").json()
        assert body["kind"] == "district"

    def test_detail_has_geometry_quality_availability_sources(self, geo_client):
        d = geo_client.get("/api/v1/water-bodies/mithi-river").json()
        assert d["geometry"]["geometry_type"] == "LineString"
        prov = d["geometry"]["provenance"]
        assert prov["source_ids"] == ["way/42"]
        assert prov["licence"].startswith("ODbL")
        assert d["availability"]["current_condition"] == (
            "Cannot be established from this dataset."
        )
        assert d["data_quality"]["level"] in {
            "HIGH",
            "MODERATE",
            "LIMITED",
            "INSUFFICIENT",
        }
        assert all("rule" in f for f in d["data_quality"]["factors"])
        roles = [s["role"] for s in d["sources_panel"]]
        assert roles[:1] == ["Measurements"]
        assert "Reference standard" in roles and "Geometry" in roles
        station = d["stations"][0]
        assert station["relationship_type"] == "on_geometry"

    def test_body_without_geometry_says_why(self, geo_client):
        body = geo_client.get("/api/v1/water-bodies/yamuna-river/geometry").json()
        assert body["geometry"] is None
        assert body["geometry_status"] == "not_attempted"
        assert body["geometry_status_text"]

    def test_coverage_endpoint(self, geo_client):
        t = geo_client.get("/api/v1/water-coverage").json()["totals"]
        # The fixture provider publishes MH and DL; UP arrives in MH's resource.
        assert t["states_loaded"] == 3
        assert t["states_available_in_source"] == 2
        assert t["geometries"] == 1
        assert t["boundaries"] == {"state": 3, "district": 3}
        assert t["cities"] >= 1

    def test_search_finds_city_first_and_routes_questions(self, geo_client):
        body = geo_client.get("/api/v1/search?q=Mumbai").json()
        assert body["items"][0]["type"] == "city"
        assert body["items"][0]["href"] == "/app/city/mumbai-mh"
        assert body["ask_suggested"] is False
        alias = geo_client.get("/api/v1/search?q=Bombay").json()
        assert alias["items"][0]["title"] == "Mumbai"
        mithi = geo_client.get("/api/v1/search?q=Mithi").json()
        assert mithi["items"][0]["slug"] == "mithi-river"
        question = geo_client.get("/api/v1/search?q=polluted rivers near Mumbai").json()
        assert question["ask_suggested"] is True
        assert question["intent"] == "nearby"

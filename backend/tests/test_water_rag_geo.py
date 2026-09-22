"""RAG geography: city-scoped spatial questions and layered evidence.

Uses the pipeline fixture (Mithi, Juhu and Godavari in Maharashtra, Yamuna in
UP and Delhi) plus small boundary files. Nothing here calls a model.
"""

from __future__ import annotations

from app.water.rag import answer
from test_water_geo_api import geo_client  # noqa: F401  (fixture)
from test_water_pipeline import water_db  # noqa: F401  (fixture)


def _ask(water_db, question: str) -> dict:  # noqa: F811
    db, _ = water_db
    return answer(db, question)


class TestCityQuestions:
    def test_polluted_rivers_near_mumbai(self, water_db, geo_client):  # noqa: F811
        a = _ask(water_db, "Which polluted rivers are near Mumbai?")
        assert a["status"] == "grounded"
        assert a["resolution"]["cities"] == ["Mumbai"]
        # The city stands in for its districts; they are not matched again.
        assert a["resolution"]["districts"] == []
        names = [i["name"] for i in a["sections"][0]["items"]]
        assert names == ["Mithi River"]
        assert "Mumbai" in a["headline"]
        assert a["headline"].startswith("1 river ")  # not "1 rivers"
        assert any("Mumbai City and Mumbai Suburban" in lim for lim in a["limitations"])
        assert all(c["evidence_type"] == "DERIVED_STATUS" for c in a["citations"])

    def test_no_match_is_not_a_clean_bill(self, water_db, geo_client):  # noqa: F811
        a = _ask(water_db, "lakes near Mumbai")
        assert a["status"] == "no_evidence"
        assert any(
            "not that the area's water is clean" in lim for lim in a["limitations"]
        )

    def test_stations_near_a_city_are_measured_evidence(self, water_db, geo_client):  # noqa: F811
        a = _ask(water_db, "monitoring stations near Mumbai")
        assert a["status"] == "grounded"
        assert a["sections"][0]["kind"] == "stations"
        assert {c["evidence_type"] for c in a["citations"]} == {"MEASURED"}
        assert all(i["distance_km"] <= 25 for i in a["sections"][0]["items"])

    def test_city_without_extent_refuses_to_search(self, water_db, geo_client):  # noqa: F811
        a = _ask(water_db, "which rivers are within 20 km of Pune")
        assert a["status"] == "no_evidence"
        assert "no mapped extent" in a["headline"]

    def test_high_concern_in_a_state_is_strict(self, water_db, geo_client):  # noqa: F811
        a = _ask(water_db, "high-concern water bodies in Maharashtra")
        assert a["resolution"]["filter_high_concern"] is True
        names = {i["name"] for i in a["sections"][0]["items"]}
        assert "Mithi River" in names
        assert all(
            i.get("latest_available_status") in (None, "HIGH_CONCERN", "POLLUTED_STRETCH")
            for i in a["sections"][0]["items"]
        )


class TestLayeredEvidence:
    def test_status_answer_separates_evidence_layers(self, water_db, geo_client):  # noqa: F811
        a = _ask(water_db, "What is the status of Mithi River?")
        section = a["sections"][0]
        layers = section["evidence_layers"]
        assert set(layers) == {
            "MEASURED",
            "REFERENCE_COMPARISON",
            "SOURCE_CLASSIFICATION",
            "DERIVED_STATUS",
            "SATELLITE_OBSERVED",
        }
        assert layers["REFERENCE_COMPARISON"]["standard"] == (
            "Primary Water Quality Criteria for Bathing Water"
        )
        assert layers["SOURCE_CLASSIFICATION"] == []
        assert layers["SATELLITE_OBSERVED"] is None  # nothing retrieved: not invented
        assert layers["DERIVED_STATUS"]["describes_present_state"] is False
        derived = [c for c in a["citations"] if c["kind"] == "status"]
        assert derived[0]["evidence_type"] == "DERIVED_STATUS"
        assert "Bathing Water" in derived[0]["source"]

    def test_coastal_body_has_no_reference_and_says_why(self, water_db, geo_client):  # noqa: F811
        a = _ask(water_db, "How is Sea Water Juhu Beach Juhugaon Santacruz Mumbai?")
        assert a["resolution"]["water_bodies"], "the coastal body must resolve"
        layers = a["sections"][0]["evidence_layers"]
        assert layers["REFERENCE_COMPARISON"]["standard"] is None
        assert "coastal" in layers["REFERENCE_COMPARISON"]["unavailable_reason"].lower()


class TestOverHttp:
    def test_city_answer_serialises_through_the_api(self, water_db, geo_client):  # noqa: F811
        """Regression: a City object in the trace broke JSON serialisation."""
        r = geo_client.post(
            "/api/v1/water/ask", json={"question": "Show polluted rivers near Mumbai"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "grounded"
        traced = [
            c["arguments"] for c in body["trace"] if c["tool"] == "water_bodies_near_city"
        ]
        assert traced and traced[0]["city"] == "City:Mumbai"

    def test_station_answer_serialises_through_the_api(self, water_db, geo_client):  # noqa: F811
        r = geo_client.post(
            "/api/v1/water/ask", json={"question": "monitoring stations near Mumbai"}
        )
        assert r.status_code == 200

    def test_state_listing_question(self, water_db, geo_client):  # noqa: F811
        """Regression: "rivers in <state>" had no route and returned no evidence."""
        r = geo_client.post(
            "/api/v1/water/ask", json={"question": "rivers in Maharashtra"}
        )
        body = r.json()
        assert body["status"] == "grounded"
        names = {i["name"] for i in body["sections"][0]["items"]}
        assert {"Mithi River", "Godavari River"} <= names
        assert "Sea Water" not in " ".join(names)  # coastal excluded by type
        assert "rivers in Maharashtra" in body["headline"]

    def test_common_words_never_resolve_to_water_bodies(self, water_db):  # noqa: F811
        """Regression: a body normalised to "THE" matched every question."""
        from app.models.water import WaterBody
        from app.water.rag import resolve_entities

        db, _ = water_db
        db.add(
            WaterBody(
                slug="the-river",
                name="The River",
                normalized_name="THE",
                water_type="river",
            )
        )
        db.add(
            WaterBody(
                slug="red-lake", name="Red Lake", normalized_name="RED", water_type="lake"
            )
        )
        db.commit()
        r = resolve_entities(db, "What is the status of the red fort area?")
        assert [b.slug for b in r.water_bodies] == []
        r = resolve_entities(db, "How is Red Lake?")
        assert [b.slug for b in r.water_bodies] == ["red-lake"]

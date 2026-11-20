"""The knowledge graph must contain only relationships that exist as rows.

The failure mode worth guarding is not a crash: it is a graph that looks
plausible and contains an edge nobody stored. Every test here checks that an
edge in the output corresponds to a foreign key value in the database.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.knowledge_graph.builder import build_graph, graph_summary
from app.models.enums import EvidenceLevel
from app.models.pollution import (
    PollutionEvent,
    Region,
    RiskAssessment,
    SatelliteObservation,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select


@pytest.fixture
def linked_records(db):
    """One region, one observation, one event and one risk assessment.

    Built through the ORM so the links are genuine foreign keys rather than
    something the test asserts into being.
    """
    region = Region(
        code="test_sea_ne",
        name="Test Sea NE",
        parent_code="Test Sea",
        min_lon=0.0,
        min_lat=0.0,
        max_lon=1.0,
        max_lat=1.0,
        centroid_lat=0.5,
        centroid_lon=0.5,
    )
    db.add(region)
    db.flush()

    observation = SatelliteObservation(
        observation_id="obs_graph_test",
        region_id=region.id,
        collection="COPERNICUS/S1_GRD",
        platform="Sentinel-1",
        acquired_at=datetime.now(UTC),
        mean_db=-24.0,
        evidence_level=str(EvidenceLevel.SIMULATED),
    )
    db.add(observation)
    db.flush()

    event = PollutionEvent(
        event_id="evt_graph_test",
        region_id=region.id,
        observation_id=observation.id,
        signature="oil_like_signature",
        detection_method="sar_dark_formation",
        evidence_level=str(EvidenceLevel.SIMULATED),
        confidence=0.7,
        latitude=0.5,
        longitude=0.5,
        risk_score=61.0,
        severity="HIGH",
        detected_at=datetime.now(UTC),
    )
    db.add(event)
    db.flush()

    db.add(
        RiskAssessment(
            assessment_id="risk_graph_test",
            event_id=event.id,
            score=61.0,
            severity="HIGH",
            engine_version="1.0.0",
            contributions=[],
            missing_factors=[],
            evidence_level=str(EvidenceLevel.INFERRED),
            narrative="test",
        )
    )
    db.commit()
    return {"region": region, "observation": observation, "event": event}


class TestGraphContainsOnlyRealEdges:
    def test_a_region_reaches_its_own_event_and_observation(
        self, db, linked_records
    ) -> None:
        region = linked_records["region"]
        graph = build_graph(db, "region", str(region.id), depth=2)

        types = {n["type"] for n in graph["nodes"]}
        assert {"region", "pollution_event", "satellite_observation"} <= types
        relations = {e["relation"] for e in graph["edges"]}
        assert {"occurs_in", "covers"} <= relations

    def test_every_edge_corresponds_to_a_stored_foreign_key(
        self, db, linked_records
    ) -> None:
        """The whole point: no edge may exist without a row behind it."""
        graph = build_graph(db, "region", str(linked_records["region"].id), depth=2)
        nodes = {n["id"]: n for n in graph["nodes"]}

        for edge in graph["edges"]:
            assert edge["source"] in nodes, "edge points at a node not returned"
            assert edge["target"] in nodes, "edge points at a node not returned"

            _, source_key = edge["source"].split(":", 1)
            _, target_key = edge["target"].split(":", 1)

            if edge["relation"] == "occurs_in":
                event = db.get(PollutionEvent, int(source_key))
                assert event is not None
                assert str(event.region_id) == target_key
            elif edge["relation"] == "detected_by":
                event = db.get(PollutionEvent, int(source_key))
                assert event is not None
                assert str(event.observation_id) == target_key
            elif edge["relation"] == "covers":
                observation = db.get(SatelliteObservation, int(source_key))
                assert observation is not None
                assert str(observation.region_id) == target_key
            elif edge["relation"] == "assesses":
                assessment = db.get(RiskAssessment, int(source_key))
                assert assessment is not None
                assert str(assessment.event_id) == target_key
            else:  # pragma: no cover - a new relation needs a check here
                raise AssertionError(f"unchecked relation {edge['relation']}")

    def test_an_isolated_region_returns_itself_and_no_edges(self, db) -> None:
        """'No linked records' must be a real answer, not an empty failure."""
        lonely = Region(
            code="lonely_sea",
            name="Lonely Sea",
            parent_code="Lonely",
            min_lon=0.0,
            min_lat=0.0,
            max_lon=1.0,
            max_lat=1.0,
            centroid_lat=0.5,
            centroid_lon=0.5,
        )
        db.add(lonely)
        db.commit()

        graph = build_graph(db, "region", str(lonely.id), depth=2)
        assert graph["node_count"] == 1
        assert graph["edges"] == []

    def test_nodes_keep_their_own_evidence_level(self, db, linked_records) -> None:
        graph = build_graph(db, "region", str(linked_records["region"].id), depth=2)
        by_type = {n["type"]: n for n in graph["nodes"]}
        assert by_type["pollution_event"]["evidence_level"] == "SIMULATED"
        # A region is configuration, not a measurement, so it must not borrow
        # an evidence level from its neighbours.
        assert by_type["region"]["evidence_level"] is None


class TestDepthAndLimit:
    def test_depth_one_stops_before_the_second_hop(self, db, linked_records) -> None:
        shallow = build_graph(db, "region", str(linked_records["region"].id), depth=1)
        deep = build_graph(db, "region", str(linked_records["region"].id), depth=2)
        # The risk assessment hangs off the event, so it is only reachable at
        # depth 2.
        assert "risk_assessment" not in {n["type"] for n in shallow["nodes"]}
        assert "risk_assessment" in {n["type"] for n in deep["nodes"]}

    def test_limit_is_respected_and_truncation_is_declared(
        self, db, linked_records
    ) -> None:
        graph = build_graph(
            db, "region", str(linked_records["region"].id), depth=2, limit=2
        )
        assert graph["node_count"] <= 2
        assert graph["truncated"] is True

    def test_an_untruncated_graph_says_so(self, db, linked_records) -> None:
        graph = build_graph(db, "region", str(linked_records["region"].id), depth=2)
        assert graph["truncated"] is False


class TestSummary:
    def test_counts_match_the_tables(self, db, linked_records) -> None:
        summary = graph_summary(db)
        assert summary["node_counts"]["region"] == db.scalar(
            select(func.count(Region.id))
        )
        assert summary["node_counts"]["pollution_event"] == db.scalar(
            select(func.count(PollutionEvent.id))
        )
        assert summary["edge_counts"]["assesses"] == db.scalar(
            select(func.count(RiskAssessment.id)).where(
                RiskAssessment.event_id.is_not(None)
            )
        )

    def test_it_states_that_regulations_are_absent(self, db) -> None:
        """The placeholder page promised regulation nodes; no FK supports them."""
        assert any("regulation" in note for note in graph_summary(db)["notes"])


class TestEndpoint:
    def test_summary_is_not_swallowed_by_the_graph_route(
        self, client: TestClient
    ) -> None:
        response = client.get("/api/v1/knowledge-graph/summary")
        assert response.status_code == 200
        assert "node_counts" in response.json()

    def test_an_unknown_centre_is_404(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/knowledge-graph",
            params={"center_type": "region", "center_id": "no-such-region"},
        )
        assert response.status_code == 404

    def test_an_unknown_centre_type_is_400_and_lists_the_valid_ones(
        self, client: TestClient
    ) -> None:
        response = client.get(
            "/api/v1/knowledge-graph",
            params={"center_type": "wormhole", "center_id": "1"},
        )
        assert response.status_code == 400
        assert "region" in response.json()["detail"]

    def test_depth_above_two_is_rejected(self, client: TestClient) -> None:
        response = client.get("/api/v1/knowledge-graph", params={"depth": 5})
        assert response.status_code == 422

    def test_a_region_with_no_links_returns_itself_and_no_edges(
        self, client: TestClient
    ) -> None:
        """A region with nothing attached to it.

        Start-up bootstraps regions but no events, which is the "no linked
        records" state the page has to render without inventing anything.
        """
        body = client.get("/api/v1/knowledge-graph").json()
        assert body["node_count"] == 1
        assert body["nodes"][0]["type"] == "region"
        assert body["edges"] == []

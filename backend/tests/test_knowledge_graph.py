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
        """The whole point: no edge may exist without a row behind it.

        Scoped to ``foreign_key`` edges. Citation edges are resolved out of a
        JSON column rather than joined, so they are checked separately in
        :class:`TestCitationEdges` -- they must still resolve, but they are
        not declared relationships and must not be claimed as such.
        """
        graph = build_graph(db, "region", str(linked_records["region"].id), depth=2)
        nodes = {n["id"]: n for n in graph["nodes"]}

        foreign_key_edges = [
            e for e in graph["edges"] if e["edge_kind"] == "foreign_key"
        ]
        assert foreign_key_edges, "no foreign-key edges to check"

        for edge in foreign_key_edges:
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

    def test_it_states_how_citations_differ_from_foreign_keys(self, db) -> None:
        """Documents are reachable now, but not as declared relationships.

        This replaces an earlier assertion that regulation nodes were absent.
        They are present, resolved from reports.sources -- so the claim worth
        guarding is no longer "there are none" but "these are not foreign
        keys", which is the thing a reader could otherwise be misled about.
        """
        notes = graph_summary(db)["notes"]
        assert any("JSON column" in note for note in notes)
        assert any("no foreign keys of its own" in note for note in notes)


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


class TestCitationEdges:
    """Citation edges, which are resolved rather than joined.

    They get their own guarantee: every one must land on a document that
    actually exists, and the graph must never claim a citation is a declared
    relationship.
    """

    @pytest.fixture
    def report_with_sources(self, db, linked_records):
        from app.models.intelligence import Report, ResearchDocument

        real = ResearchDocument(
            document_id="marpol-annex-i",
            title="MARPOL Annex I",
            doc_type="regulation",
        )
        db.add(real)
        db.add(
            Report(
                report_id="rpt_graph_test",
                event_id=linked_records["event"].id,
                workflow_id="wf_test",
                title="Test report",
                summary="summary",
                sections={},
                provenance={},
                # One id that resolves and one that does not, because a JSON
                # column has nothing stopping it from dangling.
                sources=[
                    {"document_id": "marpol-annex-i", "title": "MARPOL Annex I"},
                    {"document_id": "deleted-document", "title": "Gone"},
                ],
                generated_by="test",
                contains_simulated_data=True,
            )
        )
        db.commit()
        return real

    def test_a_cites_edge_lands_on_a_real_document(
        self, db, linked_records, report_with_sources
    ) -> None:
        from app.models.intelligence import ResearchDocument

        graph = build_graph(db, "report", "rpt_graph_test", depth=1)
        cites = [e for e in graph["edges"] if e["relation"] == "cites"]
        assert cites, "no citation edges produced"

        for edge in cites:
            assert edge["edge_kind"] == "resolved_reference"
            node_type, key = edge["target"].split(":", 1)
            assert node_type == "research_document"
            assert db.get(ResearchDocument, int(key)) is not None

    def test_an_unresolvable_citation_is_counted_not_drawn(
        self, db, linked_records, report_with_sources
    ) -> None:
        graph = build_graph(db, "report", "rpt_graph_test", depth=1)
        assert graph["unresolved_citations"] == 1
        assert any("do not resolve" in n or "not drawn" in n for n in graph["notes"])
        # Exactly one of the two ids resolved, so exactly one edge is drawn.
        assert len([e for e in graph["edges"] if e["relation"] == "cites"]) == 1

    def test_citations_are_never_labelled_as_foreign_keys(
        self, db, linked_records, report_with_sources
    ) -> None:
        graph = build_graph(db, "report", "rpt_graph_test", depth=1)
        for edge in graph["edges"]:
            if edge["relation"] == "cites":
                assert edge["edge_kind"] != "foreign_key"
            else:
                assert edge["edge_kind"] == "foreign_key"

    def test_a_document_reaches_the_reports_that_cite_it(
        self, db, linked_records, report_with_sources
    ) -> None:
        graph = build_graph(db, "research_document", "marpol-annex-i", depth=1)
        assert any(e["relation"] == "cites" for e in graph["edges"])
        assert any(n["type"] == "report" for n in graph["nodes"])

    def test_summary_counts_citations_separately(self, db, report_with_sources) -> None:
        summary = graph_summary(db)
        assert summary["edge_counts"]["cites"] == 1
        assert summary["edge_kinds"]["resolved_reference"] == 1
        assert summary["unresolved_citations"] == 1

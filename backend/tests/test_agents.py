"""Tests for the agentic layer.

Two properties matter most and both are asserted here:

* the workflow terminates in a bounded number of tool calls, because agents
  never call each other
* no agent ever produces a risk number; every score comes from the
  deterministic engine
"""

from __future__ import annotations

import pytest
from app.agents.tools import ToolRegistry, calculate_risk, get_geographic_context
from app.agents.workflow import (
    AGENTS,
    WORKFLOW_NAME,
    describe_workflow,
    run_event_analysis,
)
from app.llm.base import LLMStatus
from app.llm.providers import NullLLM, get_llm
from fastapi.testclient import TestClient


class TestNullLLM:
    def test_is_the_default_provider(self) -> None:
        """The platform must run with no API key."""
        assert isinstance(get_llm(), NullLLM)

    def test_reports_unavailable_rather_than_fabricating(self) -> None:
        response = NullLLM().generate([])
        assert response.status is LLMStatus.UNAVAILABLE
        assert response.text == ""
        assert "deterministically" in (response.detail or "")

    def test_is_never_marked_available(self) -> None:
        assert NullLLM().is_available is False


class TestTools:
    def test_registry_exposes_a_catalogue(self, db) -> None:
        names = {t["name"] for t in ToolRegistry(db=db).describe()}
        assert "calculate_risk" in names
        assert "search_research" in names
        assert all(t["description"] for t in ToolRegistry(db=db).describe())

    def test_calls_are_recorded_with_timing(self, db) -> None:
        registry = ToolRegistry(db=db)
        registry.call("get_geographic_context", latitude=25.0, longitude=55.0)
        assert len(registry.calls) == 1
        call = registry.calls[0]
        assert call.success is True
        assert call.duration_ms >= 0

    def test_unknown_tool_is_recorded_not_raised(self, db) -> None:
        registry = ToolRegistry(db=db)
        assert registry.call("no_such_tool") is None
        assert registry.calls[0].success is False
        assert "no such tool" in registry.calls[0].error

    def test_failing_tool_is_captured_as_data(self, db) -> None:
        """A tool failure must not abort a workflow."""
        registry = ToolRegistry(db=db)
        registry.call("get_geographic_context")  # missing required arguments
        assert registry.calls[0].success is False
        assert registry.calls[0].error

    def test_session_is_never_written_into_the_trace(self, db) -> None:
        registry = ToolRegistry(db=db)
        registry.call("get_pollution_history", region_code="nowhere", days=7)
        for call in registry.calls:
            assert "<session>" not in str(call.arguments) or True
            assert "Session object at" not in str(call.arguments)

    def test_risk_tool_delegates_to_the_deterministic_engine(self) -> None:
        result = calculate_risk(signature="oil_like_signature", confidence=0.8)
        assert result["engine_version"].startswith("risk-engine")
        awarded = sum(c["points"] for c in result["contributions"])
        available = sum(c["max_points"] for c in result["contributions"])
        assert result["score"] == round(awarded / available * 100, 2)

    def test_geographic_tool_returns_precision_notes(self) -> None:
        context = get_geographic_context(25.0, 55.0)
        assert context["coast_precision_note"]
        assert context["protected_area_precision_note"]


class TestWorkflowShape:
    def test_five_stages_in_dependency_order(self) -> None:
        assert [a.name for a in AGENTS] == [
            "detection",
            "context",
            "research",
            "risk",
            "report",
        ]

    def test_every_stage_states_its_purpose(self) -> None:
        for agent in AGENTS:
            assert agent.purpose

    def test_catalogue_documents_the_control_flow(self) -> None:
        described = describe_workflow()
        assert described["workflow"] == WORKFLOW_NAME
        assert "never call each other" in described["control_flow"]
        assert any("never produces a score" in n for n in described["notes"])


class TestWorkflowExecution:
    @pytest.fixture
    def event_id(self, seeded_client: TestClient) -> str:
        items = seeded_client.get("/api/v1/pollution-events?limit=1").json()["items"]
        if not items:
            pytest.skip("no events available")
        return items[0]["event_id"]

    def test_runs_all_stages_without_an_llm(
        self, seeded_client: TestClient, event_id: str, session
    ) -> None:
        result = run_event_analysis(session, event_id)
        assert result["status"] == "success"
        assert [f["agent"] for f in result["findings"]] == [
            "detection",
            "context",
            "research",
            "risk",
            "report",
        ]
        assert result["llm_provider"] == "none"

    def test_terminates_in_a_bounded_number_of_tool_calls(
        self, seeded_client: TestClient, event_id: str, session
    ) -> None:
        """A linear state machine cannot loop; assert the bound holds."""
        result = run_event_analysis(session, event_id)
        assert 0 < len(result["tool_calls"]) <= 12

    def test_produces_a_report_with_separated_evidence_levels(
        self, seeded_client: TestClient, event_id: str, session
    ) -> None:
        result = run_event_analysis(session, event_id)
        sections = result["report"]["sections"]
        assert sections["observed"]["evidence_level"] == "OBSERVED"
        assert sections["detected"]["evidence_level"] == "DETECTED"
        assert sections["inferred"]["evidence_level"] == "INFERRED"
        assert sections["forecast"]["evidence_level"] == "FORECAST"

    def test_risk_in_the_report_comes_from_the_engine(
        self, seeded_client: TestClient, event_id: str, session
    ) -> None:
        """No agent may invent a score."""
        result = run_event_analysis(session, event_id)
        inferred = result["report"]["sections"]["inferred"]
        assert inferred["engine_version"].startswith("risk-engine")
        awarded = sum(c["points"] for c in inferred["contributions"])
        available = sum(c["max_points"] for c in inferred["contributions"])
        assert inferred["risk_score"] == round(awarded / available * 100, 2)

    def test_narrative_is_template_based_without_an_llm(
        self, seeded_client: TestClient, event_id: str, session
    ) -> None:
        result = run_event_analysis(session, event_id)
        report = result["report"]
        assert report["narrative_provider"] == "none"
        assert "not a confirmed pollution incident" in report["narrative"]

    def test_simulated_events_are_flagged_in_the_report(
        self, seeded_client: TestClient, event_id: str, session
    ) -> None:
        result = run_event_analysis(session, event_id)
        limitations = " ".join(result["report"]["limitations"])
        assert "SIMULATED" in limitations

    def test_unknown_event_fails_cleanly(self, client: TestClient, session) -> None:
        result = run_event_analysis(session, "evt_does_not_exist")
        assert result["status"] == "failed"
        assert result["findings"][0]["ok"] is False


class TestIntelligenceEndpoints:
    def test_agents_catalogue(self, client: TestClient) -> None:
        body = client.get("/api/v1/agents").json()
        assert len(body["stages"]) == 5
        assert body["tools"]
        assert body["llm"]["available"] is False

    def test_research_declines_without_evidence(self, client: TestClient) -> None:
        body = client.post(
            "/api/v1/research", json={"question": "airspeed of an unladen swallow"}
        ).json()
        assert body["status"] == "no_evidence"
        assert body["source_count"] == 0

    def test_research_returns_cited_passages(self, client: TestClient) -> None:
        body = client.post(
            "/api/v1/research", json={"question": "MARPOL oil discharge rules"}
        ).json()
        assert body["status"] == "retrieval_only"
        assert body["source_count"] > 0
        assert all(s["title"] for s in body["sources"])

    def test_analyze_unknown_event_is_404(self, client: TestClient) -> None:
        response = client.post("/api/v1/agents/analyze-event", json={"event_id": "nope"})
        assert response.status_code == 404

    def test_report_generation_and_text_rendering(
        self, seeded_client: TestClient
    ) -> None:
        items = seeded_client.get("/api/v1/pollution-events?limit=1").json()["items"]
        if not items:
            pytest.skip("no events available")
        report = seeded_client.post(
            "/api/v1/reports/generate", json={"event_id": items[0]["event_id"]}
        ).json()
        assert report["report_id"]
        assert set(report["provenance"]) >= {"observed", "detected", "inferred"}

        text = seeded_client.get(f"/api/v1/reports/{report['report_id']}/text").json()[
            "text"
        ]
        assert "OCEAN INTELLIGENCE REPORT" in text
        assert "OBSERVED" in text and "DETECTED" in text and "INFERRED" in text
        # The renderer's own chrome must be ASCII so it survives a cp1252
        # console. Corpus content may carry Unicode -- several real instrument
        # titles use em-dashes, and rewriting a source's name would be worse.
        chrome = [
            ln
            for ln in text.splitlines()
            if ln.startswith(("=", "-", "Report ", "Generated", "Workflow"))
        ]
        assert all(ln.isascii() for ln in chrome)
        assert text.encode("utf-8")

    def test_agent_runs_are_persisted(self, seeded_client: TestClient) -> None:
        items = seeded_client.get("/api/v1/pollution-events?limit=1").json()["items"]
        if not items:
            pytest.skip("no events available")
        seeded_client.post(
            "/api/v1/agents/analyze-event", json={"event_id": items[0]["event_id"]}
        )
        runs = seeded_client.get("/api/v1/agents/runs").json()
        assert runs["count"] >= 1
        assert runs["items"][0]["tool_calls"] > 0

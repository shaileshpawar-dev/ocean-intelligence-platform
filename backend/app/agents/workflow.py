"""Multi-agent workflow for analysing a pollution event.

Control flow
------------
This is a **linear state machine**, not a conversation between agents:

    Detection -> Context -> Research -> Risk -> Report

Each stage reads the shared :class:`AgentContext`, calls tools, writes its
findings back, and hands on. Agents never call each other and never loop, so
the workflow terminates in a bounded number of tool calls by construction.
Free-form agent-to-agent delegation is where cost and latency become
unpredictable, and it buys nothing here: the dependency order between these
five stages is known in advance.

Degradation
-----------
Every stage works with no LLM. The agents' substance -- the measurements, the
risk arithmetic, the retrieved passages -- is computed by tools over real
data. An LLM, when configured, adds a prose ``narrative`` to the report and
nothing else. It never produces a score, a confidence or an area.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agents.tools import ToolRegistry
from app.core.logging import get_logger
from app.llm.base import LLMMessage
from app.llm.providers import get_llm
from app.models import AgentRun, AgentRunStatus, EvidenceLevel, Report
from app.models.pollution import PollutionEvent

logger = get_logger(__name__)

WORKFLOW_NAME = "event-intelligence-v1"


@dataclass(slots=True)
class AgentFinding:
    """What one agent concluded.

    ``reasoning_summary`` is a short, human-readable statement of *why*, built
    from the data the agent saw. Raw chain-of-thought is never requested from
    a model, never stored and never returned.
    """

    agent: str
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    evidence_level: str = str(EvidenceLevel.INFERRED)
    concerns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the finding."""
        return {
            "agent": self.agent,
            "ok": self.ok,
            "summary": self.summary,
            "data": self.data,
            "evidence_level": self.evidence_level,
            "concerns": self.concerns,
        }


@dataclass(slots=True)
class AgentContext:
    """Shared state threaded through the workflow."""

    db: Session
    event_id: str
    tools: ToolRegistry
    findings: dict[str, AgentFinding] = field(default_factory=dict)
    event: dict | None = None
    region_code: str | None = None

    def record(self, finding: AgentFinding) -> None:
        """Store a finding under its agent name."""
        self.findings[finding.agent] = finding

    def data(self, agent: str) -> dict:
        """Findings data for one agent, or an empty dict."""
        finding = self.findings.get(agent)
        return finding.data if finding else {}


class BaseAgent(ABC):
    """One stage of the workflow."""

    name: str = "agent"
    purpose: str = ""

    @abstractmethod
    def run(self, ctx: AgentContext) -> AgentFinding:
        """Do this stage's work and return its finding."""

    def describe(self) -> dict:
        """Agent metadata for the API."""
        return {"name": self.name, "purpose": self.purpose}


class DetectionAgent(BaseAgent):
    """Reads the detection and judges how much it can support."""

    name = "detection"
    purpose = (
        "Load the detection and its measurement, check confidence and "
        "calibration, and surface anything anomalous about the claim."
    )

    def run(self, ctx: AgentContext) -> AgentFinding:
        """Load the event and assess the strength of its claim."""
        event = ctx.tools.call("get_pollution_event", event_id=ctx.event_id)
        if event is None:
            return AgentFinding(
                agent=self.name,
                ok=False,
                summary=f"No detection found with id {ctx.event_id!r}.",
                concerns=["Workflow cannot proceed without an event."],
            )

        ctx.event = event
        ctx.region_code = event.get("region_code")
        observation = ctx.tools.call("get_satellite_observation", event_id=ctx.event_id)

        concerns: list[str] = []
        confidence = event.get("confidence") or 0.0
        if not event.get("confidence_is_calibrated", False):
            concerns.append(
                "Confidence is an uncalibrated detector score, not a "
                "probability of correctness."
            )
        if confidence < 0.5:
            concerns.append(f"Confidence {confidence:.2f} is low; the signature is weak.")
        if event.get("is_simulated"):
            concerns.append(
                "This detection is SIMULATED demo data and describes no real "
                "satellite acquisition."
            )
        if event.get("signature") == "dark_formation":
            concerns.append(
                "Signature is a bare dark formation: the cause is "
                "undetermined and includes low-wind and biogenic look-alikes."
            )
        if observation and observation.get("contrast_db") is not None:
            contrast = observation["contrast_db"]
            if contrast < 3.0:
                concerns.append(
                    f"Backscatter contrast {contrast} dB is low, which is more "
                    "consistent with a uniformly dark low-wind sea than with a "
                    "localised film."
                )

        return AgentFinding(
            agent=self.name,
            ok=True,
            summary=(
                f"{event['signature'].replace('_', ' ')} in "
                f"{event.get('region_name')} at confidence {confidence:.2f}, "
                f"detected by {event.get('model_version')}."
            ),
            data={"event": event, "observation": observation},
            evidence_level=str(EvidenceLevel.DETECTED),
            concerns=concerns,
        )


class ContextAgent(BaseAgent):
    """Assembles geography and observed history around the detection."""

    name = "context"
    purpose = (
        "Gather geographic context and the region's observed history so the "
        "detection can be judged against its surroundings and its past."
    )

    def run(self, ctx: AgentContext) -> AgentFinding:
        """Collect geography, history and forecast for the region."""
        if ctx.event is None:
            return AgentFinding(agent=self.name, ok=False, summary="No event in context.")

        geography = ctx.tools.call(
            "get_geographic_context",
            latitude=ctx.event["latitude"],
            longitude=ctx.event["longitude"],
        )
        # A stage-2 sub-cell is newly created and has almost no history of its
        # own, so fall back to its parent screening cell. Reporting "0 observed
        # days" for a refined detection would understate the evidence that
        # actually exists for that patch of ocean.
        history = ctx.tools.call(
            "get_pollution_history", region_code=ctx.region_code, days=60
        )
        history_scope = ctx.region_code
        parent = _parent_code(ctx.region_code)
        if (history or {}).get("coverage_days", 0) == 0 and parent != ctx.region_code:
            parent_history = ctx.tools.call(
                "get_pollution_history", region_code=parent, days=60
            )
            if (parent_history or {}).get("coverage_days", 0) > 0:
                history = parent_history
                history_scope = parent

        forecast = ctx.tools.call("get_forecast", region_code=parent, horizon=7)

        concerns: list[str] = []
        if geography:
            concerns.append(geography["coast_precision_note"])
            concerns.append(geography["protected_area_precision_note"])
        coverage = (history or {}).get("coverage_ratio")
        if coverage is not None and coverage < 0.5:
            concerns.append(
                f"Only {coverage:.0%} of the 60-day window was observed; gaps "
                "are satellite revisit intervals, not quiet water."
            )
        if history_scope != ctx.region_code:
            concerns.append(
                f"History and forecast are for the parent screening cell "
                f"{history_scope}, not the refined sub-cell, which has too "
                "little history of its own."
            )
        if forecast and forecast.get("beats_naive") is False:
            concerns.append(
                "The forecast model did not beat a naive last-value baseline "
                "in backtesting; treat its point values as weakly supported."
            )

        distance = (geography or {}).get("distance_to_coast_km")
        return AgentFinding(
            agent=self.name,
            ok=True,
            summary=(
                f"~{distance:.0f} km from the nearest coastal reference; "
                f"{(history or {}).get('coverage_days', 0)} observed days in "
                "the last 60."
                if distance is not None
                else "Geographic context assembled."
            ),
            data={
                "geography": geography,
                "history": history,
                "history_scope": history_scope,
                "forecast": forecast,
            },
            evidence_level=str(EvidenceLevel.OBSERVED),
            concerns=concerns,
        )


class ResearchAgent(BaseAgent):
    """Retrieves regulatory and methodological context."""

    name = "research"
    purpose = (
        "Retrieve regulations and methodology notes relevant to this "
        "signature and region, with citations."
    )

    def run(self, ctx: AgentContext) -> AgentFinding:
        """Search the corpus using terms drawn from the detection itself."""
        if ctx.event is None:
            return AgentFinding(agent=self.name, ok=False, summary="No event in context.")

        signature = ctx.event["signature"].replace("_", " ")
        parent = ctx.event.get("parent_region") or ""
        query = f"{signature} {parent} discharge regulation response".strip()
        passages = ctx.tools.call("search_research", query=query, limit=4) or []

        return AgentFinding(
            agent=self.name,
            ok=True,
            summary=(
                f"{len(passages)} corpus passage(s) retrieved for "
                f"'{signature}' in {parent or 'the region'}."
            ),
            data={"query": query, "passages": passages},
            evidence_level=str(EvidenceLevel.OBSERVED),
            concerns=(
                []
                if passages
                else ["No corpus passage matched; no regulatory context available."]
            ),
        )


class RiskAgent(BaseAgent):
    """Interprets the deterministic risk score. It does not compute one."""

    name = "risk"
    purpose = (
        "Interpret the risk engine's output: which factors dominated, which "
        "were unavailable, and how complete the assessment is."
    )

    def run(self, ctx: AgentContext) -> AgentFinding:
        """Read the stored assessment and describe what drove it."""
        if ctx.event is None:
            return AgentFinding(agent=self.name, ok=False, summary="No event in context.")

        assessment = ctx.event.get("risk_assessment")
        if not assessment:
            # Recompute through the same engine the API uses, never estimate.
            assessment = ctx.tools.call(
                "calculate_risk",
                signature=ctx.event["signature"],
                confidence=ctx.event["confidence"],
                latitude=ctx.event["latitude"],
                longitude=ctx.event["longitude"],
                estimated_area_km2=ctx.event.get("estimated_area_km2"),
            )
        if not assessment:
            return AgentFinding(
                agent=self.name, ok=False, summary="Risk engine unavailable."
            )

        contributions = sorted(
            assessment.get("contributions", []),
            key=lambda c: c["points"],
            reverse=True,
        )
        missing = assessment.get("missing_factors", []) or []
        top = ", ".join(
            f"{c['factor'].replace('_', ' ')} {c['points']:.1f}/{c['max_points']:.0f}"
            for c in contributions[:3]
        )

        concerns: list[str] = []
        if missing:
            concerns.append(
                f"{len(missing)} factor(s) could not be evaluated "
                f"({', '.join(missing)}). The score is renormalised over the "
                "rest, so this is a partial assessment rather than a low one."
            )

        return AgentFinding(
            agent=self.name,
            ok=True,
            summary=(
                f"Risk {assessment['score']:.1f}/100 ({assessment['severity']}), "
                f"driven by {top}."
            ),
            data={"assessment": assessment},
            evidence_level=str(EvidenceLevel.INFERRED),
            concerns=concerns,
        )


class ReportAgent(BaseAgent):
    """Assembles the final report, separating evidence levels."""

    name = "report"
    purpose = (
        "Compose the environmental intelligence report, keeping observed, "
        "detected, inferred, forecast and retrieved content distinct."
    )

    def run(self, ctx: AgentContext) -> AgentFinding:
        """Build the structured report sections and an optional narrative."""
        if ctx.event is None:
            return AgentFinding(agent=self.name, ok=False, summary="No event in context.")

        event = ctx.event
        context_data = ctx.data("context")
        research_data = ctx.data("research")
        risk_data = ctx.data("risk")
        assessment = risk_data.get("assessment", {})
        observation = ctx.data("detection").get("observation") or {}
        geography = context_data.get("geography") or {}
        history = context_data.get("history") or {}
        forecast = context_data.get("forecast") or {}

        sections = {
            "observed": {
                "evidence_level": str(EvidenceLevel.OBSERVED),
                "region": event.get("region_name"),
                "coordinates": [event["latitude"], event["longitude"]],
                "acquired_at": observation.get("acquired_at"),
                "platform": observation.get("platform"),
                "collection": observation.get("collection"),
                "mean_backscatter_db": observation.get("mean_db"),
                "contrast_db": observation.get("contrast_db"),
                "distance_to_coast_km": geography.get("distance_to_coast_km"),
                "nearest_protected_area": geography.get("nearest_protected_area"),
                "observed_days_in_window": history.get("coverage_days"),
                "coverage_ratio": history.get("coverage_ratio"),
            },
            "detected": {
                "evidence_level": str(EvidenceLevel.DETECTED),
                "signature": event["signature"],
                "confidence": event["confidence"],
                "confidence_is_calibrated": event.get("confidence_is_calibrated", False),
                "detection_method": event.get("detection_method"),
                "model_version": event.get("model_version"),
                "estimated_area_km2": event.get("estimated_area_km2"),
                "area_method": event.get("area_method"),
                "caveats": event.get("caveats", []),
            },
            "inferred": {
                "evidence_level": str(EvidenceLevel.INFERRED),
                "risk_score": assessment.get("score"),
                "severity": assessment.get("severity"),
                "engine_version": assessment.get("engine_version"),
                "contributions": assessment.get("contributions", []),
                "missing_factors": assessment.get("missing_factors", []),
            },
            "forecast": {
                "evidence_level": str(EvidenceLevel.FORECAST),
                "kind": forecast.get("forecast_kind"),
                "status": forecast.get("status"),
                "model": forecast.get("model_name"),
                "beats_naive": forecast.get("beats_naive"),
                "bands": forecast.get("bands", [])[:7],
                "scope_note": (
                    "Forecasts this platform's own detection activity for the "
                    "region. Not a prediction of where a pollutant will travel."
                ),
            },
            "retrieved_evidence": {
                "evidence_level": str(EvidenceLevel.OBSERVED),
                "query": research_data.get("query"),
                "sources": [
                    {
                        "title": p["title"],
                        "document_id": p["document_id"],
                        "doc_type": p["doc_type"],
                        "source_url": p["source_url"],
                        "excerpt": p["text"][:280],
                        "notice": p.get("notice", ""),
                    }
                    for p in research_data.get("passages", [])
                ],
            },
        }

        concerns: list[str] = []
        for finding in ctx.findings.values():
            concerns.extend(finding.concerns)

        recommendations = _recommendations(event, assessment, geography)
        narrative, provider = _narrative(sections, concerns, recommendations)

        return AgentFinding(
            agent=self.name,
            ok=True,
            summary=(
                f"Report assembled for {event['event_id']} with "
                f"{len(sections['retrieved_evidence']['sources'])} source(s)."
            ),
            data={
                "sections": sections,
                "recommendations": recommendations,
                "limitations": sorted(set(concerns)),
                "narrative": narrative,
                "narrative_provider": provider,
            },
            evidence_level=str(EvidenceLevel.INFERRED),
        )


def _recommendations(event: dict, assessment: dict, geography: dict) -> list[str]:
    """Derive recommended actions from the computed values.

    Rule-based on purpose. These are operational suggestions tied to
    thresholds a reader can check, not a model's opinion.
    """
    actions: list[str] = []
    severity = (assessment or {}).get("severity")
    signature = event.get("signature")

    if severity in {"HIGH", "CRITICAL"}:
        actions.append(
            "Task a higher-resolution acquisition or aerial overflight to "
            "confirm the feature before treating it as an incident."
        )
    if signature == "oil_like_signature":
        actions.append(
            "Correlate with AIS vessel tracks over the acquisition window; "
            "satellite detection alone cannot attribute a discharge."
        )
        actions.append(
            "If confirmed, notify the competent national authority under the "
            "OPRC reporting framework."
        )
    if signature == "dark_formation":
        actions.append(
            "Obtain wind-field data for the acquisition time. Below ~3 m/s a "
            "dark formation is not separable from the low-wind background."
        )
    distance = (geography or {}).get("distance_to_protected_area_km")
    if distance is not None and distance < 200:
        actions.append(
            f"Notify the managing authority for "
            f"{geography.get('nearest_protected_area')} "
            f"(~{distance:.0f} km away) as a precaution."
        )
    if not event.get("confidence_is_calibrated", False):
        actions.append(
            "Treat the confidence value as a ranking score, not a probability, "
            "when prioritising this against other detections."
        )
    if event.get("is_simulated"):
        actions.insert(
            0,
            "NO OPERATIONAL ACTION: this detection is simulated demo data.",
        )
    return actions


def _facts_json(observed: dict, detected: dict, inferred: dict) -> str:
    """Serialise the computed facts handed to the LLM, truncated."""
    import json

    payload = {"observed": observed, "detected": detected, "inferred": inferred}
    return json.dumps(payload, default=str)[:3500]


def _facts_json(observed: dict, detected: dict, inferred: dict) -> str:
    """Serialise the computed facts handed to the LLM, truncated.

    Only values the deterministic layer already produced are sent. The model
    is given facts to phrase, never a gap to fill.
    """
    import json

    payload = {"observed": observed, "detected": detected, "inferred": inferred}
    return json.dumps(payload, default=str)[:3500]


def _narrative(
    sections: dict, concerns: list[str], recommendations: list[str]
) -> tuple[str, str]:
    """Produce the prose summary, with or without an LLM.

    The template path is not a degraded fallback -- it is the default, and it
    states only values already computed. The LLM path is given those same
    values and forbidden from adding any.
    """
    detected = sections["detected"]
    inferred = sections["inferred"]
    observed = sections["observed"]

    template = (
        f"A {detected['signature'].replace('_', ' ')} was detected in "
        f"{observed['region']} at an uncalibrated confidence of "
        f"{detected['confidence']:.2f} by {detected['model_version']}. "
        f"The deterministic risk engine scored it "
        f"{inferred['risk_score']:.1f}/100 ({inferred['severity']}) from "
        f"{len(inferred['contributions'])} evaluable factors"
        + (
            f", with {len(inferred['missing_factors'])} factor(s) unavailable"
            if inferred["missing_factors"]
            else ""
        )
        + ". This is a detection, not a confirmed pollution incident."
    )

    llm = get_llm()
    if not llm.is_available:
        return template, "none"

    prompt = (
        "Write a concise 3-4 sentence analyst summary of this marine pollution "
        "detection. Use ONLY the values given. Do not invent numbers, do not "
        "estimate anything, and do not claim the detection proves pollution "
        "occurred. State it as a signature with uncertainty.\n\n"
        f"{_facts_json(observed, detected, inferred)}\n\n"
        f"Known limitations: {'; '.join(concerns[:6])}\n"
        "Recommended actions already derived: " + "; ".join(recommendations[:4])
    )
    response = llm.generate(
        [
            LLMMessage(
                role="system",
                content=(
                    "You summarise environmental detections for analysts. You "
                    "never invent figures and never overstate a detection as a "
                    "confirmed incident."
                ),
            ),
            LLMMessage(role="user", content=prompt),
        ],
        max_tokens=400,
    )
    if response.ok and response.text:
        return response.text, response.provider
    return template, "none"


def _parent_code(region_code: str | None) -> str:
    """Screening-cell code for a possibly-refined region code."""
    if not region_code:
        return ""
    return region_code.split("__")[0]


AGENTS: tuple[BaseAgent, ...] = (
    DetectionAgent(),
    ContextAgent(),
    ResearchAgent(),
    RiskAgent(),
    ReportAgent(),
)


def run_event_analysis(db: Session, event_id: str) -> dict:
    """Execute the full workflow for one event and persist the trace.

    Args:
        db: Active session.
        event_id: The detection to analyse.

    Returns:
        A dict with the workflow id, per-agent findings, the assembled report
        and the full tool-call trace.
    """
    workflow_id = uuid.uuid4().hex[:16]
    started = datetime.now(UTC)
    clock = time.perf_counter()

    tools = ToolRegistry(db=db)
    ctx = AgentContext(db=db, event_id=event_id, tools=tools)
    llm = get_llm()

    run = AgentRun(
        workflow_id=workflow_id,
        workflow_name=WORKFLOW_NAME,
        status=str(AgentRunStatus.RUNNING),
        started_at=started,
        llm_provider=llm.name,
        llm_model=getattr(llm, "model", None),
    )
    db.add(run)
    db.flush()

    failed = False
    for agent in AGENTS:
        finding = agent.run(ctx)
        ctx.record(finding)
        if not finding.ok:
            failed = True
            logger.warning(
                "agent_stage_failed",
                extra={"workflow_id": workflow_id, "agent": agent.name},
            )
            break

    duration_ms = (time.perf_counter() - clock) * 1000
    report_data = ctx.data("report")

    result = {
        "workflow_id": workflow_id,
        "workflow_name": WORKFLOW_NAME,
        "event_id": event_id,
        "status": str(AgentRunStatus.FAILED if failed else AgentRunStatus.SUCCESS),
        "duration_ms": round(duration_ms, 2),
        "llm_provider": llm.name,
        "findings": [f.to_dict() for f in ctx.findings.values()],
        "tool_calls": [c.to_dict() for c in tools.calls],
        "report": report_data,
    }

    run.status = result["status"]
    run.finished_at = datetime.now(UTC)
    run.duration_ms = duration_ms
    run.steps = [
        {**c.to_dict(), "agent": _agent_for_tool(ctx, c.tool)} for c in tools.calls
    ]
    run.result = {
        "findings": result["findings"],
        "report_summary": (report_data or {}).get("narrative"),
    }
    if failed:
        run.error = next(
            (f.summary for f in ctx.findings.values() if not f.ok), "unknown"
        )

    event_row = db.scalar(
        __import__("sqlalchemy")
        .select(PollutionEvent)
        .where(PollutionEvent.event_id == event_id)
    )
    if event_row is not None:
        run.event_id = event_row.id

    if not failed and report_data:
        report = Report(
            report_id=f"rpt_{uuid.uuid4().hex[:12]}",
            event_id=event_row.id if event_row else None,
            workflow_id=workflow_id,
            title=(
                f"Ocean Intelligence Report — {ctx.event.get('region_name')} "
                f"({ctx.event.get('signature')})"
            ),
            summary=report_data.get("narrative"),
            sections=report_data.get("sections", {}),
            provenance={
                section: content.get("evidence_level")
                for section, content in report_data.get("sections", {}).items()
            },
            sources=report_data["sections"]["retrieved_evidence"]["sources"],
            generated_by=(
                f"{WORKFLOW_NAME}; narrative={report_data.get('narrative_provider')}"
            ),
            contains_simulated_data=bool(ctx.event.get("is_simulated")),
        )
        db.add(report)
        db.flush()
        result["report_id"] = report.report_id

    db.commit()
    logger.info(
        "agent_workflow_complete",
        extra={
            "workflow_id": workflow_id,
            "status": result["status"],
            "tool_calls": len(tools.calls),
            "duration_ms": round(duration_ms, 2),
        },
    )
    return result


def _agent_for_tool(ctx: AgentContext, tool_name: str) -> str:
    """Best-effort attribution of a tool call to the stage that made it."""
    mapping = {
        "get_pollution_event": "detection",
        "get_satellite_observation": "detection",
        "get_geographic_context": "context",
        "get_pollution_history": "context",
        "get_forecast": "context",
        "search_research": "research",
        "calculate_risk": "risk",
        "get_region": "context",
    }
    return mapping.get(tool_name, "unknown")


def describe_workflow() -> dict:
    """Workflow and agent catalogue, for the API."""
    return {
        "workflow": WORKFLOW_NAME,
        "control_flow": "linear state machine; agents never call each other",
        "stages": [agent.describe() for agent in AGENTS],
        "notes": [
            "Every stage runs without an LLM. Measurements, risk arithmetic "
            "and retrieval are computed by tools over real data.",
            "An LLM, when configured, writes the report narrative only. It "
            "never produces a score, confidence or area.",
            "Chain-of-thought is never requested or stored; runs persist a "
            "concise summary plus the tool trace.",
        ],
    }

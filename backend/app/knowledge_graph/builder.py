"""A graph over the platform's own records, built only from foreign keys.

Every edge here is a declared relationship in the schema. Nothing is inferred
from proximity, name similarity or an embedding: if two nodes are joined, a
row somewhere holds the other's primary key. That is the whole design
constraint, and it is why this can be trusted as a view of the data rather
than as a picture of what a graph over the data might look like.

Two consequences worth knowing before reading the output:

* **``sar_candidates`` has no foreign keys**, so the SAR candidates form a
  separate connected component from the regions. Centring on a region will
  never reach a candidate, and that absence is real rather than a gap in this
  module.
* **There are no regulation nodes.** ``research_documents`` has no foreign
  keys; the link from a report to the instruments it cites lives in a JSON
  column, not a relationship, so it is out of scope here.

Nodes carry whatever evidence level their own row declares, so a subgraph of
simulated events is visibly a subgraph of simulated events.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.intelligence import AgentRun, Report
from app.models.pollution import (
    PollutionEvent,
    Region,
    RiskAssessment,
    SatelliteObservation,
)
from app.models.sar_candidate import (
    SARCandidate,
    SARCandidateOpticalEvidence,
    SARCandidateReview,
)
from app.models.vessel import Vessel

#: Node types this graph knows how to render. Anything else is not reachable.
NODE_TYPES = (
    "region",
    "pollution_event",
    "satellite_observation",
    "risk_assessment",
    "agent_run",
    "report",
    "sar_candidate",
    "sar_review",
    "optical_evidence",
    "vessel",
)

#: Hard ceiling on a response, so one busy centre cannot return the database.
MAX_NODES = 150


@dataclass(slots=True)
class Node:
    """One record in the graph, with whatever evidence level its row declares."""

    id: str
    type: str
    label: str
    evidence_level: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise for the API."""
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "evidence_level": self.evidence_level,
            "attrs": self.attrs,
        }


def node_id(node_type: str, key: Any) -> str:
    """Stable node identifier: the type and the row's key."""
    return f"{node_type}:{key}"


# ---------------------------------------------------------------------------
# Loading one node by type
# ---------------------------------------------------------------------------
def _region_node(row: Region) -> Node:
    return Node(
        id=node_id("region", row.id),
        type="region",
        label=row.name,
        # Regions are configuration -- where the platform looks -- not a
        # measurement, so they carry no evidence level and must not borrow one.
        evidence_level=None,
        attrs={"code": row.code, "parent": row.parent_code},
    )


def _event_node(row: PollutionEvent) -> Node:
    return Node(
        id=node_id("pollution_event", row.id),
        type="pollution_event",
        label=row.signature.replace("_", " ").title(),
        evidence_level=row.evidence_level,
        attrs={
            "event_id": row.event_id,
            "severity": row.severity,
            "risk_score": row.risk_score,
            "confidence": row.confidence,
            "detected_at": row.detected_at.isoformat() if row.detected_at else None,
        },
    )


def _observation_node(row: SatelliteObservation) -> Node:
    return Node(
        id=node_id("satellite_observation", row.id),
        type="satellite_observation",
        label=f"Observation {row.id}",
        evidence_level=row.evidence_level,
        attrs={
            "platform": getattr(row, "platform", None),
            "mean_db": getattr(row, "mean_db", None),
            "acquired_at": (
                row.acquired_at.isoformat() if getattr(row, "acquired_at", None) else None
            ),
        },
    )


def _risk_node(row: RiskAssessment) -> Node:
    return Node(
        id=node_id("risk_assessment", row.id),
        type="risk_assessment",
        label=f"Risk {row.score:.0f} ({row.severity})",
        evidence_level=row.evidence_level,
        attrs={
            "assessment_id": row.assessment_id,
            "score": row.score,
            "severity": row.severity,
            "engine_version": row.engine_version,
        },
    )


def _agent_run_node(row: AgentRun) -> Node:
    return Node(
        id=node_id("agent_run", row.id),
        type="agent_run",
        label=f"{row.workflow_name} run",
        evidence_level=None,
        attrs={
            "workflow_id": row.workflow_id,
            "status": row.status,
            "llm_provider": row.llm_provider,
            "duration_ms": row.duration_ms,
        },
    )


def _report_node(row: Report) -> Node:
    return Node(
        id=node_id("report", row.id),
        type="report",
        label=row.title,
        # Reports do not carry an evidence level; they carry a flag saying
        # whether anything inside them was simulated. Surface that, not a
        # level the row does not have.
        evidence_level="SIMULATED" if row.contains_simulated_data else None,
        attrs={"report_id": row.report_id, "generated_by": row.generated_by},
    )


def _candidate_node(row: SARCandidate) -> Node:
    return Node(
        id=node_id("sar_candidate", row.id),
        type="sar_candidate",
        label=row.candidate_id,
        # Measured Sentinel-1 data, but an uncalibrated score: say so rather
        # than borrowing one of the simulated levels.
        evidence_level="MEASURED",
        attrs={
            "candidate_id": row.candidate_id,
            "split": row.split,
            "subset": row.subset,
            "raw_confidence": row.raw_confidence,
            "screening_status": row.screening_status,
            "review_status": row.review_status,
            "confidence_is_calibrated": row.confidence_is_calibrated,
        },
    )


def _review_node(row: SARCandidateReview) -> Node:
    return Node(
        id=node_id("sar_review", row.id),
        type="sar_review",
        label=f"Review: {row.decision}"
        if hasattr(row, "decision")
        else "Review",
        evidence_level=None,
        attrs={"review_id": row.review_id},
    )


def _optical_node(row: SARCandidateOpticalEvidence) -> Node:
    return Node(
        id=node_id("optical_evidence", row.id),
        type="optical_evidence",
        label=f"Optical evidence {row.id}",
        evidence_level=None,
        attrs={"scene_id": getattr(row, "scene_id", None)},
    )


def _vessel_node(row: Vessel) -> Node:
    return Node(
        id=node_id("vessel", row.mmsi),
        type="vessel",
        label=row.name or row.mmsi,
        evidence_level=None,
        attrs={
            "mmsi": row.mmsi,
            "vessel_type": row.vessel_type,
            "flag": row.flag_country,
        },
    )


#: How to fetch one node of each type by its primary key.
_LOADERS = {
    "region": (Region, Region.id, _region_node),
    "pollution_event": (PollutionEvent, PollutionEvent.id, _event_node),
    "satellite_observation": (
        SatelliteObservation,
        SatelliteObservation.id,
        _observation_node,
    ),
    "risk_assessment": (RiskAssessment, RiskAssessment.id, _risk_node),
    "agent_run": (AgentRun, AgentRun.id, _agent_run_node),
    "report": (Report, Report.id, _report_node),
    "sar_candidate": (SARCandidate, SARCandidate.id, _candidate_node),
    "sar_review": (SARCandidateReview, SARCandidateReview.id, _review_node),
    "optical_evidence": (
        SARCandidateOpticalEvidence,
        SARCandidateOpticalEvidence.id,
        _optical_node,
    ),
    "vessel": (Vessel, Vessel.mmsi, _vessel_node),
}


def _coerce_key(column: Any, key: Any) -> Any | None:
    """Make ``key`` match the column's type, or None when it cannot.

    Most primary keys here are integers and most callers hold a string from a
    URL. PostgreSQL will not compare the two -- it raises rather than casting
    -- so a non-numeric identifier against an integer key is not a lookup that
    returns nothing, it is an error. Returning None lets the caller fall
    through to the human-facing identifier instead.
    """
    try:
        python_type = column.type.python_type
    except NotImplementedError:  # pragma: no cover - exotic column types
        return key
    if python_type is int:
        try:
            return int(key)
        except (TypeError, ValueError):
            return None
    return key


def load_node(db: Session, node_type: str, key: Any) -> Node | None:
    """Fetch one node, or None when the row does not exist."""
    spec = _LOADERS.get(node_type)
    if spec is None:
        return None
    model, pk, build = spec
    coerced = _coerce_key(pk, key)
    if coerced is None:
        return None
    row = db.scalar(select(model).where(pk == coerced))
    return build(row) if row is not None else None


def resolve_center(db: Session, node_type: str, identifier: str) -> Node | None:
    """Find a centre by primary key, or by the human-facing identifier.

    A caller holding a region code or an ``evt_...`` id should not have to look
    up a surrogate key first.
    """
    direct = load_node(db, node_type, identifier)
    if direct is not None:
        return direct

    alternates = {
        "region": (Region, Region.code, _region_node),
        "pollution_event": (PollutionEvent, PollutionEvent.event_id, _event_node),
        "risk_assessment": (
            RiskAssessment,
            RiskAssessment.assessment_id,
            _risk_node,
        ),
        "report": (Report, Report.report_id, _report_node),
        "sar_candidate": (SARCandidate, SARCandidate.candidate_id, _candidate_node),
    }
    spec = alternates.get(node_type)
    if spec is None:
        return None
    model, column, build = spec
    row = db.scalar(select(model).where(column == identifier))
    return build(row) if row is not None else None


# ---------------------------------------------------------------------------
# Expansion: one hop from a node, along declared foreign keys only
# ---------------------------------------------------------------------------
def _expand(db: Session, node: Node, per_node: int) -> list[tuple[Node, str, bool]]:
    """Neighbours of ``node`` as (neighbour, relation, node_is_source).

    ``node_is_source`` records the direction the foreign key actually points,
    so an edge is never drawn backwards.
    """
    out: list[tuple[Node, str, bool]] = []
    key = node.id.split(":", 1)[1]

    def add(rows: Any, build: Any, relation: str, *, forward: bool) -> None:
        for row in rows:
            out.append((build(row), relation, forward))

    if node.type == "region":
        region_id = int(key)
        add(
            db.scalars(
                select(PollutionEvent)
                .where(PollutionEvent.region_id == region_id)
                .order_by(PollutionEvent.risk_score.desc())
                .limit(per_node)
            ),
            _event_node,
            "occurs_in",
            forward=False,
        )
        add(
            db.scalars(
                select(SatelliteObservation)
                .where(SatelliteObservation.region_id == region_id)
                .order_by(SatelliteObservation.id.desc())
                .limit(per_node)
            ),
            _observation_node,
            "covers",
            forward=False,
        )

    elif node.type == "pollution_event":
        event_id = int(key)
        event = db.scalar(select(PollutionEvent).where(PollutionEvent.id == event_id))
        if event is None:
            return out
        if event.region_id is not None:
            region = db.scalar(select(Region).where(Region.id == event.region_id))
            if region is not None:
                out.append((_region_node(region), "occurs_in", True))
        if event.observation_id is not None:
            obs = db.scalar(
                select(SatelliteObservation).where(
                    SatelliteObservation.id == event.observation_id
                )
            )
            if obs is not None:
                out.append((_observation_node(obs), "detected_by", True))
        add(
            db.scalars(
                select(RiskAssessment)
                .where(RiskAssessment.event_id == event_id)
                .limit(per_node)
            ),
            _risk_node,
            "assesses",
            forward=False,
        )
        add(
            db.scalars(
                select(AgentRun).where(AgentRun.event_id == event_id).limit(per_node)
            ),
            _agent_run_node,
            "analysed",
            forward=False,
        )
        add(
            db.scalars(
                select(Report).where(Report.event_id == event_id).limit(per_node)
            ),
            _report_node,
            "documents",
            forward=False,
        )

    elif node.type == "satellite_observation":
        obs_id = int(key)
        obs = db.scalar(
            select(SatelliteObservation).where(SatelliteObservation.id == obs_id)
        )
        if obs is not None and obs.region_id is not None:
            region = db.scalar(select(Region).where(Region.id == obs.region_id))
            if region is not None:
                out.append((_region_node(region), "covers", True))
        add(
            db.scalars(
                select(PollutionEvent)
                .where(PollutionEvent.observation_id == obs_id)
                .limit(per_node)
            ),
            _event_node,
            "detected_by",
            forward=False,
        )

    elif node.type in ("risk_assessment", "agent_run", "report"):
        model = {
            "risk_assessment": RiskAssessment,
            "agent_run": AgentRun,
            "report": Report,
        }[node.type]
        relation = {
            "risk_assessment": "assesses",
            "agent_run": "analysed",
            "report": "documents",
        }[node.type]
        row = db.scalar(select(model).where(model.id == int(key)))
        if row is not None and row.event_id is not None:
            event = db.scalar(
                select(PollutionEvent).where(PollutionEvent.id == row.event_id)
            )
            if event is not None:
                out.append((_event_node(event), relation, True))

    elif node.type == "sar_candidate":
        candidate = db.scalar(select(SARCandidate).where(SARCandidate.id == int(key)))
        if candidate is None:
            return out
        add(
            db.scalars(
                select(SARCandidateReview)
                .where(SARCandidateReview.candidate_id == candidate.id)
                .limit(per_node)
            ),
            _review_node,
            "reviews",
            forward=False,
        )
        add(
            db.scalars(
                select(SARCandidateOpticalEvidence)
                .where(SARCandidateOpticalEvidence.candidate_id == candidate.id)
                .limit(per_node)
            ),
            _optical_node,
            "corroborates",
            forward=False,
        )
        for vessel in _associated_vessels(db, candidate.candidate_id, per_node):
            out.append((_vessel_node(vessel), "associated_vessel", False))

    elif node.type in ("sar_review", "optical_evidence"):
        model = (
            SARCandidateReview
            if node.type == "sar_review"
            else SARCandidateOpticalEvidence
        )
        relation = "reviews" if node.type == "sar_review" else "corroborates"
        row = db.scalar(select(model).where(model.id == int(key)))
        if row is not None:
            candidate = db.scalar(
                select(SARCandidate).where(SARCandidate.id == row.candidate_id)
            )
            if candidate is not None:
                out.append((_candidate_node(candidate), relation, True))

    elif node.type == "vessel":
        for candidate in _vessel_candidates(db, key, per_node):
            out.append((_candidate_node(candidate), "associated_vessel", True))

    return out


def _associated_vessels(db: Session, candidate_id: str, limit: int) -> list[Vessel]:
    """Vessels linked to a candidate through the association table."""
    from app.models.vessel import CandidateVesselAssociation as Assoc

    mmsis = db.scalars(
        select(Assoc.mmsi).where(Assoc.candidate_id == candidate_id).limit(limit)
    ).all()
    if not mmsis:
        return []
    return list(db.scalars(select(Vessel).where(Vessel.mmsi.in_(mmsis))))


def _vessel_candidates(db: Session, mmsi: str, limit: int) -> list[SARCandidate]:
    from app.models.vessel import CandidateVesselAssociation as Assoc

    ids = db.scalars(
        select(Assoc.candidate_id).where(Assoc.mmsi == mmsi).limit(limit)
    ).all()
    if not ids:
        return []
    return list(
        db.scalars(select(SARCandidate).where(SARCandidate.candidate_id.in_(ids)))
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_graph(
    db: Session,
    center_type: str,
    center_id: str,
    depth: int = 1,
    limit: int = MAX_NODES,
) -> dict | None:
    """Breadth-first subgraph around one node, or None when it does not exist.

    Returns at most ``limit`` nodes. ``truncated`` says whether the walk was
    cut short, so a partial view never passes for a complete one.
    """
    center = resolve_center(db, center_type, center_id)
    if center is None:
        return None

    limit = max(1, min(limit, MAX_NODES))
    nodes: dict[str, Node] = {center.id: center}
    edges: set[tuple[str, str, str]] = set()
    queue: deque[tuple[Node, int]] = deque([(center, 0)])
    truncated = False

    # Enough breadth that a region's busiest neighbours all appear, without
    # letting one hop exhaust the whole budget.
    per_node = max(5, limit // 3)

    while queue:
        node, node_depth = queue.popleft()
        if node_depth >= depth:
            continue
        for neighbour, relation, node_is_source in _expand(db, node, per_node):
            if neighbour.id not in nodes:
                if len(nodes) >= limit:
                    truncated = True
                    continue
                nodes[neighbour.id] = neighbour
                queue.append((neighbour, node_depth + 1))
            source, target = (
                (node.id, neighbour.id) if node_is_source else (neighbour.id, node.id)
            )
            edges.add((source, target, relation))

    return {
        "center": center.id,
        "center_type": center.type,
        "depth": depth,
        "limit": limit,
        "truncated": truncated,
        "nodes": [n.to_dict() for n in nodes.values()],
        "edges": [
            {"source": s, "target": t, "relation": r} for s, t, r in sorted(edges)
        ],
        "node_count": len(nodes),
        "edge_count": len(edges),
        "notes": [
            "Every edge is a declared foreign key. Nothing is inferred.",
            "SAR candidates have no foreign key to a region, so they form a "
            "separate component and cannot be reached from one.",
        ],
    }


def graph_summary(db: Session) -> dict:
    """Node and edge counts straight from the tables."""
    from app.models.vessel import CandidateVesselAssociation as Assoc

    node_counts = {
        "region": db.scalar(select(func.count(Region.id))) or 0,
        "pollution_event": db.scalar(select(func.count(PollutionEvent.id))) or 0,
        "satellite_observation": db.scalar(
            select(func.count(SatelliteObservation.id))
        )
        or 0,
        "risk_assessment": db.scalar(select(func.count(RiskAssessment.id))) or 0,
        "agent_run": db.scalar(select(func.count(AgentRun.id))) or 0,
        "report": db.scalar(select(func.count(Report.id))) or 0,
        "sar_candidate": db.scalar(select(func.count(SARCandidate.id))) or 0,
        "sar_review": db.scalar(select(func.count(SARCandidateReview.id))) or 0,
        "optical_evidence": db.scalar(
            select(func.count(SARCandidateOpticalEvidence.id))
        )
        or 0,
        "vessel": db.scalar(select(func.count(Vessel.mmsi))) or 0,
    }

    # Edge counts are counts of rows whose foreign key is actually set. A
    # nullable FK that is NULL is not an edge.
    edge_counts = {
        "occurs_in": db.scalar(
            select(func.count(PollutionEvent.id)).where(
                PollutionEvent.region_id.is_not(None)
            )
        )
        or 0,
        "detected_by": db.scalar(
            select(func.count(PollutionEvent.id)).where(
                PollutionEvent.observation_id.is_not(None)
            )
        )
        or 0,
        "covers": db.scalar(
            select(func.count(SatelliteObservation.id)).where(
                SatelliteObservation.region_id.is_not(None)
            )
        )
        or 0,
        "assesses": db.scalar(
            select(func.count(RiskAssessment.id)).where(
                RiskAssessment.event_id.is_not(None)
            )
        )
        or 0,
        "analysed": db.scalar(
            select(func.count(AgentRun.id)).where(AgentRun.event_id.is_not(None))
        )
        or 0,
        "documents": db.scalar(
            select(func.count(Report.id)).where(Report.event_id.is_not(None))
        )
        or 0,
        "reviews": db.scalar(select(func.count(SARCandidateReview.id))) or 0,
        "corroborates": db.scalar(
            select(func.count(SARCandidateOpticalEvidence.id))
        )
        or 0,
        "associated_vessel": db.scalar(select(func.count(Assoc.id))) or 0,
    }

    return {
        "node_counts": node_counts,
        "edge_counts": edge_counts,
        "total_nodes": sum(node_counts.values()),
        "total_edges": sum(edge_counts.values()),
        "node_types": list(NODE_TYPES),
        "max_nodes_per_request": MAX_NODES,
        "notes": [
            "Counts are table counts, not a sampled graph.",
            "An edge is a row whose foreign key is set; a nullable FK left "
            "NULL is not counted.",
            "No regulation nodes: research_documents has no foreign keys, and "
            "the citations in reports.sources are JSON rather than a "
            "declared relationship.",
        ],
    }


def default_center(db: Session) -> tuple[str, str] | None:
    """The busiest region, so the first view a reader sees is not empty."""
    row = db.execute(
        select(Region.id, func.count(PollutionEvent.id).label("n"))
        .join(PollutionEvent, PollutionEvent.region_id == Region.id)
        .group_by(Region.id)
        .order_by(func.count(PollutionEvent.id).desc())
        .limit(1)
    ).first()
    if row is None:
        any_region = db.scalar(select(Region.id).limit(1))
        return ("region", str(any_region)) if any_region is not None else None
    return ("region", str(row[0]))


def node_type_counts(nodes: list[dict]) -> dict[str, int]:
    """How many nodes of each type a subgraph holds."""
    return dict(Counter(n["type"] for n in nodes))

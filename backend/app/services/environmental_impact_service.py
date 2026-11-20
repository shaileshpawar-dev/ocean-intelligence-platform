"""Service layer for environmental receptors and spill vulnerability assessment (Phase 17)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.environmental_impact import (
    CandidateEnvironmentalImpact,
    MarineReceptor,
)
from app.models.sar_candidate import SARCandidate
from app.schemas.environmental_impact import (
    CandidateEnvironmentalImpactOut,
    CandidateImpactAssessmentOut,
    MarineReceptorOut,
)
from app.vision.environmental_impact_screener import (
    EnvironmentalImpactScreener,
    seed_marine_receptors,
)

logger = get_logger(__name__)


def list_marine_receptors(
    db: Session,
    category: str | None = None,
    search: str | None = None,
) -> list[MarineReceptorOut]:
    """Retrieve indexed Marine Protected Areas, coral reefs, and coastal intakes."""
    seed_marine_receptors(db)
    query = select(MarineReceptor)
    if category:
        query = query.where(MarineReceptor.category == category)
    if search:
        s = f"%{search.strip().lower()}%"
        query = query.where(
            (MarineReceptor.name.ilike(s)) | (MarineReceptor.jurisdiction.ilike(s))
        )
    query = query.order_by(MarineReceptor.name)
    rows = db.execute(query).scalars().all()
    return [MarineReceptorOut.model_validate(r) for r in rows]


def get_candidate_environmental_impact(
    db: Session,
    candidate_id: str,
) -> CandidateImpactAssessmentOut:
    """Retrieve or auto-evaluate environmental impact for a SAR candidate."""
    impacts = (
        db.query(CandidateEnvironmentalImpact)
        .filter_by(candidate_id=candidate_id)
        .order_by(desc(CandidateEnvironmentalImpact.vulnerability_score))
        .all()
    )

    if not impacts:
        screener = EnvironmentalImpactScreener()
        try:
            impacts = screener.evaluate_candidate(db, candidate_id)
        except ValueError:
            return CandidateImpactAssessmentOut(
                candidate_id=candidate_id,
                max_vulnerability_score=0.0,
                highest_severity="LOW",
                proximate_receptors_count=0,
                impacts=[],
                overall_mitigation_summary="No candidate found for environmental evaluation.",
            )

    impact_outs: list[CandidateEnvironmentalImpactOut] = []
    max_score = 0.0
    highest_sev = "LOW"

    severity_order = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "LOW": 1}

    for imp in impacts:
        rec = imp.receptor
        if imp.vulnerability_score > max_score:
            max_score = imp.vulnerability_score
        if severity_order.get(imp.impact_severity, 1) > severity_order.get(highest_sev, 1):
            highest_sev = imp.impact_severity

        impact_outs.append(
            CandidateEnvironmentalImpactOut(
                id=imp.id,
                candidate_id=imp.candidate_id,
                receptor_id=imp.receptor_id,
                receptor_name=rec.name if rec else "Unknown Receptor",
                category=rec.category if rec else "ECOSYSTEM",
                distance_km=imp.distance_km,
                estimated_arrival_hours=imp.estimated_arrival_hours,
                impact_severity=imp.impact_severity,
                vulnerability_score=imp.vulnerability_score,
                priority_action=imp.priority_action,
            )
        )

    if highest_sev == "CRITICAL":
        summary = (
            f"CRITICAL ENVIRONMENTAL EXPOSURE: Candidate is within immediate proximity "
            f"({impact_outs[0].distance_km} km) of high-vulnerability receptor {impact_outs[0].receptor_name}. "
            "Rapid containment boom deployment recommended."
        )
    elif highest_sev == "HIGH":
        summary = (
            f"HIGH ENVIRONMENTAL RISK: Proximity to {impact_outs[0].receptor_name} ({impact_outs[0].distance_km} km). "
            "Stage nearshore protection assets and monitor drift trajectory."
        )
    elif highest_sev == "MODERATE":
        summary = (
            f"MODERATE VULNERABILITY: Regional proximity ({impact_outs[0].distance_km} km) to {impact_outs[0].receptor_name}. "
            "Coordinate with regional maritime environmental teams."
        )
    else:
        summary = "LOW RECEPTOR EXPOSURE: Surface anomaly is in open water > 100 km from designated sensitive receptors."

    return CandidateImpactAssessmentOut(
        candidate_id=candidate_id,
        max_vulnerability_score=round(max_score, 1),
        highest_severity=highest_sev,
        proximate_receptors_count=len(impact_outs),
        impacts=impact_outs,
        overall_mitigation_summary=summary,
    )


def evaluate_candidate_environmental_impact(
    db: Session,
    candidate_id: str,
) -> CandidateImpactAssessmentOut:
    """Force re-evaluation of environmental impact for a candidate."""
    screener = EnvironmentalImpactScreener()
    screener.evaluate_candidate(db, candidate_id)
    return get_candidate_environmental_impact(db, candidate_id)

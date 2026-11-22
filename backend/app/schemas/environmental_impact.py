"""Pydantic schemas for Marine Protected Areas and environmental vulnerability (Phase 17)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MarineReceptorOut(BaseModel):
    """An ecologically sensitive marine receptor or infrastructure asset."""

    receptor_id: str
    name: str
    category: str
    jurisdiction: str
    latitude: float
    longitude: float
    vulnerability_weight: float
    description: str | None = None

    model_config = {"from_attributes": True}


class CandidateEnvironmentalImpactOut(BaseModel):
    """Specific exposure and impact assessment on a proximate marine receptor."""

    id: int
    candidate_id: str
    receptor_id: str
    receptor_name: str
    category: str
    distance_km: float
    estimated_arrival_hours: float | None = None
    impact_severity: str
    vulnerability_score: float
    priority_action: str | None = None

    model_config = {"from_attributes": True}


class CandidateImpactAssessmentOut(BaseModel):
    """Composite environmental vulnerability assessment for a candidate slick."""

    candidate_id: str
    max_vulnerability_score: float
    highest_severity: str
    proximate_receptors_count: int
    impacts: list[CandidateEnvironmentalImpactOut]
    overall_mitigation_summary: str

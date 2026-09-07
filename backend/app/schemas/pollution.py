"""Schemas for pollution events, zones, alerts and detection."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RiskContributionOut(BaseModel):
    """One factor's contribution to a risk score."""

    factor: str
    points: float
    max_points: float
    detail: str
    evidence_level: str


class RiskAssessmentOut(BaseModel):
    """A full, explainable risk assessment."""

    assessment_id: str
    score: float = Field(ge=0, le=100)
    severity: str
    engine_version: str
    contributions: list[RiskContributionOut]
    missing_factors: list[str] = Field(
        default_factory=list,
        description=(
            "Factors that could not be evaluated. The score is renormalised "
            "over the remaining factors, so this is a partial assessment "
            "rather than a confidently low one."
        ),
    )
    narrative: str | None = None
    evidence_level: str


class ObservationOut(BaseModel):
    """The satellite measurement behind an event. All values are OBSERVED."""

    observation_id: str
    collection: str
    platform: str
    scene_id: str | None = None
    acquired_at: datetime
    polarisation: str | None = None
    orbit_pass: str | None = None
    scale_m: int | None = None
    mean_db: float | None = None
    p10_db: float | None = None
    p90_db: float | None = None
    stddev_db: float | None = None
    evidence_level: str


class GeographicContextOut(BaseModel):
    """Coarse geographic context for a region."""

    distance_to_coast_km: float | None = None
    nearest_protected_area: str | None = None
    distance_to_protected_area_km: float | None = None


class PollutionEventOut(BaseModel):
    """A detector's claim about a region, with its provenance."""

    model_config = ConfigDict(extra="allow")

    event_id: str
    region_code: str | None = None
    region_name: str | None = None
    parent_region: str | None = None

    signature: str = Field(
        description=(
            "What the sensing modality supports as a claim, e.g. "
            "'oil_like_signature'. Deliberately not a pollutant identification."
        )
    )
    detection_method: str
    evidence_level: str
    confidence: float = Field(ge=0, le=1)
    confidence_is_calibrated: bool = Field(
        default=False,
        description="False means confidence is a score, not a probability.",
    )

    latitude: float
    longitude: float
    bbox: list[float] | None = None

    estimated_area_km2: float | None = None
    area_method: str | None = None
    risk_score: float | None = None
    severity: str | None = None

    detected_at: datetime
    model_version: str | None = None
    caveats: list[str] = Field(default_factory=list)
    is_simulated: bool = False


class PollutionEventDetailOut(PollutionEventOut):
    """An event plus its risk breakdown, source measurement and geography."""

    risk_assessment: RiskAssessmentOut | None = None
    observation: ObservationOut | None = None
    geographic_context: GeographicContextOut | None = None


class ZoneOut(BaseModel):
    """Current state of one monitored cell, for the map layer."""

    region_code: str
    region_name: str
    parent_region: str | None = None
    latitude: float
    longitude: float
    bbox: list[float]

    last_observed_at: datetime
    mean_backscatter_db: float | None = None
    platform: str
    observation_evidence_level: str

    signature: str | None = Field(
        default=None,
        description="Null means the cell was observed and nothing was detected.",
    )
    confidence: float | None = None
    risk_score: float | None = None
    severity: str | None = None
    event_id: str | None = None
    is_simulated: bool = False


class AlertOut(BaseModel):
    """An event surfaced as an operator alert."""

    event_id: str
    severity: str
    risk_score: float | None = None
    signature: str
    region_name: str
    parent_region: str | None = None
    confidence: float
    detected_at: datetime
    message: str
    is_simulated: bool = False
    caveats: list[str] = Field(default_factory=list)


class DetectionOut(BaseModel):
    """One detection from the image-upload endpoint."""

    signature: str
    class_name: str | None = None
    confidence: float
    confidence_is_calibrated: bool
    method: str
    model_version: str
    evidence_level: str
    bbox: list[float] | None = None
    geo_bbox: list[float] | None = None
    latitude: float | None = None
    longitude: float | None = None
    area_pixels: int | None = None
    caveats: list[str] = Field(default_factory=list)


class DetectResponse(BaseModel):
    """Response for ``POST /api/v1/detect``."""

    request_id: str
    detector: str
    model_version: str
    detection_count: int
    latency_ms: float
    detections: list[DetectionOut]
    notes: list[str] = Field(default_factory=list)


class IngestionSummaryOut(BaseModel):
    """Result of an ingestion run."""

    provider: str
    cells_requested: int
    observations_stored: int
    events_created: int
    negatives_recorded: int = Field(
        description="Cells observed and explicitly found unremarkable."
    )
    contains_simulated_data: bool
    errors: list[str] = Field(default_factory=list)

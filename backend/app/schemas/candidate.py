"""Pydantic schemas for SAR oil slick candidates and analyst review workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class SARCandidateOut(BaseModel):
    """A single SAR dark-formation candidate with ERA5 environmental context.

    Blinded analyst-facing view: research ground truth codes (ow/oc/nw/nc) and
    cluster labels are omitted to prevent reviewer bias.
    """

    candidate_id: str
    image_name: str
    component_id: int | None = None
    latitude: float
    longitude: float
    is_coastal: bool
    acquisition_timestamp: datetime
    detector_name: str
    model_version: str
    raw_confidence: float
    confidence_is_calibrated: bool
    wind_speed_ms: float | None = None
    wind_direction_deg: float | None = None
    era5_source: str
    grid_latitude: float | None = None
    grid_longitude: float | None = None
    temporal_offset_minutes: float | None = None
    grid_distance_km: float | None = None
    quality_status: str
    environmental_warnings: list[str] = Field(default_factory=list)
    screening_status: str
    retained_for_analyst_review: bool
    review_status: str
    latest_review_decision: str | None = None
    latest_reviewed_at: datetime | None = None
    latest_reviewer_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="wrap")
    @classmethod
    def mask_source_identifiers(cls, v: Any, handler: Any) -> Any:
        """Ensure neutral image identifiers are served to analysts."""
        res = handler(v)
        if hasattr(v, "neutral_image_id") and getattr(v, "neutral_image_id"):
            res.image_name = getattr(v, "neutral_image_id")
        elif isinstance(v, dict) and v.get("neutral_image_id"):
            res.image_name = v["neutral_image_id"]
        return res


class SARCandidateReviewOut(BaseModel):
    """An application-enforced append-only audit entry for an analyst review action."""

    review_id: str
    previous_status: str
    decision: str
    reviewer_id: str
    reviewed_at: datetime
    model_version: str
    notes: str | None = None
    evidence_references: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SARCandidateDetailOut(SARCandidateOut):
    """Detailed view including physical interpretation and review history."""

    interpretation: str
    reviews: list[SARCandidateReviewOut] = Field(default_factory=list)
    optical_evidence: list[SARCandidateOpticalEvidenceOut] = Field(default_factory=list)


class CandidateReviewCreateIn(BaseModel):
    """Analyst review submission payload."""

    decision: str = Field(
        ...,
        description=(
            "Action decision: 'potential_oil_slick', 'rejected_lookalike', "
            "'inconclusive', or 'requires_additional_evidence'"
        ),
    )
    reviewer_id: str = Field(
        default="analyst_local",
        description="Analyst identity or username (local-development mode defaults to 'analyst_local')",
    )
    notes: str | None = Field(
        default=None,
        description="Optional analyst notes and physical justification",
    )
    evidence_references: dict[str, Any] | None = Field(
        default=None,
        description="References to collateral evidence (e.g. Sentinel-2 NDCI, AIS tracks)",
    )


class SARCandidateSummaryOut(BaseModel):
    """Summary counts for dashboard KPI cards with reconciled screening semantics."""

    total_candidates: int = Field(
        ...,
        description="Total evaluated Sentinel-1 SAR samples (alias for total_evaluated_samples)",
    )
    total_monitored_samples: int = Field(
        ...,
        description="Total evaluated Sentinel-1 SAR samples across the monitoring window",
    )
    total_evaluated_samples: int = Field(
        ...,
        description="Total evaluated Sentinel-1 SAR samples (historical research evaluation benchmark)",
    )
    eligible_candidates: int = Field(
        ...,
        description="Candidate formations with p_oil >= 0.50 eligible for analyst triage",
    )
    standard_review_candidates: int = Field(
        ...,
        description="Candidates in diagnostic wind regime (wind in [3.0, 12.0] m/s)",
    )
    standard_wind_review: int = Field(
        ...,
        description="Alias for standard_review_candidates (wind in [3.0, 12.0] m/s)",
    )
    low_wind_ambiguity_candidates: int = Field(
        ...,
        description="Candidates in low-wind ambiguity regime (wind < 3.0 m/s)",
    )
    low_wind_ambiguity: int = Field(
        ...,
        description="Alias for low_wind_ambiguity_candidates (wind < 3.0 m/s)",
    )
    high_wind_ambiguity_candidates: int = Field(
        default=0,
        description="Candidates in high-wind dispersion regime (wind > 12.0 m/s)",
    )
    high_wind_ambiguity: int = Field(
        default=0,
        description="Alias for high_wind_ambiguity_candidates (wind > 12.0 m/s)",
    )
    wind_unavailable_candidates: int = Field(
        default=1,
        description="Eligible candidates with missing or unverified ERA5 wind data",
    )
    wind_unavailable: int = Field(
        default=1,
        description="Alias for wind_unavailable_candidates",
    )
    no_candidate_detected: int = Field(
        ...,
        description="Evaluated background samples where p_oil < 0.50 (non-detections)",
    )
    background_non_detections: int = Field(
        ...,
        description="Alias for no_candidate_detected (p_oil < 0.50)",
    )
    awaiting_analyst_review: int = Field(
        ...,
        description="Eligible candidate formations currently pending an analyst review decision",
    )
    reviewed_candidates: int = Field(
        ...,
        description="Candidates with at least one recorded audit review decision",
    )
    decisions: dict[str, int] = Field(default_factory=dict)


class CandidateMapPointOut(BaseModel):
    """Lightweight point representation for the GIS map."""

    candidate_id: str
    image_name: str
    latitude: float
    longitude: float
    screening_status: str
    review_status: str
    raw_confidence: float
    wind_speed_ms: float | None = None
    is_coastal: bool
    acquisition_timestamp: str
    map_state: str
    color: str

class OpticalSceneOut(BaseModel):
    """A discovered Sentinel-2 Level-2A scene matching candidate coordinates."""

    scene_id: str
    platform: str
    acquisition_time: str
    temporal_delta_hours: float
    temporal_delta_days: float
    temporal_window: str  # primary_3d | secondary_10d
    cloud_cover_pct: float
    cloud_category: str  # clean | moderate | contaminated | covered
    quality_grade: str
    tile_id: str = ""
    available_bands: list[str] = Field(default_factory=list)
    has_scl: bool = True
    is_best_match: bool = False


class SARCandidateOpticalEvidenceOut(BaseModel):
    """A processed Sentinel-2 optical evidence record for a candidate."""

    id: int
    candidate_id: str
    scene_id: str
    platform: str
    acquisition_timestamp: datetime
    temporal_offset_hours: float
    temporal_window: str
    scene_cloud_cover_pct: float
    tile_id: str | None = None
    local_water_fraction: float
    local_cloud_fraction: float
    local_shadow_fraction: float
    local_valid_pixel_fraction: float
    mean_ndci: float | None = None
    p90_ndci: float | None = None
    mean_ndti: float | None = None
    mean_swir_ratio: float | None = None
    optical_quality_flag: str
    has_rgb_image: bool = True
    has_false_color_image: bool = True
    has_scl_mask: bool = True
    has_ndci_map: bool = True
    processing_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProcessOpticalEvidenceIn(BaseModel):
    """Payload for triggering optical evidence extraction on a candidate."""

    scene_id: str | None = Field(
        None,
        description="Target Sentinel-2 scene ID. If omitted, best matching scene is used."
    )
    chip_size: int = Field(512, ge=128, le=1024)



class EvidenceItemOut(BaseModel):
    """A single sensor or environmental observation in the multi-sensor evidence chain."""

    modality: str
    sensor: str
    acquisition_time_utc: str
    temporal_offset_hours: float | None = None
    signature: str
    confidence: float
    consistency: str
    description: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class MultiSensorAssessmentOut(BaseModel):
    """Triangulated multi-sensor assessment and objective concordance score."""

    candidate_id: str
    latitude: float
    longitude: float
    sar_screening_status: str
    wind_classification: str
    optical_verification_status: str
    concordance_score: float
    concordance_level: str
    triangulation_summary: str
    recommended_action: str
    evidence_items: list[EvidenceItemOut]
    generated_at: str

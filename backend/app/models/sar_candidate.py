"""SQLAlchemy models for experimental SAR oil-slick candidates and analyst review history.

Connects Sentinel-1 SAR texture detections, ERA5 atmospheric reanalysis context,
and human analyst decision history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow


class SARCandidate(Base, TimestampMixin):
    """An experimental SAR dark-formation candidate evaluated with ERA5 wind context.

    Preserves raw model outputs without modification, along with spatiotemporally
    collocated ERA5 environmental reanalysis and the three-state screening status.
    """

    __tablename__ = "sar_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # -- Provenance & Source Metadata -------------------------------------
    internal_sample_id: Mapped[str | None] = mapped_column(String(64), index=True)
    neutral_image_id: Mapped[str | None] = mapped_column(String(128))
    image_name: Mapped[str] = mapped_column(String(128), index=True)
    safe_scene: Mapped[str | None] = mapped_column(String(256), index=True)
    subset: Mapped[str] = mapped_column(String(16), index=True)  # ow, oc, nw, nc (internal research ground truth)
    cluster: Mapped[str] = mapped_column(String(32), index=True)  # oil, nw_c01.. (internal research cluster)
    component_id: Mapped[int | None] = mapped_column(Integer, index=True)
    split: Mapped[str] = mapped_column(String(64), index=True)  # locked_test, dev, val, p12_test

    # -- Geographic Coordinates (WGS84) -----------------------------------
    latitude: Mapped[float] = mapped_column(Float, index=True)
    longitude: Mapped[float] = mapped_column(Float, index=True)
    is_coastal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    acquisition_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # -- Model Information & Confidence ------------------------------------
    detector_name: Mapped[str] = mapped_column(String(64), default="sar-oil-slick-v2.2")
    model_version: Mapped[str] = mapped_column(String(64), default="2.2.0-experimental", index=True)
    raw_confidence: Mapped[float] = mapped_column(Float)  # Raw p_oil from CNN
    confidence_is_calibrated: Mapped[bool] = mapped_column(Boolean, default=False)

    # -- ERA5 Atmospheric Wind Reanalysis Context --------------------------
    wind_speed_ms: Mapped[float | None] = mapped_column(Float)
    wind_direction_deg: Mapped[float | None] = mapped_column(Float)
    era5_source: Mapped[str] = mapped_column(
        String(128), default="ECMWF ERA5 Reanalysis Archive"
    )
    grid_latitude: Mapped[float | None] = mapped_column(Float)
    grid_longitude: Mapped[float | None] = mapped_column(Float)
    temporal_offset_minutes: Mapped[float | None] = mapped_column(Float)
    grid_distance_km: Mapped[float | None] = mapped_column(Float)
    quality_status: Mapped[str] = mapped_column(
        String(48), default="reanalysis_available"
    )

    # -- Three-State Screening & Caveats -----------------------------------
    environmental_warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    screening_status: Mapped[str] = mapped_column(String(48), index=True)
    retained_for_analyst_review: Mapped[bool] = mapped_column(
        Boolean, default=True, index=True
    )

    # -- Review Lifecycle Status -------------------------------------------
    # awaiting_review | potential_oil_slick | rejected_lookalike | inconclusive | requires_additional_evidence
    review_status: Mapped[str] = mapped_column(
        String(48), default="awaiting_review", index=True
    )
    latest_review_decision: Mapped[str | None] = mapped_column(String(48))
    latest_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_reviewer_id: Mapped[str | None] = mapped_column(String(64))

    # Audit relationship: ON DELETE RESTRICT prevents cascade deletion of audit history
    reviews: Mapped[list[SARCandidateReview]] = relationship(
        back_populates="candidate",
        passive_deletes=True,
        order_by="desc(SARCandidateReview.reviewed_at)",
    )
    optical_evidence: Mapped[list[SARCandidateOpticalEvidence]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        order_by="desc(SARCandidateOpticalEvidence.acquisition_timestamp)",
    )
    vessel_associations: Mapped[list[Any]] = relationship(
        "CandidateVesselAssociation",
        back_populates="candidate",
        cascade="all, delete-orphan",
    )
    environmental_impacts: Mapped[list[Any]] = relationship(
        "CandidateEnvironmentalImpact",
        back_populates="candidate",
        cascade="all, delete-orphan",
        order_by="CandidateEnvironmentalImpact.distance_km",
    )

    __table_args__ = (
        Index("ix_sar_cand_loc", "latitude", "longitude"),
        Index("ix_sar_cand_screening_review", "screening_status", "review_status"),
    )


class SARCandidateReview(Base):
    """An application-enforced append-only audit record of an analyst's decision on a SAR candidate."""

    __tablename__ = "sar_candidate_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("sar_candidates.id", ondelete="RESTRICT"), index=True
    )
    candidate: Mapped[SARCandidate] = relationship(back_populates="reviews")

    previous_status: Mapped[str] = mapped_column(String(48))
    decision: Mapped[str] = mapped_column(String(48), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(64), index=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    model_version: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    evidence_references: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_cand_rev_time", "candidate_id", "reviewed_at"),
    )

class SARCandidateOpticalEvidence(Base, TimestampMixin):
    """Sentinel-2 Level-2A optical evidence associated with a SAR dark-formation candidate.

    Captures Bottom-of-Atmosphere (BOA) surface reflectance, Scene Classification Layer
    (SCL) cloud/water/shadow fractions, and environmental chlorophyll/turbidity indicators.
    """

    __tablename__ = "sar_candidate_optical_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("sar_candidates.id", ondelete="CASCADE"), index=True
    )
    candidate: Mapped[SARCandidate] = relationship(back_populates="optical_evidence")

    # STAC Granule Identification
    scene_id: Mapped[str] = mapped_column(String(128), index=True)
    platform: Mapped[str] = mapped_column(String(32), default="sentinel-2")
    acquisition_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    temporal_offset_hours: Mapped[float] = mapped_column(Float)
    temporal_window: Mapped[str] = mapped_column(String(32), default="primary_3d")  # primary_3d | secondary_10d
    scene_cloud_cover_pct: Mapped[float] = mapped_column(Float, default=0.0)
    tile_id: Mapped[str | None] = mapped_column(String(32))

    # Local Chip Quality Screening Metrics
    local_water_fraction: Mapped[float] = mapped_column(Float, default=0.0)
    local_cloud_fraction: Mapped[float] = mapped_column(Float, default=0.0)
    local_shadow_fraction: Mapped[float] = mapped_column(Float, default=0.0)
    local_valid_pixel_fraction: Mapped[float] = mapped_column(Float, default=1.0)
    mean_ndci: Mapped[float | None] = mapped_column(Float)
    p90_ndci: Mapped[float | None] = mapped_column(Float)
    mean_ndti: Mapped[float | None] = mapped_column(Float)
    mean_swir_ratio: Mapped[float | None] = mapped_column(Float)
    optical_quality_flag: Mapped[str] = mapped_column(String(48), index=True)

    # Local Evidence Product Paths
    rgb_thumbnail_path: Mapped[str | None] = mapped_column(String(256))
    false_color_path: Mapped[str | None] = mapped_column(String(256))
    scl_mask_path: Mapped[str | None] = mapped_column(String(256))
    ndci_map_path: Mapped[str | None] = mapped_column(String(256))
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Processing State
    processing_status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_cand_opt_time", "candidate_id", "acquisition_timestamp"),
        Index("ix_cand_opt_scene", "candidate_id", "scene_id"),
    )


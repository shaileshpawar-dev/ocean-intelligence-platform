"""Core domain tables: regions, satellite observations and pollution events.

The split between :class:`SatelliteObservation` (what the sensor measured) and
:class:`PollutionEvent` (what a detector concluded) is deliberate and load
bearing. The original system collapsed the two, which is how brightness
rankings ended up being served as pollution classifications.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    DetectionMethod,
    EvidenceLevel,
    PollutionSignature,
)


class Region(Base, TimestampMixin):
    """A named monitoring area, optionally subdivided into grid cells.

    Regions are configuration, not measurements: they define *where* the
    platform looks. Bounds are stored as a WGS84 bounding box.
    """

    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    parent_code: Mapped[str | None] = mapped_column(String(64), index=True)

    min_lon: Mapped[float] = mapped_column(Float)
    min_lat: Mapped[float] = mapped_column(Float)
    max_lon: Mapped[float] = mapped_column(Float)
    max_lat: Mapped[float] = mapped_column(Float)

    centroid_lat: Mapped[float] = mapped_column(Float)
    centroid_lon: Mapped[float] = mapped_column(Float)

    # Distance from the cell centroid to the nearest coastline, in km.
    # Populated by the geographic provider; feeds the risk engine.
    distance_to_coast_km: Mapped[float | None] = mapped_column(Float)
    nearest_protected_area: Mapped[str | None] = mapped_column(String(256))
    distance_to_protected_area_km: Mapped[float | None] = mapped_column(Float)

    observations: Mapped[list[SatelliteObservation]] = relationship(
        back_populates="region", cascade="all, delete-orphan"
    )
    events: Mapped[list[PollutionEvent]] = relationship(
        back_populates="region", cascade="all, delete-orphan"
    )


class SatelliteObservation(Base, TimestampMixin):
    """A measurement taken from satellite imagery over one region cell.

    Every column here is OBSERVED: it is a statistic computed by the Earth
    Engine reducer over real pixels, or metadata attached to the scene. No
    interpretation lives in this table.
    """

    __tablename__ = "satellite_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="CASCADE"), index=True
    )
    region: Mapped[Region] = relationship(back_populates="observations")

    # -- Provenance --------------------------------------------------------
    collection: Mapped[str] = mapped_column(String(128))  # e.g. COPERNICUS/S1_GRD
    platform: Mapped[str] = mapped_column(String(64))  # e.g. Sentinel-1
    scene_id: Mapped[str | None] = mapped_column(String(256))
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    instrument_mode: Mapped[str | None] = mapped_column(String(32))
    polarisation: Mapped[str | None] = mapped_column(String(16))
    orbit_pass: Mapped[str | None] = mapped_column(String(16))
    scale_m: Mapped[int | None] = mapped_column(Integer)
    scene_count: Mapped[int | None] = mapped_column(Integer)

    # -- Measured backscatter statistics (dB) ------------------------------
    mean_db: Mapped[float | None] = mapped_column(Float)
    p10_db: Mapped[float | None] = mapped_column(Float)
    p90_db: Mapped[float | None] = mapped_column(Float)
    stddev_db: Mapped[float | None] = mapped_column(Float)
    min_db: Mapped[float | None] = mapped_column(Float)
    max_db: Mapped[float | None] = mapped_column(Float)

    # -- Honesty marker ----------------------------------------------------
    evidence_level: Mapped[str] = mapped_column(
        String(16), default=EvidenceLevel.OBSERVED, index=True
    )

    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (Index("ix_obs_region_acquired", "region_id", "acquired_at"),)


class PollutionEvent(Base, TimestampMixin):
    """A detector's conclusion about a region at a point in time.

    A pollution event is a *claim*, not a fact. ``signature`` records what
    kind of claim the sensing modality supports, ``detection_method`` records
    how it was produced, and ``evidence_level`` records how strongly it may
    be stated. ``confidence`` is a detector score, never a fabricated number.
    """

    __tablename__ = "pollution_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="CASCADE"), index=True
    )
    region: Mapped[Region] = relationship(back_populates="events")

    observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("satellite_observations.id", ondelete="SET NULL"), index=True
    )
    observation: Mapped[SatelliteObservation | None] = relationship()

    # -- The claim ---------------------------------------------------------
    signature: Mapped[str] = mapped_column(
        String(48), default=PollutionSignature.SURFACE_ANOMALY, index=True
    )
    detection_method: Mapped[str] = mapped_column(
        String(48), default=DetectionMethod.SAR_DARK_FORMATION
    )
    evidence_level: Mapped[str] = mapped_column(
        String(16), default=EvidenceLevel.DETECTED, index=True
    )
    confidence: Mapped[float] = mapped_column(Float)

    # -- Where -------------------------------------------------------------
    latitude: Mapped[float] = mapped_column(Float, index=True)
    longitude: Mapped[float] = mapped_column(Float, index=True)
    bbox: Mapped[list | None] = mapped_column(JSON)  # [minlon, minlat, maxlon, maxlat]

    # -- Extent ------------------------------------------------------------
    area_pixels: Mapped[int | None] = mapped_column(Integer)
    estimated_area_km2: Mapped[float | None] = mapped_column(Float)
    area_method: Mapped[str | None] = mapped_column(String(64))

    # -- Assessment (filled by the deterministic risk engine) --------------
    risk_score: Mapped[float | None] = mapped_column(Float, index=True)
    severity: Mapped[str | None] = mapped_column(String(16), index=True)

    # -- Provenance --------------------------------------------------------
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    model_version: Mapped[str | None] = mapped_column(String(64), index=True)
    source_image: Mapped[str | None] = mapped_column(Text)

    # Human-readable caveats attached at detection time, e.g. the SAR
    # look-alike warning. Surfaced verbatim in the API and the report.
    caveats: Mapped[list | None] = mapped_column(JSON)
    extra: Mapped[dict | None] = mapped_column(JSON)

    risk_assessments: Mapped[list[RiskAssessment]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_event_region_detected", "region_id", "detected_at"),
        Index("ix_event_severity_detected", "severity", "detected_at"),
    )


class RiskAssessment(Base, TimestampMixin):
    """Output of the deterministic risk engine for one event.

    ``contributions`` stores the per-factor point breakdown so the score is
    fully reconstructible and explainable without an LLM.
    """

    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    event_id: Mapped[int] = mapped_column(
        ForeignKey("pollution_events.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[PollutionEvent] = relationship(back_populates="risk_assessments")

    score: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    engine_version: Mapped[str] = mapped_column(String(32))

    # [{"factor": "...", "points": 25.0, "detail": "...", "evidence_level": "..."}]
    contributions: Mapped[list] = mapped_column(JSON)
    # Factors that could not be evaluated (missing data), so the consumer
    # knows the score is partial rather than confidently low.
    missing_factors: Mapped[list | None] = mapped_column(JSON)

    evidence_level: Mapped[str] = mapped_column(
        String(16), default=EvidenceLevel.INFERRED
    )
    narrative: Mapped[str | None] = mapped_column(Text)


class ZoneHistory(Base):
    """Daily aggregate of activity per region, for temporal analytics.

    Rows are derived from real events and observations only. The original
    ``seed_history()`` populated 30 days of noise from a single snapshot;
    this table is populated by :mod:`app.services.analytics_service` from
    persisted data, and demo-mode rows are tagged ``SIMULATED``.
    """

    __tablename__ = "zone_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="CASCADE"), index=True
    )
    bucket_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    event_count: Mapped[int] = mapped_column(Integer, default=0)
    mean_confidence: Mapped[float | None] = mapped_column(Float)
    mean_risk_score: Mapped[float | None] = mapped_column(Float)
    max_risk_score: Mapped[float | None] = mapped_column(Float)
    total_area_km2: Mapped[float | None] = mapped_column(Float)
    mean_backscatter_db: Mapped[float | None] = mapped_column(Float)

    evidence_level: Mapped[str] = mapped_column(
        String(16), default=EvidenceLevel.OBSERVED
    )

    __table_args__ = (
        Index("ix_hist_region_date", "region_id", "bucket_date", unique=True),
    )

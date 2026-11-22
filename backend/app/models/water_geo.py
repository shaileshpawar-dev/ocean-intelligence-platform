"""Phase 2 water models: geometry, geography, standards, classifications, imagery.

Kept apart from ``water.py`` so the core observation model stays readable.
Geometry is stored as GeoJSON text with an indexed bounding box, which keeps
SQLite working locally; the PostGIS migration (docs/data-model.md) swaps the
text column for a geography column without changing any caller.
"""

from __future__ import annotations

from datetime import datetime

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class WaterBodyGeometry(Base, TimestampMixin):
    """Mapped geometry of a water body, with where it came from.

    One row per water body per source: sources are never silently mixed, and
    every row names its source, the source's feature ids, the licence and when
    it was retrieved.
    """

    __tablename__ = "water_body_geometries"
    __table_args__ = (
        UniqueConstraint("water_body_id", "source", name="uq_geometry_body_source"),
        Index("ix_geometry_bbox", "min_lat", "max_lat", "min_lon", "max_lon"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    water_body_id: Mapped[int] = mapped_column(ForeignKey("water_bodies.id"), index=True)
    geometry_type: Mapped[str] = mapped_column(String(24))
    """``LineString``, ``MultiLineString``, ``Polygon`` or ``MultiPolygon``."""

    geojson: Mapped[str] = mapped_column(Text)
    """Simplified geometry as served to the map."""

    min_lat: Mapped[float] = mapped_column(Float)
    min_lon: Mapped[float] = mapped_column(Float)
    max_lat: Mapped[float] = mapped_column(Float)
    max_lon: Mapped[float] = mapped_column(Float)

    source: Mapped[str] = mapped_column(String(64))
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    source_licence: Mapped[str | None] = mapped_column(String(120), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    confidence: Mapped[str] = mapped_column(String(16))
    """``high`` (name and position agree) or ``medium`` (name agrees, some
    stations sit away from the feature). Nothing weaker is stored."""

    match_method: Mapped[str] = mapped_column(String(64))
    match_notes: Mapped[list] = mapped_column(JSON, default=list)
    feature_count: Mapped[int] = mapped_column(Integer, default=1)
    clipped: Mapped[bool] = mapped_column(Boolean, default=False)
    """True when a long river was clipped to the reach around its stations."""


class AdminBoundary(Base, TimestampMixin):
    """A state or district boundary from an openly licensed source."""

    __tablename__ = "admin_boundaries"
    __table_args__ = (
        UniqueConstraint("level", "source", "source_id", name="uq_boundary_source"),
        Index("ix_boundary_bbox", "min_lat", "max_lat", "min_lon", "max_lon"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(16), index=True)
    """``state`` or ``district``."""

    name: Mapped[str] = mapped_column(String(160), index=True)
    normalized_name: Mapped[str] = mapped_column(String(160), index=True)
    state_id: Mapped[int | None] = mapped_column(ForeignKey("states.id"), nullable=True)
    district_id: Mapped[int | None] = mapped_column(
        ForeignKey("districts.id"), nullable=True
    )
    parent_name: Mapped[str | None] = mapped_column(String(160), nullable=True)

    geojson: Mapped[str] = mapped_column(Text)
    min_lat: Mapped[float] = mapped_column(Float)
    min_lon: Mapped[float] = mapped_column(Float)
    max_lat: Mapped[float] = mapped_column(Float)
    max_lon: Mapped[float] = mapped_column(Float)
    centroid_lat: Mapped[float] = mapped_column(Float)
    centroid_lon: Mapped[float] = mapped_column(Float)

    source: Mapped[str] = mapped_column(String(120))
    source_id: Mapped[str] = mapped_column(String(120))
    licence: Mapped[str] = mapped_column(String(160))
    vintage: Mapped[str | None] = mapped_column(String(32), nullable=True)


class City(Base, TimestampMixin):
    """A city, defined as the districts that make it up.

    The monitoring data is keyed to districts, so a city is an explicit,
    listed set of districts -- Mumbai is Mumbai City plus Mumbai Suburban --
    rather than an invented boundary. Its position comes from those districts'
    published boundaries, not from averaged station coordinates.
    """

    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    state_id: Mapped[int | None] = mapped_column(ForeignKey("states.id"), nullable=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    district_ids: Mapped[list] = mapped_column(JSON, default=list)
    centroid_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    centroid_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_source: Mapped[str] = mapped_column(String(200))
    definition_note: Mapped[str] = mapped_column(Text)


class ReferenceStandard(Base, TimestampMixin):
    """A published water-quality standard, or one category within it."""

    __tablename__ = "reference_standards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(160), nullable=True)
    issuing_body: Mapped[str] = mapped_column(String(200))
    legal_basis: Mapped[str | None] = mapped_column(String(300), nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verified_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    thresholds: Mapped[list[ReferenceThreshold]] = relationship(back_populates="standard")


class ReferenceThreshold(Base, TimestampMixin):
    """One limit for one parameter within a standard."""

    __tablename__ = "reference_thresholds"
    __table_args__ = (
        UniqueConstraint("standard_id", "parameter", name="uq_threshold_standard_param"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    standard_id: Mapped[int] = mapped_column(
        ForeignKey("reference_standards.id"), index=True
    )
    parameter: Mapped[str] = mapped_column(String(64))
    threshold_type: Mapped[str] = mapped_column(String(16))
    """``minimum``, ``maximum`` or ``range``."""

    minimum: Mapped[float | None] = mapped_column(Float, nullable=True)
    maximum: Mapped[float | None] = mapped_column(Float, nullable=True)
    desirable: Mapped[float | None] = mapped_column(Float, nullable=True)
    """Advisory level stricter than the limit, where the standard gives one."""

    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    standard: Mapped[ReferenceStandard] = relationship(back_populates="thresholds")


class SourceClassification(Base, TimestampMixin):
    """An official classification of a water body or stretch by a source.

    Separate from observations on purpose: "BOD was 18 mg/L on this date" and
    "CPCB lists this stretch as priority IV" are different claims with
    different sources and dates, and the platform never manufactures the
    second from the first.
    """

    __tablename__ = "source_classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    water_body_id: Mapped[int | None] = mapped_column(
        ForeignKey("water_bodies.id"), nullable=True, index=True
    )
    river_stretch_id: Mapped[int | None] = mapped_column(
        ForeignKey("river_stretches.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(200))
    classification_type: Mapped[str] = mapped_column(String(64))
    assessment_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    river_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stretch_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    state_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    qualifying_parameter: Mapped[str | None] = mapped_column(String(64), nullable=True)
    qualifying_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_reference: Mapped[str] = mapped_column(String(500))
    match_method: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WaterImage(Base, TimestampMixin):
    """An image attached to a water body as evidence."""

    __tablename__ = "water_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    water_body_id: Mapped[int] = mapped_column(ForeignKey("water_bodies.id"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(32))
    """``SATELLITE``, ``OFFICIAL_PHOTO``, ``FIELD_PHOTO``, ``REPORT_IMAGE`` or
    ``REFERENCE``."""

    source: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sensor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    acquisition_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    full_image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    min_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    licence: Mapped[str | None] = mapped_column(String(200), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    image_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

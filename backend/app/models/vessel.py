"""SQLAlchemy models for AIS vessel tracking, trajectory interpolation, and incident association (Phase 15).

Provides vessel registries, timestamped geospatial position history (AIS pings),
and deterministic spatio-temporal association with SAR surface candidates.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
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

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.sar_candidate import SARCandidate


class Vessel(Base, TimestampMixin):
    """Commercial vessel particulars and maritime registry attributes."""

    __tablename__ = "vessels"

    mmsi: Mapped[str] = mapped_column(String(16), primary_key=True)
    imo: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    callsign: Mapped[str | None] = mapped_column(String(16), nullable=True)
    vessel_type: Mapped[str] = mapped_column(String(64), index=True)  # Tanker, Cargo, Container, Bulk Carrier, Fishing
    flag_country: Mapped[str] = mapped_column(String(64), index=True)
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    width_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    draught_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_profile: Mapped[str] = mapped_column(String(64), default="STANDARD", index=True)

    positions: Mapped[list[VesselPosition]] = relationship(
        back_populates="vessel",
        cascade="all, delete-orphan",
        order_by="VesselPosition.timestamp",
    )
    associations: Mapped[list[CandidateVesselAssociation]] = relationship(
        back_populates="vessel",
        cascade="all, delete-orphan",
    )


class VesselPosition(Base):
    """Timestamped geospatial AIS transmission / ping along a vessel trajectory."""

    __tablename__ = "vessel_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mmsi: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("vessels.mmsi", ondelete="CASCADE"),
        index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    latitude: Mapped[float] = mapped_column(Float, index=True)
    longitude: Mapped[float] = mapped_column(Float, index=True)
    speed_knots: Mapped[float] = mapped_column(Float, default=0.0)
    heading_deg: Mapped[float] = mapped_column(Float, default=0.0)
    nav_status: Mapped[str] = mapped_column(String(64), default="Under way using engine")
    destination: Mapped[str | None] = mapped_column(String(128), nullable=True)

    vessel: Mapped[Vessel] = relationship(back_populates="positions")

    __table_args__ = (
        Index("ix_vessel_pos_mmsi_time", "mmsi", "timestamp"),
        Index("ix_vessel_pos_geo", "latitude", "longitude"),
    )


class CandidateVesselAssociation(Base, TimestampMixin):
    """Spatio-temporal correlation between a SAR candidate slick and an AIS vessel track."""

    __tablename__ = "candidate_vessel_associations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sar_candidates.candidate_id", ondelete="CASCADE"),
        index=True,
    )
    mmsi: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("vessels.mmsi", ondelete="CASCADE"),
        index=True,
    )
    association_type: Mapped[str] = mapped_column(
        String(64),
        default="PROXIMATE_TRANSIT",
        index=True,
    )  # SOURCE_SUSPECT | PROXIMATE_TRANSIT | INTERSECTED_TRACK | CO_OCCURRING
    spatial_distance_km: Mapped[float] = mapped_column(Float)
    temporal_offset_minutes: Mapped[float] = mapped_column(Float)
    interpolated_lat: Mapped[float] = mapped_column(Float)
    interpolated_lon: Mapped[float] = mapped_column(Float)
    association_score: Mapped[float] = mapped_column(Float)  # 0.0 to 1.0 suspicion score
    is_primary_suspect: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    vessel: Mapped[Vessel] = relationship(back_populates="associations")
    candidate: Mapped[SARCandidate] = relationship(back_populates="vessel_associations")

    __table_args__ = (
        Index("ix_cand_vessel_assoc_cand", "candidate_id", "spatial_distance_km"),
    )

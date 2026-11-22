"""SQLAlchemy models for Marine Protected Areas, sensitive receptors, and spill impact (Phase 17)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

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

from app.models.base import Base, utcnow

if TYPE_CHECKING:
    from app.models.sar_candidate import SARCandidate


class MarineReceptor(Base):
    """An ecologically sensitive marine receptor or critical coastal infrastructure asset."""

    __tablename__ = "marine_receptors"

    receptor_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    category: Mapped[str] = mapped_column(
        String(64),
        index=True,
    )  # CORAL_REEF | MANGROVE_ECOSYSTEM | MARINE_PROTECTED_AREA | DESALINATION_INTAKE | FISHERY_ZONE
    jurisdiction: Mapped[str] = mapped_column(String(128))
    latitude: Mapped[float] = mapped_column(Float, index=True)
    longitude: Mapped[float] = mapped_column(Float, index=True)
    boundary_geojson: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    vulnerability_weight: Mapped[float] = mapped_column(Float, default=0.80)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )

    impacts: Mapped[list[CandidateEnvironmentalImpact]] = relationship(
        back_populates="receptor",
        cascade="all, delete-orphan",
    )


class CandidateEnvironmentalImpact(Base):
    """Evaluated exposure and vulnerability assessment connecting a SAR slick to a receptor."""

    __tablename__ = "candidate_environmental_impacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sar_candidates.candidate_id", ondelete="CASCADE"),
        index=True,
    )
    receptor_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marine_receptors.receptor_id", ondelete="CASCADE"),
        index=True,
    )
    distance_km: Mapped[float] = mapped_column(Float)
    estimated_arrival_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    impact_severity: Mapped[str] = mapped_column(
        String(32),
        default="LOW",
        index=True,
    )  # CRITICAL | HIGH | MODERATE | LOW
    vulnerability_score: Mapped[float] = mapped_column(Float, default=0.0)
    priority_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )

    receptor: Mapped[MarineReceptor] = relationship(back_populates="impacts")
    candidate: Mapped[SARCandidate] = relationship(back_populates="environmental_impacts")

    __table_args__ = (
        Index("ix_cand_env_impact_cand_dist", "candidate_id", "distance_km"),
    )

"""SQLAlchemy model for Lagrangian oil-spill trajectory simulations and beaching risk (Phase 16)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class DriftSimulation(Base):
    """A numerical Lagrangian particle simulation of marine oil-spill drift, weathering, and beaching."""

    __tablename__ = "drift_simulations"

    simulation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("sar_candidates.candidate_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    origin_lat: Mapped[float] = mapped_column(Float)
    origin_lon: Mapped[float] = mapped_column(Float)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_hours: Mapped[int] = mapped_column(Integer, default=48)
    oil_type: Mapped[str] = mapped_column(String(64), default="Medium Crude")
    spill_volume_m3: Mapped[float] = mapped_column(Float, default=50.0)
    wind_speed_ms: Mapped[float] = mapped_column(Float)
    wind_direction_deg: Mapped[float] = mapped_column(Float)
    current_speed_ms: Mapped[float] = mapped_column(Float, default=0.20)
    current_direction_deg: Mapped[float] = mapped_column(Float, default=90.0)
    evaporated_pct: Mapped[float] = mapped_column(Float, default=0.0)
    floating_pct: Mapped[float] = mapped_column(Float, default=100.0)
    beached_pct: Mapped[float] = mapped_column(Float, default=0.0)
    dispersed_pct: Mapped[float] = mapped_column(Float, default=0.0)
    beaching_risk_level: Mapped[str] = mapped_column(String(32), default="LOW")
    time_to_shore_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    trajectory_geojson: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    mass_balance_timeline: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )

    __table_args__ = (
        Index("ix_drift_sim_candidate_created", "candidate_id", "created_at"),
    )

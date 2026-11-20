"""Pydantic schemas for Lagrangian oil-spill drift simulations and weathering (Phase 16)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HourlyDriftSnapshotOut(BaseModel):
    """Ensemble status and mass balance breakdown at simulation hour t."""

    hour: int
    timestamp_utc: str
    centroid_lat: float
    centroid_lon: float
    spread_radius_km: float
    evaporated_pct: float
    floating_pct: float
    beached_pct: float
    dispersed_pct: float
    active_particles: int
    beached_particles: int
    dispersed_particles: int


class DriftSimulationRequestIn(BaseModel):
    """Parameters for running a Lagrangian oil drift simulation."""

    candidate_id: str | None = Field(
        None,
        description="Optional candidate ID to inherit origin coordinates and collocated ERA5 wind",
    )
    origin_lat: float | None = Field(None, ge=-90.0, le=90.0)
    origin_lon: float | None = Field(None, ge=-180.0, le=180.0)
    duration_hours: int = Field(default=48, ge=6, le=168)
    oil_type: str = Field(default="Medium Crude")  # Light Crude | Medium Crude | Heavy Fuel Oil | Diesel / Gasoil
    spill_volume_m3: float = Field(default=50.0, ge=1.0, le=50000.0)
    wind_speed_ms: float | None = Field(None, ge=0.0, le=50.0)
    wind_direction_deg: float | None = Field(None, ge=0.0, le=360.0)
    current_speed_ms: float = Field(default=0.20, ge=0.0, le=5.0)
    current_direction_deg: float = Field(default=90.0, ge=0.0, le=360.0)


class DriftSimulationOut(BaseModel):
    """Summary and complete trajectory output of Lagrangian drift simulation."""

    simulation_id: str
    candidate_id: str | None = None
    origin_lat: float
    origin_lon: float
    start_time: str
    duration_hours: int
    oil_type: str
    spill_volume_m3: float
    wind_speed_ms: float
    wind_direction_deg: float
    current_speed_ms: float
    current_direction_deg: float
    final_evaporated_pct: float
    final_floating_pct: float
    final_beached_pct: float
    final_dispersed_pct: float
    beaching_risk_level: str
    time_to_shore_hours: float | None = None
    mass_balance_timeline: list[HourlyDriftSnapshotOut] = Field(default_factory=list)
    geojson: dict[str, Any] = Field(default_factory=dict)

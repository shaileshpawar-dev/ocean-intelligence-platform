"""Service layer for Lagrangian oil-spill drift simulations and persistence (Phase 16)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.drift_simulation import DriftSimulation
from app.models.sar_candidate import SARCandidate
from app.schemas.drift import (
    DriftSimulationOut,
    DriftSimulationRequestIn,
    HourlyDriftSnapshotOut,
)
from app.vision.lagrangian_drift import LagrangianDriftEngine

logger = get_logger(__name__)


def run_drift_simulation(
    db: Session,
    payload: DriftSimulationRequestIn,
) -> DriftSimulationOut:
    """Execute numerical Lagrangian particle simulation and persist outcome to database."""
    origin_lat = payload.origin_lat
    origin_lon = payload.origin_lon
    wind_spd = payload.wind_speed_ms
    wind_dir = payload.wind_direction_deg
    start_time = datetime.now(UTC)
    is_coastal = False

    # Inherit candidate environmental context if candidate_id provided
    if payload.candidate_id:
        cand = db.query(SARCandidate).filter_by(candidate_id=payload.candidate_id).first()
        if cand:
            if origin_lat is None:
                origin_lat = cand.latitude
            if origin_lon is None:
                origin_lon = cand.longitude
            if wind_spd is None:
                wind_spd = cand.wind_speed_ms if cand.wind_speed_ms is not None else 6.0
            if wind_dir is None:
                wind_dir = cand.wind_direction_deg if cand.wind_direction_deg is not None else 225.0
            start_time = cand.acquisition_timestamp
            is_coastal = cand.is_coastal

    if origin_lat is None or origin_lon is None:
        origin_lat = 20.0
        origin_lon = 65.0
    if wind_spd is None:
        wind_spd = 6.0
    if wind_dir is None:
        wind_dir = 225.0

    engine = LagrangianDriftEngine()
    result = engine.simulate(
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        start_time=start_time,
        duration_hours=payload.duration_hours,
        num_particles=150,
        oil_type=payload.oil_type,
        spill_volume_m3=payload.spill_volume_m3,
        wind_speed_ms=wind_spd,
        wind_direction_deg=wind_dir,
        current_speed_ms=payload.current_speed_ms,
        current_direction_deg=payload.current_direction_deg,
        candidate_id=payload.candidate_id,
        is_coastal=is_coastal,
    )

    # Persist simulation to database
    sim_row = DriftSimulation(
        simulation_id=result.simulation_id,
        candidate_id=payload.candidate_id,
        origin_lat=result.origin_lat,
        origin_lon=result.origin_lon,
        start_time=result.start_time,
        duration_hours=result.duration_hours,
        oil_type=result.oil_type,
        spill_volume_m3=result.spill_volume_m3,
        wind_speed_ms=result.wind_speed_ms,
        wind_direction_deg=result.wind_direction_deg,
        current_speed_ms=result.current_speed_ms,
        current_direction_deg=result.current_direction_deg,
        evaporated_pct=result.final_evaporated_pct,
        floating_pct=result.final_floating_pct,
        beached_pct=result.final_beached_pct,
        dispersed_pct=result.final_dispersed_pct,
        beaching_risk_level=result.beaching_risk_level,
        time_to_shore_hours=result.time_to_shore_hours,
        trajectory_geojson=result.geojson,
        mass_balance_timeline=[s.to_dict() for s in result.mass_balance_timeline],
    )
    db.add(sim_row)
    db.commit()

    return DriftSimulationOut(
        simulation_id=result.simulation_id,
        candidate_id=result.candidate_id,
        origin_lat=result.origin_lat,
        origin_lon=result.origin_lon,
        start_time=result.start_time.isoformat(),
        duration_hours=result.duration_hours,
        oil_type=result.oil_type,
        spill_volume_m3=result.spill_volume_m3,
        wind_speed_ms=result.wind_speed_ms,
        wind_direction_deg=result.wind_direction_deg,
        current_speed_ms=result.current_speed_ms,
        current_direction_deg=result.current_direction_deg,
        final_evaporated_pct=result.final_evaporated_pct,
        final_floating_pct=result.final_floating_pct,
        final_beached_pct=result.final_beached_pct,
        final_dispersed_pct=result.final_dispersed_pct,
        beaching_risk_level=result.beaching_risk_level,
        time_to_shore_hours=result.time_to_shore_hours,
        mass_balance_timeline=[HourlyDriftSnapshotOut(**s.to_dict()) for s in result.mass_balance_timeline],
        geojson=result.geojson,
    )


def get_drift_simulation(db: Session, simulation_id: str) -> DriftSimulationOut | None:
    """Retrieve full results of an existing drift simulation."""
    row = db.get(DriftSimulation, simulation_id)
    if not row:
        return None

    timeline = (
        [HourlyDriftSnapshotOut(**s) for s in row.mass_balance_timeline]
        if row.mass_balance_timeline
        else []
    )

    return DriftSimulationOut(
        simulation_id=row.simulation_id,
        candidate_id=row.candidate_id,
        origin_lat=row.origin_lat,
        origin_lon=row.origin_lon,
        start_time=row.start_time.isoformat() if row.start_time else "",
        duration_hours=row.duration_hours,
        oil_type=row.oil_type,
        spill_volume_m3=row.spill_volume_m3,
        wind_speed_ms=row.wind_speed_ms,
        wind_direction_deg=row.wind_direction_deg,
        current_speed_ms=row.current_speed_ms,
        current_direction_deg=row.current_direction_deg,
        final_evaporated_pct=row.evaporated_pct,
        final_floating_pct=row.floating_pct,
        final_beached_pct=row.beached_pct,
        final_dispersed_pct=row.dispersed_pct,
        beaching_risk_level=row.beaching_risk_level,
        time_to_shore_hours=row.time_to_shore_hours,
        mass_balance_timeline=timeline,
        geojson=row.trajectory_geojson or {},
    )


def get_candidate_drift_simulation(
    db: Session,
    candidate_id: str,
) -> DriftSimulationOut:
    """Retrieve latest simulation for a candidate, or auto-run a 48h simulation."""
    query = (
        select(DriftSimulation)
        .where(DriftSimulation.candidate_id == candidate_id)
        .order_by(desc(DriftSimulation.created_at))
        .limit(1)
    )
    existing = db.execute(query).scalar_one_or_none()
    if existing:
        return get_drift_simulation(db, existing.simulation_id)  # type: ignore

    # Auto-run simulation for this candidate
    payload = DriftSimulationRequestIn(candidate_id=candidate_id, duration_hours=48)
    return run_drift_simulation(db, payload)

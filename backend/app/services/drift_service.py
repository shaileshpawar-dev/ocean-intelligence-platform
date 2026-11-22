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


#: What the engine falls back to when no current field is available. Named so
#: it reads as the placeholder it is rather than as a measurement.
PLACEHOLDER_CURRENT_MS = 0.22
PLACEHOLDER_CURRENT_DEG = 90.0


def _resolve_current(lat: float, lon: float) -> tuple[float, float, str]:
    """The modelled surface current at a point, or the placeholder.

    Returns ``(speed_ms, direction_deg, source)``. The source string is the
    point of the function: a track drawn from Copernicus currents and one
    drawn from a constant look identical, and only this tells them apart
    afterwards.

    Resolution order, cheapest first:

    1. A cached current for the monitored region containing the point, or
       failing that the nearest one. The regions tile the Indian EEZ, so an
       origin anywhere in it lands on real data without a network call --
       which matters because the serving image does not carry the Copernicus
       toolbox, and a drift request must not wait on object storage.
    2. A live Copernicus read, where the toolbox is available.
    3. The engine's placeholder constant, named as such.

    A neighbouring cell's current is an approximation, so the source says
    which region it came from and how far away it was. That is a weaker
    claim than "the current here", and it is written down as one.
    """
    from app.vision.cmems_client import CURRENTS_PRODUCT, get_cmems_client

    cached = _nearest_cached_current(lat, lon)
    if cached is not None:
        reading, distance_km, region = cached
        where = (
            f"at {region}"
            if distance_km < 1.0
            else f"from {region}, {distance_km:.0f} km away"
        )
        return (
            reading.speed_ms,
            reading.direction_deg,
            f"{CURRENTS_PRODUCT}, valid {reading.valid_on}, {where}",
        )

    client = get_cmems_client()
    half = 0.25
    reading = client.fetch_current(
        f"drift_{lat:.2f}_{lon:.2f}",
        (lon - half, lat - half, lon + half, lat + half),
    )
    if reading is not None:
        return (
            reading.speed_ms,
            reading.direction_deg,
            f"{CURRENTS_PRODUCT}, valid {reading.valid_on}",
        )

    return (
        PLACEHOLDER_CURRENT_MS,
        PLACEHOLDER_CURRENT_DEG,
        "placeholder constant (no current field available)",
    )


def _nearest_cached_current(lat: float, lon: float):
    """The cached regional current nearest a point.

    Returns ``(reading, distance_km, region_name)`` or ``None``. Distance is
    to the region centroid, which is what the cached current is a mean over.
    """
    import json
    import math

    from app.gee.regions import all_cells
    from app.vision.cmems_client import CACHE_DIR, CurrentReading

    best = None
    for cell in all_cells():
        files = sorted(CACHE_DIR.glob(f"current_{cell.code}_*.json"), reverse=True)
        if not files:
            continue
        centroid_lat, centroid_lon = cell.centroid
        # Equirectangular approximation: these are tens of kilometres over a
        # single EEZ, where the error is far below the grid spacing anyway.
        dx = (lon - centroid_lon) * math.cos(math.radians(lat)) * 111.32
        dy = (lat - centroid_lat) * 111.32
        distance = math.hypot(dx, dy)
        if best is not None and distance >= best[1]:
            continue
        try:
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            reading = CurrentReading(**payload)
        except (json.JSONDecodeError, OSError, TypeError):
            continue
        best = (reading, distance, cell.name)
    return best


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

    # Currents: the modelled field where the spill is, when the caller did
    # not pin them. The engine's fallback (0.22 m/s due east) is a
    # placeholder, and a track computed from it is a drawing rather than a
    # forecast -- so which one was used is recorded either way.
    current_spd = payload.current_speed_ms
    current_dir = payload.current_direction_deg
    current_source = "caller-supplied"
    if current_spd is None or current_dir is None:
        current_spd, current_dir, current_source = _resolve_current(
            origin_lat, origin_lon
        )

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
        current_speed_ms=current_spd,
        current_direction_deg=current_dir,
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
        current_source=current_source,
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
        current_source=current_source,
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
        current_source=row.current_source,
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

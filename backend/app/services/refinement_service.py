"""Stage-two refinement: subdivide flagged cells and re-observe at finer scale.

Why two stages
--------------
The monitoring grid subdivides each sea area into cells of roughly 10^4-10^5
km^2. That resolution is right for *screening* -- one cheap Earth Engine call
tells you whether a whole sea deserves attention -- but it is far too coarse
to support a claim about a surface slick. A dark region occupying even 10% of
an 8-degree cell is tens of thousands of km^2, an order of magnitude beyond any
recorded marine spill, so the detector's plausibility gate correctly refuses
to call it oil.

The answer is not to loosen the gate. It is to look closer:

    Stage 1  coarse grid, whole ocean, cheap
             -> "this cell has anomalous dark structure"
             -> signature is at most DARK_FORMATION

    Stage 2  subdivide the flagged cell, re-query at finer scale
             -> dark regions are now measured against a small cell
             -> a localised dark patch can reach slick-plausible extent
             -> OIL_LIKE_SIGNATURE becomes reachable, with evidence

This mirrors how operational services (CleanSeaNet and similar) work: screen
wide and cheap, confirm narrow and expensive. It also bounds cost -- only
cells that already look anomalous are refined, and the number refined per run
is capped.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.gee import get_satellite_provider
from app.gee.base import ObservationDTO
from app.gee.regions import GridCell
from app.models import (
    EvidenceLevel,
    PollutionEvent,
    PollutionSignature,
    Region,
    RiskAssessment,
    SatelliteObservation,
)
from app.risk.engine import get_risk_engine
from app.services.ingestion_service import deterministic_event_id
from app.vision.registry import get_sar_detector
from app.vision.sar_detector import MAX_PLAUSIBLE_SLICK_KM2

logger = get_logger(__name__)

#: Target sub-cell area. Chosen so a dark patch covering a modest fraction of
#: a sub-cell lands inside the plausible-slick range rather than above it.
TARGET_SUBCELL_KM2 = MAX_PLAUSIBLE_SLICK_KM2 * 2.5

#: Never subdivide beyond this factor per axis, to bound Earth Engine calls.
MAX_SUBDIVISION = 8

#: How many flagged cells to refine in one run.
DEFAULT_MAX_CELLS = 5


@dataclass(slots=True)
class RefinementSummary:
    """Outcome of one refinement pass."""

    cells_refined: int
    subcells_observed: int
    events_created: int
    upgraded_to_oil_like: int
    contains_simulated_data: bool

    def to_dict(self) -> dict:
        """Serialise the refinement summary for the API."""
        return {
            "cells_refined": self.cells_refined,
            "subcells_observed": self.subcells_observed,
            "events_created": self.events_created,
            "upgraded_to_oil_like": self.upgraded_to_oil_like,
            "contains_simulated_data": self.contains_simulated_data,
        }


def subdivision_factor(cell_area_km2: float) -> int:
    """Choose a per-axis subdivision so sub-cells approach the target area.

    Returns a factor in ``[2, MAX_SUBDIVISION]``. Squaring it gives the number
    of Earth Engine calls the refinement will cost for this cell.
    """
    if cell_area_km2 <= TARGET_SUBCELL_KM2:
        return 2
    factor = int((cell_area_km2 / TARGET_SUBCELL_KM2) ** 0.5) + 1
    return max(2, min(MAX_SUBDIVISION, factor))


def subdivide(region: Region, factor: int) -> list[GridCell]:
    """Split a region's bounding box into ``factor x factor`` sub-cells."""
    dlon = (region.max_lon - region.min_lon) / factor
    dlat = (region.max_lat - region.min_lat) / factor

    cells: list[GridCell] = []
    for row in range(factor):
        for col in range(factor):
            cells.append(
                GridCell(
                    code=f"{region.code}__r{row}c{col}",
                    name=f"{region.name} [{row},{col}]",
                    parent_name=region.name,
                    min_lon=region.min_lon + col * dlon,
                    min_lat=region.min_lat + row * dlat,
                    max_lon=region.min_lon + (col + 1) * dlon,
                    max_lat=region.min_lat + (row + 1) * dlat,
                )
            )
    return cells


def select_cells_for_refinement(
    db: Session, max_cells: int = DEFAULT_MAX_CELLS
) -> list[Region]:
    """Pick the most anomalous coarse cells worth a closer look.

    Ranks by the risk score of each region's worst open dark-formation event,
    so refinement budget goes where the screening stage saw the most
    structure.
    """
    rows = db.execute(
        select(PollutionEvent, Region)
        .join(Region, Region.id == PollutionEvent.region_id)
        .where(
            PollutionEvent.signature.in_(
                [
                    str(PollutionSignature.DARK_FORMATION),
                    str(PollutionSignature.OIL_LIKE_SIGNATURE),
                ]
            ),
            # Only refine cells that were not already produced by refinement.
            Region.parent_code.is_not(None),
        )
        .order_by(PollutionEvent.risk_score.desc().nullslast())
    ).all()

    seen: set[int] = set()
    selected: list[Region] = []
    for _event, region in rows:
        if region.id in seen or "__" in region.code:
            continue
        seen.add(region.id)
        selected.append(region)
        if len(selected) >= max_cells:
            break
    return selected


def refine_flagged_cells(
    db: Session, max_cells: int = DEFAULT_MAX_CELLS
) -> RefinementSummary:
    """Run stage-two refinement over the most anomalous screened cells.

    Sub-cell observations and their events are persisted like any other, but
    tagged so the dashboard can show that a fine-scale detection came from a
    targeted second look rather than the routine sweep.
    """
    provider = get_satellite_provider()
    detector = get_sar_detector()
    risk_engine = get_risk_engine()

    targets = select_cells_for_refinement(db, max_cells=max_cells)
    if not targets:
        return RefinementSummary(0, 0, 0, 0, False)

    refined = observed = created = upgraded = 0
    simulated = False

    for parent in targets:
        parent_area = _region_area_km2(parent)
        factor = subdivision_factor(parent_area)
        subcells = subdivide(parent, factor)

        logger.info(
            "refining_cell",
            extra={
                "region": parent.code,
                "parent_area_km2": round(parent_area),
                "factor": factor,
                "subcells": len(subcells),
                "subcell_area_km2": round(parent_area / (factor**2)),
            },
        )

        try:
            observations = provider.get_observations(
                subcells, settings.ingest_lookback_days
            )
        except Exception:
            logger.warning("refinement_fetch_failed", exc_info=True)
            continue

        refined += 1
        subcell_by_code = {c.code: c for c in subcells}

        for obs in observations:
            subcell = subcell_by_code.get(obs.cell_code)
            if subcell is None:
                continue
            if obs.evidence_level == EvidenceLevel.SIMULATED:
                simulated = True

            region = _ensure_subregion(db, parent, subcell)
            record = _persist_subobservation(db, obs, region)
            observed += 1

            for det in detector.predict(obs.to_detector_input()):
                if det.signature == PollutionSignature.NO_ANOMALY:
                    continue
                if det.signature == PollutionSignature.OIL_LIKE_SIGNATURE:
                    upgraded += 1

                evidence = (
                    EvidenceLevel.SIMULATED
                    if obs.evidence_level == EvidenceLevel.SIMULATED
                    else EvidenceLevel.DETECTED
                )
                risk = risk_engine.assess(
                    signature=str(det.signature),
                    confidence=det.confidence,
                    latitude=det.latitude,
                    longitude=det.longitude,
                    estimated_area_km2=det.estimated_area_km2,
                    evidence_level=(
                        EvidenceLevel.SIMULATED
                        if evidence == EvidenceLevel.SIMULATED
                        else EvidenceLevel.INFERRED
                    ),
                )

                # Deterministic, for the same reason as stage 1: refining
                # the same cell twice must not duplicate its detections.
                event_id = deterministic_event_id(
                    record.observation_id, str(det.signature)
                )
                if db.scalar(
                    select(PollutionEvent.id).where(PollutionEvent.event_id == event_id)
                ):
                    continue

                event = PollutionEvent(
                    event_id=event_id,
                    region_id=region.id,
                    observation_id=record.id,
                    signature=str(det.signature),
                    detection_method=str(det.method),
                    evidence_level=str(evidence),
                    confidence=det.confidence,
                    latitude=det.latitude or region.centroid_lat,
                    longitude=det.longitude or region.centroid_lon,
                    bbox=det.geo_bbox,
                    estimated_area_km2=det.estimated_area_km2,
                    area_method=det.area_method,
                    risk_score=risk.score,
                    severity=str(risk.severity),
                    detected_at=obs.acquired_at,
                    model_version=f"{detector.name}:{detector.version}",
                    caveats=[
                        f"Stage-2 refinement of {parent.name} at "
                        f"{factor}x{factor} subdivision "
                        f"(~{parent_area / factor**2:,.0f} km^2 per sub-cell).",
                        *det.caveats,
                    ],
                    extra={
                        **det.extra,
                        "refinement_stage": 2,
                        "parent_region_code": parent.code,
                        "subdivision_factor": factor,
                    },
                )
                db.add(event)
                db.flush()
                db.add(
                    RiskAssessment(
                        assessment_id=f"risk_{uuid.uuid4().hex[:12]}",
                        event_id=event.id,
                        score=risk.score,
                        severity=str(risk.severity),
                        engine_version=risk.engine_version,
                        contributions=[c.to_dict() for c in risk.contributions],
                        missing_factors=risk.missing_factors,
                        evidence_level=str(risk.evidence_level),
                        narrative=risk.narrative,
                    )
                )
                created += 1
        db.commit()

    summary = RefinementSummary(
        cells_refined=refined,
        subcells_observed=observed,
        events_created=created,
        upgraded_to_oil_like=upgraded,
        contains_simulated_data=simulated,
    )
    logger.info("refinement_complete", extra=summary.to_dict())
    return summary


def _region_area_km2(region: Region) -> float:
    """Spherical area of a region's bounding box."""
    import math

    from app.risk.geo import EARTH_RADIUS_KM

    lat1, lat2 = math.radians(region.min_lat), math.radians(region.max_lat)
    dlon = math.radians(region.max_lon - region.min_lon)
    return abs(EARTH_RADIUS_KM**2 * dlon * (math.sin(lat2) - math.sin(lat1)))


def _ensure_subregion(db: Session, parent: Region, cell: GridCell) -> Region:
    """Upsert a refinement sub-cell as its own region row."""
    region = db.scalar(select(Region).where(Region.code == cell.code))
    if region is not None:
        return region

    lat, lon = cell.centroid
    region = Region(
        code=cell.code,
        name=cell.name,
        parent_code=parent.name,
        min_lon=cell.min_lon,
        min_lat=cell.min_lat,
        max_lon=cell.max_lon,
        max_lat=cell.max_lat,
        centroid_lat=lat,
        centroid_lon=lon,
        distance_to_coast_km=parent.distance_to_coast_km,
        nearest_protected_area=parent.nearest_protected_area,
        distance_to_protected_area_km=parent.distance_to_protected_area_km,
    )
    db.add(region)
    db.flush()
    return region


def _persist_subobservation(
    db: Session, obs: ObservationDTO, region: Region
) -> SatelliteObservation:
    """Store a refinement observation, de-duplicated on cell and timestamp."""
    observation_id = f"obs_{obs.cell_code}_{int(obs.acquired_at.timestamp())}"
    existing = db.scalar(
        select(SatelliteObservation).where(
            SatelliteObservation.observation_id == observation_id
        )
    )
    if existing is not None:
        return existing

    record = SatelliteObservation(
        observation_id=observation_id,
        region_id=region.id,
        collection=obs.collection,
        platform=obs.platform,
        scene_id=obs.scene_id,
        acquired_at=obs.acquired_at,
        instrument_mode=obs.instrument_mode,
        polarisation=obs.polarisation,
        orbit_pass=obs.orbit_pass,
        scale_m=obs.scale_m,
        scene_count=obs.scene_count,
        mean_db=obs.mean_db,
        p10_db=obs.p10_db,
        p90_db=obs.p90_db,
        stddev_db=obs.stddev_db,
        min_db=obs.min_db,
        max_db=obs.max_db,
        evidence_level=str(obs.evidence_level),
        extra={**(obs.extra or {}), "refinement_stage": 2},
    )
    db.add(record)
    db.flush()
    return record

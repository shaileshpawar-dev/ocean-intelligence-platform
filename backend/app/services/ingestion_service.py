"""Ingestion pipeline: satellite observations to assessed pollution events.

Pipeline stages, each isolated and individually testable:

    provider.get_observations()      -> measurements   (OBSERVED)
        -> persist SatelliteObservation
        -> SARDarkFormationDetector  -> detections     (DETECTED)
        -> RiskEngine                -> risk score     (INFERRED)
        -> persist PollutionEvent + RiskAssessment

The stage boundaries are exactly where the original system blurred them.
Nothing in this module invents a classification, and cells whose detector
result is ``NO_ANOMALY`` are recorded as observations without an event --
an explicit negative rather than a silent gap.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.gee import all_cells, get_satellite_provider
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
from app.risk.geo import get_geographic_provider
from app.vision.registry import get_sar_detector

logger = get_logger(__name__)


def deterministic_event_id(observation_id: str, signature: str) -> str:
    """Stable event id for one (observation, signature) pair.

    Makes detection idempotent: re-running ingestion over the same scenes
    recognises the events it already stored instead of creating duplicates.
    """
    digest = hashlib.sha256(f"{observation_id}|{signature}".encode()).hexdigest()
    return f"evt_{digest[:16]}"


@dataclass(slots=True)
class IngestionSummary:
    """What one ingestion run did. Returned by the /ingest endpoint."""

    provider: str
    cells_requested: int
    observations_stored: int
    events_created: int
    negatives_recorded: int
    contains_simulated_data: bool
    errors: list[str]

    def to_dict(self) -> dict:
        """Serialise the run summary for the API and the log record."""
        return {
            "provider": self.provider,
            "cells_requested": self.cells_requested,
            "observations_stored": self.observations_stored,
            "events_created": self.events_created,
            "negatives_recorded": self.negatives_recorded,
            "contains_simulated_data": self.contains_simulated_data,
            "errors": self.errors,
        }


def ensure_regions(db: Session) -> dict[str, Region]:
    """Upsert every configured grid cell as a :class:`Region` row.

    Geographic context (coast and protected-area proximity) is computed once
    here rather than on every risk evaluation, since cell centroids are fixed.
    """
    geo = get_geographic_provider()
    existing = {r.code: r for r in db.scalars(select(Region)).all()}
    cells: list[GridCell] = all_cells()

    for cell in cells:
        lat, lon = cell.centroid
        region = existing.get(cell.code)
        if region is None:
            region = Region(
                code=cell.code,
                name=cell.name,
                parent_code=cell.parent_name,
                min_lon=cell.min_lon,
                min_lat=cell.min_lat,
                max_lon=cell.max_lon,
                max_lat=cell.max_lat,
                centroid_lat=lat,
                centroid_lon=lon,
            )
            db.add(region)
            existing[cell.code] = region

        if region.distance_to_coast_km is None:
            region.distance_to_coast_km = geo.distance_to_coast(lat, lon).distance_km
        if region.nearest_protected_area is None:
            mpa = geo.nearest_protected_area(lat, lon)
            region.nearest_protected_area = mpa.nearest_name
            region.distance_to_protected_area_km = mpa.distance_km

    db.commit()
    logger.info("regions_ensured", extra={"count": len(existing)})
    return existing


def _persist_observation(
    db: Session, obs: ObservationDTO, region: Region
) -> SatelliteObservation:
    """Store one measurement, de-duplicating on scene + cell + timestamp."""
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
        extra=obs.extra,
    )
    db.add(record)
    db.flush()
    return record


def run_ingestion(db: Session, lookback_days: int | None = None) -> IngestionSummary:
    """Execute one full ingestion cycle.

    Args:
        db: Active session.
        lookback_days: Search window; defaults to ``settings.ingest_lookback_days``.

    Returns:
        An :class:`IngestionSummary` describing what was stored.
    """
    provider = get_satellite_provider()
    detector = get_sar_detector()
    risk_engine = get_risk_engine()
    regions = ensure_regions(db)
    cells = all_cells()

    errors: list[str] = []
    try:
        observations = provider.get_observations(
            cells, lookback_days or settings.ingest_lookback_days
        )
    except Exception as exc:
        logger.error("ingestion_provider_failed", exc_info=True)
        return IngestionSummary(
            provider=provider.name,
            cells_requested=len(cells),
            observations_stored=0,
            events_created=0,
            negatives_recorded=0,
            contains_simulated_data=False,
            errors=[f"{type(exc).__name__}: {exc}"],
        )

    # Trend context, if any history exists yet. Imported here to avoid a
    # circular import at module load.
    from app.services.analytics_service import region_trend_slopes

    slopes = region_trend_slopes(db, days=14)

    stored = created = negatives = 0
    simulated = False

    for obs in observations:
        region = regions.get(obs.cell_code)
        if region is None:
            errors.append(f"unknown cell {obs.cell_code}")
            continue

        if obs.evidence_level == EvidenceLevel.SIMULATED:
            simulated = True

        record = _persist_observation(db, obs, region)
        stored += 1

        detections = detector.predict(obs.to_detector_input())
        if not detections:
            continue

        for det in detections:
            if det.signature == PollutionSignature.NO_ANOMALY:
                negatives += 1
                continue

            # A simulated measurement can only produce a simulated event.
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
                trend_slope=slopes.get(region.id),
                evidence_level=(
                    EvidenceLevel.SIMULATED
                    if evidence == EvidenceLevel.SIMULATED
                    else EvidenceLevel.INFERRED
                ),
            )

            # Deterministic id: one event per (observation, signature). A
            # random id would make every re-ingest of the same scene create a
            # duplicate detection, so a scheduled sweep would multiply events
            # without any new data arriving.
            event_id = deterministic_event_id(record.observation_id, str(det.signature))
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
                latitude=det.latitude
                if det.latitude is not None
                else region.centroid_lat,
                longitude=det.longitude
                if det.longitude is not None
                else region.centroid_lon,
                bbox=det.geo_bbox,
                estimated_area_km2=det.estimated_area_km2,
                area_method=det.area_method,
                risk_score=risk.score,
                severity=str(risk.severity),
                detected_at=obs.acquired_at,
                model_version=f"{detector.name}:{detector.version}",
                caveats=det.caveats,
                extra=det.extra,
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

    summary = IngestionSummary(
        provider=provider.name,
        cells_requested=len(cells),
        observations_stored=stored,
        events_created=created,
        negatives_recorded=negatives,
        contains_simulated_data=simulated,
        errors=errors,
    )
    logger.info("ingestion_complete", extra=summary.to_dict())

    # Refresh the daily aggregates the analytics and forecast layers read.
    from app.services.analytics_service import rebuild_history

    rebuild_history(db)
    return summary


def last_ingestion_at(db: Session) -> str | None:
    """ISO timestamp of the most recent stored observation, if any."""
    latest = db.scalar(
        select(SatelliteObservation.created_at).order_by(
            SatelliteObservation.created_at.desc()
        )
    )
    return latest.isoformat() if latest else None

"""Read services for pollution events, zones and alerts."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.optical import OpticalIndexObservation
from app.models import (
    EvidenceLevel,
    PollutionEvent,
    Region,
    RiskAssessment,
    SatelliteObservation,
)


def _event_to_dict(event: PollutionEvent, region: Region | None = None) -> dict:
    """Serialise an event with its provenance intact."""
    region = region or event.region
    return {
        "event_id": event.event_id,
        "region_code": region.code if region else None,
        "region_name": region.name if region else None,
        "parent_region": region.parent_code if region else None,
        "signature": event.signature,
        "detection_method": event.detection_method,
        "evidence_level": event.evidence_level,
        "confidence": round(event.confidence, 4),
        "confidence_is_calibrated": False,
        "latitude": event.latitude,
        "longitude": event.longitude,
        "bbox": event.bbox,
        "estimated_area_km2": event.estimated_area_km2,
        "area_method": event.area_method,
        "risk_score": round(event.risk_score, 2) if event.risk_score else None,
        "severity": event.severity,
        "detected_at": event.detected_at.isoformat(),
        "model_version": event.model_version,
        "caveats": event.caveats or [],
        "is_simulated": event.evidence_level == str(EvidenceLevel.SIMULATED),
    }


def list_events(
    db: Session,
    limit: int = 100,
    offset: int = 0,
    severity: str | None = None,
    signature: str | None = None,
    parent_region: str | None = None,
    since_days: int | None = None,
) -> list[dict]:
    """List pollution events, newest first, with optional filters."""
    stmt = (
        select(PollutionEvent, Region)
        .join(Region, Region.id == PollutionEvent.region_id)
        .order_by(PollutionEvent.detected_at.desc())
    )
    if severity:
        stmt = stmt.where(PollutionEvent.severity == severity.upper())
    if signature:
        stmt = stmt.where(PollutionEvent.signature == signature)
    if parent_region:
        stmt = stmt.where(Region.parent_code == parent_region)
    if since_days:
        stmt = stmt.where(
            PollutionEvent.detected_at >= datetime.now(UTC) - timedelta(days=since_days)
        )

    rows = db.execute(stmt.limit(limit).offset(offset)).all()
    return [_event_to_dict(event, region) for event, region in rows]


def get_event(db: Session, event_id: str) -> dict | None:
    """Fetch one event with its risk breakdown and source observation."""
    row = db.execute(
        select(PollutionEvent, Region)
        .join(Region, Region.id == PollutionEvent.region_id)
        .where(PollutionEvent.event_id == event_id)
        .options(joinedload(PollutionEvent.risk_assessments))
    ).first()
    if row is None:
        return None

    event, region = row
    payload = _event_to_dict(event, region)

    assessment = db.scalar(
        select(RiskAssessment)
        .where(RiskAssessment.event_id == event.id)
        .order_by(RiskAssessment.created_at.desc())
    )
    payload["risk_assessment"] = (
        {
            "assessment_id": assessment.assessment_id,
            "score": round(assessment.score, 2),
            "severity": assessment.severity,
            "engine_version": assessment.engine_version,
            "contributions": assessment.contributions,
            "missing_factors": assessment.missing_factors or [],
            "narrative": assessment.narrative,
            "evidence_level": assessment.evidence_level,
        }
        if assessment
        else None
    )

    observation = (
        db.get(SatelliteObservation, event.observation_id)
        if event.observation_id
        else None
    )
    payload["observation"] = (
        {
            "observation_id": observation.observation_id,
            "collection": observation.collection,
            "platform": observation.platform,
            "scene_id": observation.scene_id,
            "acquired_at": observation.acquired_at.isoformat(),
            "polarisation": observation.polarisation,
            "orbit_pass": observation.orbit_pass,
            "scale_m": observation.scale_m,
            "mean_db": observation.mean_db,
            "p10_db": observation.p10_db,
            "p90_db": observation.p90_db,
            "stddev_db": observation.stddev_db,
            "evidence_level": observation.evidence_level,
        }
        if observation
        else None
    )

    payload["geographic_context"] = {
        "distance_to_coast_km": region.distance_to_coast_km,
        "nearest_protected_area": region.nearest_protected_area,
        "distance_to_protected_area_km": region.distance_to_protected_area_km,
    }
    return payload


def list_zones(db: Session, limit: int = 200) -> list[dict]:
    """Current state per region: latest observation and its worst open event.

    This is the map layer's data source. Regions observed with no detection
    are included with ``signature: null`` -- a cell that was looked at and
    found clean is information the map should show.
    """
    regions = db.scalars(select(Region).limit(limit)).all()
    zones: list[dict] = []

    for region in regions:
        observation = db.scalar(
            select(SatelliteObservation)
            .where(SatelliteObservation.region_id == region.id)
            .order_by(SatelliteObservation.acquired_at.desc())
        )
        # The SAR observation table holds radar backscatter statistics and is
        # empty since the seeded rows were removed. The platform's real
        # observations are Sentinel-2 index readings in their own table, so a
        # region with one of those has certainly been looked at -- and
        # skipping it here emptied the whole map layer.
        optical = (
            None
            if observation is not None
            else db.scalar(
                select(OpticalIndexObservation)
                .where(OpticalIndexObservation.region_id == region.id)
                .order_by(OpticalIndexObservation.observed_on.desc())
            )
        )
        if observation is None and optical is None:
            continue

        event = db.scalar(
            select(PollutionEvent)
            .where(PollutionEvent.region_id == region.id)
            .order_by(PollutionEvent.risk_score.desc().nullslast())
        )

        zones.append(
            {
                "region_code": region.code,
                "region_name": region.name,
                "parent_region": region.parent_code,
                "latitude": region.centroid_lat,
                "longitude": region.centroid_lon,
                "bbox": [
                    region.min_lon,
                    region.min_lat,
                    region.max_lon,
                    region.max_lat,
                ],
                "last_observed_at": (
                    observation.acquired_at.isoformat()
                    if observation is not None
                    else datetime.combine(
                        optical.observed_on, time(0, 0), tzinfo=UTC
                    ).isoformat()
                ),
                # Backscatter is a radar quantity. An optical cell has none,
                # and reporting a number here would be inventing one.
                "mean_backscatter_db": (
                    observation.mean_db if observation is not None else None
                ),
                "platform": (
                    observation.platform if observation is not None else "Sentinel-2"
                ),
                "observation_evidence_level": (
                    observation.evidence_level
                    if observation is not None
                    else optical.evidence_level
                ),
                "signature": event.signature if event else None,
                "confidence": round(event.confidence, 4) if event else None,
                "risk_score": (
                    round(event.risk_score, 2)
                    if event and event.risk_score is not None
                    else None
                ),
                "severity": event.severity if event else None,
                "event_id": event.event_id if event else None,
                "is_simulated": (
                    observation.evidence_level == str(EvidenceLevel.SIMULATED)
                    if observation is not None
                    else False
                ),
            }
        )
    return zones


def list_alerts(db: Session, min_severity: str = "HIGH") -> list[dict]:
    """Open events at or above a severity threshold, worst first."""
    ranking = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    floor = ranking.get(min_severity.upper(), 2)
    allowed = [name for name, rank in ranking.items() if rank >= floor]

    rows = db.execute(
        select(PollutionEvent, Region)
        .join(Region, Region.id == PollutionEvent.region_id)
        .where(PollutionEvent.severity.in_(allowed))
        .order_by(PollutionEvent.risk_score.desc().nullslast())
    ).all()

    return [
        {
            "event_id": event.event_id,
            "severity": event.severity,
            "risk_score": round(event.risk_score, 2) if event.risk_score else None,
            "signature": event.signature,
            "region_name": region.name,
            "parent_region": region.parent_code,
            "confidence": round(event.confidence, 4),
            "detected_at": event.detected_at.isoformat(),
            "message": (
                f"{event.signature.replace('_', ' ').title()} in {region.name} "
                f"({event.severity}, risk {event.risk_score:.0f}/100)"
                if event.risk_score is not None
                else f"{event.signature} in {region.name}"
            ),
            "is_simulated": event.evidence_level == str(EvidenceLevel.SIMULATED),
            "caveats": event.caveats or [],
        }
        for event, region in rows
    ]

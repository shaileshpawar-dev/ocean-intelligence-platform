"""Service layer for AIS vessel intelligence and trajectory association (Phase 15)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.sar_candidate import SARCandidate
from app.models.vessel import CandidateVesselAssociation, Vessel, VesselPosition
from app.schemas.vessel import (
    CandidateVesselAssociationOut,
    VesselDetailOut,
    VesselOut,
    VesselPositionOut,
)
from app.vision.ais_associator import AISAssociationEngine

logger = get_logger(__name__)


def list_vessels(
    db: Session,
    vessel_type: str | None = None,
    risk_profile: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[VesselOut]:
    """Retrieve indexed commercial vessels with optional filtering."""
    query = select(Vessel)
    if vessel_type:
        query = query.where(Vessel.vessel_type == vessel_type)
    if risk_profile:
        query = query.where(Vessel.risk_profile == risk_profile)
    if search:
        s = f"%{search.strip().lower()}%"
        query = query.where(
            (Vessel.name.ilike(s)) | (Vessel.mmsi.ilike(s)) | (Vessel.imo.ilike(s))
        )
    query = query.order_by(Vessel.name).offset(offset).limit(limit)
    rows = db.execute(query).scalars().all()
    return [VesselOut.model_validate(r) for r in rows]


def get_vessel_detail(db: Session, mmsi: str) -> VesselDetailOut | None:
    """Retrieve vessel particulars along with historical AIS ping trajectory."""
    vessel = db.get(Vessel, mmsi)
    if not vessel:
        return None
    return VesselDetailOut(
        mmsi=vessel.mmsi,
        imo=vessel.imo,
        name=vessel.name,
        callsign=vessel.callsign,
        vessel_type=vessel.vessel_type,
        flag_country=vessel.flag_country,
        length_m=vessel.length_m,
        width_m=vessel.width_m,
        draught_m=vessel.draught_m,
        risk_profile=vessel.risk_profile,
        positions=[VesselPositionOut.model_validate(p) for p in vessel.positions],
    )


def get_candidate_vessel_associations(
    db: Session,
    candidate_id: str,
) -> list[CandidateVesselAssociationOut]:
    """Retrieve correlated vessel associations for a candidate, auto-running correlation if none exist."""
    associations = (
        db.query(CandidateVesselAssociation)
        .filter_by(candidate_id=candidate_id)
        .order_by(desc(CandidateVesselAssociation.association_score))
        .all()
    )

    if not associations:
        engine = AISAssociationEngine()
        try:
            associations = engine.correlate_candidate(db, candidate_id)
        except ValueError:
            return []

    res: list[CandidateVesselAssociationOut] = []
    for a in associations:
        v = a.vessel
        res.append(
            CandidateVesselAssociationOut(
                id=a.id,
                candidate_id=a.candidate_id,
                mmsi=a.mmsi,
                vessel_name=v.name if v else "Unknown Vessel",
                vessel_type=v.vessel_type if v else "Unknown",
                flag_country=v.flag_country if v else "Unknown",
                association_type=a.association_type,
                spatial_distance_km=a.spatial_distance_km,
                temporal_offset_minutes=a.temporal_offset_minutes,
                interpolated_lat=a.interpolated_lat,
                interpolated_lon=a.interpolated_lon,
                association_score=a.association_score,
                is_primary_suspect=a.is_primary_suspect,
                notes=a.notes,
            )
        )
    return res


def trigger_candidate_vessel_correlation(
    db: Session,
    candidate_id: str,
) -> list[CandidateVesselAssociationOut]:
    """Force re-correlation of AIS vessel tracks against candidate coordinates."""
    engine = AISAssociationEngine()
    associations = engine.correlate_candidate(db, candidate_id)
    return get_candidate_vessel_associations(db, candidate_id)

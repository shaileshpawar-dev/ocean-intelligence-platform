"""FastAPI routes for AIS vessel tracking and candidate trajectory association (Phase 15)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.vessel import (
    CandidateVesselAssociationOut,
    VesselDetailOut,
    VesselOut,
)
from app.services import vessel_service

router = APIRouter(prefix="/vessels", tags=["vessels"])


@router.get("", response_model=list[VesselOut])
def list_vessels(
    vessel_type: str | None = Query(default=None, description="Filter by vessel type"),
    risk_profile: str | None = Query(default=None, description="Filter by risk profile"),
    search: str | None = Query(default=None, description="Search by name, MMSI, or IMO"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[VesselOut]:
    """List commercial vessels registered in the AIS tracking registry."""
    return vessel_service.list_vessels(
        db=db,
        vessel_type=vessel_type,
        risk_profile=risk_profile,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/{mmsi}", response_model=VesselDetailOut)
def get_vessel(
    mmsi: str,
    db: Session = Depends(get_db),
) -> VesselDetailOut:
    """Retrieve full particulars and recorded AIS trajectory pings for a vessel."""
    vessel = vessel_service.get_vessel_detail(db, mmsi)
    if not vessel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vessel with MMSI {mmsi!r} not found.",
        )
    return vessel

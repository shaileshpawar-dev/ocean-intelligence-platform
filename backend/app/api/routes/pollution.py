"""Pollution event, zone and alert endpoints.

Routes stay thin: parse, delegate to a service, wrap in an envelope. No
business logic lives here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import demo_mode_notes, make_provenance
from app.core.database import get_db
from app.gee import get_satellite_provider
from app.schemas.common import ListResponse
from app.schemas.pollution import (
    AlertOut,
    PollutionEventDetailOut,
    PollutionEventOut,
    ZoneOut,
)
from app.services import pollution_service

router = APIRouter(tags=["pollution"])


@router.get(
    "/pollution-events",
    response_model=ListResponse[PollutionEventOut],
    summary="List pollution events",
)
def list_pollution_events(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    severity: str | None = Query(None, description="LOW | MEDIUM | HIGH | CRITICAL"),
    signature: str | None = Query(None, description="e.g. oil_like_signature"),
    parent_region: str | None = Query(None, description="e.g. Arabian Sea"),
    since_days: int | None = Query(None, ge=1, le=365),
    db: Session = Depends(get_db),
) -> ListResponse[PollutionEventOut]:
    """Detections made by the platform, newest first."""
    items = pollution_service.list_events(
        db,
        limit=limit,
        offset=offset,
        severity=severity,
        signature=signature,
        parent_region=parent_region,
        since_days=since_days,
    )
    return ListResponse[PollutionEventOut](
        count=len(items),
        items=items,
        provenance=make_provenance("pollution_events", items, notes=demo_mode_notes()),
    )


@router.get(
    "/pollution-events/{event_id}",
    response_model=PollutionEventDetailOut,
    summary="Event detail with risk breakdown and source measurement",
)
def get_pollution_event(
    event_id: str, db: Session = Depends(get_db)
) -> PollutionEventDetailOut:
    """One event, its explainable risk assessment and the measurement behind it."""
    event = pollution_service.get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"No event {event_id!r}")
    return PollutionEventDetailOut(**event)


@router.get(
    "/pollution-zones",
    response_model=ListResponse[ZoneOut],
    summary="Current state of every monitored cell",
)
def list_pollution_zones(
    limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)
) -> ListResponse[ZoneOut]:
    """Map layer data.

    Cells observed with no detection are included with a null ``signature``.
    A cell that was looked at and found clean is a real result, and hiding it
    would make the map imply that everywhere unmarked is unmonitored.
    """
    items = pollution_service.list_zones(db, limit=limit)
    provider = get_satellite_provider()
    return ListResponse[ZoneOut](
        count=len(items),
        items=items,
        provenance=make_provenance(
            f"zones:{provider.name}",
            items,
            evidence_key="observation_evidence_level",
            notes=demo_mode_notes(),
        ),
    )


@router.get(
    "/alerts",
    response_model=ListResponse[AlertOut],
    summary="Events at or above a severity threshold",
)
def list_alerts(
    min_severity: str = Query("HIGH", description="LOW | MEDIUM | HIGH | CRITICAL"),
    db: Session = Depends(get_db),
) -> ListResponse[AlertOut]:
    """Operator alerts, highest risk first."""
    items = pollution_service.list_alerts(db, min_severity=min_severity)
    return ListResponse[AlertOut](
        count=len(items),
        items=items,
        provenance=make_provenance("alerts", items, notes=demo_mode_notes()),
    )

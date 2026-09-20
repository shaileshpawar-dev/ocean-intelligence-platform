"""Water intelligence HTTP layer.

Routes parse, delegate and wrap. Every collection response carries the
platform's provenance envelope, so a client can tell measured data from
inferred and can see which source produced it without a second call.

Endpoint naming follows the domain rather than the storage: a caller asks for
``/water-bodies/mithi-river``, not for a row id, because the slug is what the
UI routes on and what a person can read in a URL.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import make_provenance
from app.core.database import get_db
from app.services import water_service as ws
from app.water.parameters import registry_summary
from app.water.standards import DEFAULT_USE, DesignatedUse, standards_summary

router = APIRouter(tags=["water"])

DbSession = Annotated[Session, Depends(get_db)]

WATER_SOURCE_NOTE = (
    "Water-quality values are laboratory measurements published by CPCB "
    "through the National Water Informatics Centre. They are not satellite "
    "estimates and not model output."
)


def _parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    """Parse ``min_lat,min_lon,max_lat,max_lon``.

    Raises 422 on a malformed box rather than silently ignoring it, because a
    dropped filter would quietly return the whole country to a map that asked
    for one district.
    """
    if not bbox:
        return None
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(
            status_code=422,
            detail="bbox must be 'min_lat,min_lon,max_lat,max_lon'.",
        )
    try:
        min_lat, min_lon, max_lat, max_lon = (float(p) for p in parts)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="bbox values must be numbers."
        ) from exc
    if min_lat > max_lat or min_lon > max_lon:
        raise HTTPException(status_code=422, detail="bbox minimum exceeds maximum.")
    return min_lat, min_lon, max_lat, max_lon


# ---------------------------------------------------------------------------
# Water bodies
# ---------------------------------------------------------------------------
@router.get("/water-bodies", summary="List water bodies")
def list_water_bodies(
    db: DbSession,
    state: str | None = None,
    district: str | None = None,
    water_type: str | None = None,
    status: str | None = None,
    q: str | None = None,
    bbox: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """Water bodies matching the given filters."""
    filters = ws.WaterBodyFilters(
        state=state,
        district=district,
        water_type=water_type,
        status=status,
        query=q,
        bbox=_parse_bbox(bbox),
    )
    items, total = ws.list_water_bodies(db, filters, limit=limit, offset=offset)
    return {
        "count": len(items),
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
        "provenance": make_provenance(
            "water:cpcb_nwdp", notes=[WATER_SOURCE_NOTE]
        ).model_dump(),
    }


@router.get("/water-bodies/{slug}", summary="Water body detail")
def water_body_detail(
    db: DbSession,
    slug: str,
    designated_use: DesignatedUse = DEFAULT_USE,
) -> dict:
    """One water body with status, parameters, stations and sources."""
    detail = ws.get_water_body_detail(db, slug, use=designated_use)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No water body '{slug}'.")
    detail["provenance"] = make_provenance(
        "water:cpcb_nwdp", notes=[WATER_SOURCE_NOTE]
    ).model_dump()
    return detail


@router.get("/water-bodies/{slug}/parameters", summary="Plottable parameters")
def water_body_parameters(db: DbSession, slug: str) -> dict:
    """Parameters measured on this water body and whether they can be plotted."""
    items = ws.available_parameters(db, slug)
    if not items and ws.get_water_body_detail(db, slug) is None:
        raise HTTPException(status_code=404, detail=f"No water body '{slug}'.")
    return {"count": len(items), "items": items}


@router.get("/water-bodies/{slug}/trend", summary="Parameter time series")
def water_body_trend(
    db: DbSession,
    slug: str,
    parameter: str = Query(..., description="Canonical parameter key."),
    days: int | None = Query(None, ge=1, le=36500),
) -> dict:
    """Observed values over time for one parameter.

    Returns only the points that exist. Gaps are left as gaps: interpolating
    across a period when nobody sampled would draw a line the data does not
    support.
    """
    trend = ws.parameter_trend(db, slug, parameter, days=days)
    if trend is None:
        raise HTTPException(
            status_code=404,
            detail=f"No water body '{slug}' or unknown parameter '{parameter}'.",
        )
    trend["provenance"] = make_provenance(
        "water:cpcb_nwdp", notes=[WATER_SOURCE_NOTE]
    ).model_dump()
    return trend


@router.get("/water-bodies/{slug}/stations", summary="Stations on a water body")
def water_body_stations(db: DbSession, slug: str) -> dict:
    """Monitoring stations attached to this water body."""
    detail = ws.get_water_body_detail(db, slug)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No water body '{slug}'.")
    return {"count": len(detail["stations"]), "items": detail["stations"]}


@router.get("/water-bodies/{slug}/sources", summary="Sources for a water body")
def water_body_sources(db: DbSession, slug: str) -> dict:
    """Which datasets contributed this water body's observations."""
    detail = ws.get_water_body_detail(db, slug)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No water body '{slug}'.")
    return {"count": len(detail["sources"]), "items": detail["sources"]}


# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------
@router.get("/stations", summary="List monitoring stations")
def list_stations(
    db: DbSession,
    state: str | None = None,
    bbox: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
) -> dict:
    """Monitoring stations, optionally within a viewport."""
    items = ws.map_stations(db, bbox=_parse_bbox(bbox), state=state, limit=limit)
    return {
        "count": len(items),
        "items": items,
        "provenance": make_provenance("water:stations").model_dump(),
    }


@router.get("/stations/{station_id}", summary="Station detail")
def station_detail(db: DbSession, station_id: int) -> dict:
    """One station with its latest observations."""
    detail = ws.station_detail(db, station_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No station with id {station_id}.")
    return detail


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
@router.get("/map/water-bodies", summary="Map features: water bodies")
def map_water_bodies(
    db: DbSession,
    bbox: str | None = None,
    state: str | None = None,
    water_type: str | None = None,
    status: str | None = None,
    limit: int = Query(1000, ge=1, le=2000),
) -> dict:
    """Water bodies as lightweight map features.

    Deliberately thinner than the list endpoint: the map needs a position, a
    status and a label, and sending the full record for every feature is what
    makes a map of a whole country slow.
    """
    filters = ws.WaterBodyFilters(
        state=state,
        water_type=water_type,
        status=status,
        bbox=_parse_bbox(bbox),
    )
    items = ws.map_water_bodies(db, filters, limit=limit)
    return {"count": len(items), "items": items}


@router.get("/map/stations", summary="Map features: stations")
def map_stations(
    db: DbSession,
    bbox: str | None = None,
    state: str | None = None,
    limit: int = Query(1000, ge=1, le=2000),
) -> dict:
    """Monitoring stations as map features."""
    items = ws.map_stations(db, bbox=_parse_bbox(bbox), state=state, limit=limit)
    return {"count": len(items), "items": items}


@router.get("/map/near", summary="Water bodies near a point")
def map_near(
    db: DbSession,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(25.0, gt=0, le=500),
    water_type: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """Water bodies within a true circle of a point, nearest first."""
    items = ws.water_bodies_near(
        db,
        lat,
        lon,
        radius_km,
        limit=limit,
        water_type=water_type,
        status=status,
    )
    return {
        "count": len(items),
        "centre": {"latitude": lat, "longitude": lon},
        "radius_km": radius_km,
        "items": items,
        "provenance": make_provenance(
            "water:spatial",
            notes=[
                "Distances are great-circle from the water body's centroid, "
                "which is the mean position of its monitoring stations rather "
                "than a surveyed centre."
            ],
        ).model_dump(),
    }


# ---------------------------------------------------------------------------
# Geography
# ---------------------------------------------------------------------------
@router.get("/states", summary="States with coverage counts")
def list_states(db: DbSession) -> dict:
    """Every state present in the ingested data."""
    items = ws.list_states(db)
    return {"count": len(items), "items": items}


@router.get("/states/{slug}", summary="State detail")
def state_detail(db: DbSession, slug: str) -> dict:
    """Coverage, status distribution and notable water bodies for one state."""
    detail = ws.state_detail(db, slug)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No state '{slug}'.")
    return detail


@router.get("/cities/{slug}", summary="City or district detail")
def district_detail(db: DbSession, slug: str) -> dict:
    """Water bodies and stations within one district.

    Districts double as the platform's city unit: Indian monitoring data is
    keyed to districts, and the places people search for -- Mumbai, Pune,
    Bengaluru -- are districts in that data.
    """
    detail = ws.district_detail(db, slug)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No district '{slug}'.")
    return detail


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
@router.get("/search", summary="Unified water search")
def search(
    db: DbSession,
    q: str = Query(..., min_length=2, description="Free-text query."),
    limit: int = Query(25, ge=1, le=50),
) -> dict:
    """Search water bodies, states, districts and stations at once."""
    items = ws.search(db, q, limit=limit)
    return {"query": q, "count": len(items), "items": items}


# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------
@router.get("/water-overview", summary="Water intelligence headline counters")
def water_overview(db: DbSession) -> dict:
    """Counters for the dashboard, every one a count of ingested records."""
    return ws.overview(db)


@router.get("/water-standards", summary="Reference standards in force")
def water_standards() -> dict:
    """The thresholds the status engine applies, with their sources."""
    return standards_summary()


@router.get("/water-parameters", summary="Canonical parameter registry")
def water_parameters() -> dict:
    """Parameters the platform recognises and the units it normalises to."""
    return registry_summary()


@router.get("/water-quality-report", summary="Ingestion data quality")
def water_quality_report(db: DbSession) -> dict:
    """Validation outcomes, so data problems are countable rather than hidden."""
    return ws.data_quality(db)

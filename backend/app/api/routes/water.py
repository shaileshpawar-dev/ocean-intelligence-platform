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

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import make_provenance
from app.core.database import get_db
from app.services import geo_service as gs
from app.services import water_service as ws
from app.water.parameters import registry_summary
from app.water.standards import standards_summary

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
    reference: str | None = Query(
        None,
        pattern=r"^[A-Ea-e]$|^[A-Z0-9-]{3,48}$",
        description=(
            "Compare against a specific standard: a CPCB designated-use class "
            "letter (A-E) or a standard code. Omit to let the platform select "
            "the applicable reference, which may be none."
        ),
    ),
) -> dict:
    """One water body with status, parameters, stations and sources."""
    detail = ws.get_water_body_detail(db, slug, reference=reference)
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


@router.get("/water-bodies/{slug}/geometry", summary="Geometry with provenance")
def water_body_geometry(db: DbSession, slug: str) -> dict:
    """The matched geometry, or why there is none."""
    from sqlalchemy import select

    from app.models.water import WaterBody

    body = db.scalar(select(WaterBody).where(WaterBody.slug == slug))
    if body is None:
        raise HTTPException(status_code=404, detail=f"No water body '{slug}'.")
    return {
        "slug": slug,
        "geometry_status": body.geometry_status,
        "geometry_status_text": gs.GEOMETRY_STATUS_TEXT.get(body.geometry_status, ""),
        "geometry": gs.water_body_geometry(db, body),
    }


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


@router.get("/map/geometries", summary="Map features: water-body geometry")
def map_geometries(
    db: DbSession,
    bbox: str | None = None,
    zoom: int | None = Query(None, ge=0, le=22),
    state: str | None = None,
    water_type: str | None = None,
    status: str | None = None,
    limit: int = Query(gs.GEOMETRY_LIMIT, ge=1, le=gs.GEOMETRY_LIMIT),
) -> dict:
    """Rivers as lines and lakes as polygons, where a geometry was matched.

    Simplified for ``zoom`` for display only. Water bodies without a matched
    geometry are not drawn as shapes; they stay as points on the point layer.
    """
    return gs.map_geometries(
        db,
        bbox=_parse_bbox(bbox),
        zoom=zoom,
        state=state,
        water_type=water_type,
        status=status,
        limit=limit,
    )


@router.get("/map/station-clusters", summary="Map features: clustered stations")
def map_station_clusters(
    db: DbSession,
    bbox: str | None = None,
    zoom: int = Query(5, ge=0, le=22),
    state: str | None = None,
) -> dict:
    """Stations clustered server-side on a grid sized to ``zoom``."""
    return gs.station_clusters(db, bbox=_parse_bbox(bbox), zoom=zoom, state=state)


@router.get("/map/layers", summary="Map layer catalogue")
def map_layers() -> dict:
    """Layer groups, sources and attributions, so the client hardcodes none."""
    return gs.layer_catalogue()


# ---------------------------------------------------------------------------
# Geography
# ---------------------------------------------------------------------------
@router.get("/boundaries/states", summary="State and UT boundaries")
def state_boundaries(
    db: DbSession, zoom: int | None = Query(None, ge=0, le=22)
) -> Response:
    """All state / UT polygons, simplified for ``zoom``."""
    return Response(
        gs.boundaries_json(db, level="state", zoom=zoom), media_type="application/json"
    )


@router.get("/boundaries/districts", summary="District boundaries")
def district_boundaries(
    db: DbSession,
    state: str | None = None,
    bbox: str | None = None,
    zoom: int | None = Query(None, ge=0, le=22),
) -> Response:
    """District polygons for one state or a viewport (one is required)."""
    if not state and not bbox:
        raise HTTPException(
            status_code=422, detail="Pass a state or a bbox; all 735 at once is too much."
        )
    return Response(
        gs.boundaries_json(
            db, level="district", state=state, bbox=_parse_bbox(bbox), zoom=zoom
        ),
        media_type="application/json",
    )


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


@router.get("/cities", summary="Curated cities")
def list_cities(db: DbSession) -> dict:
    """Cities, each an explicit, documented grouping of districts."""
    items = gs.list_cities(db)
    return {"count": len(items), "items": items}


@router.get("/cities/{slug}", summary="City or district detail")
def district_detail(db: DbSession, slug: str) -> dict:
    """A curated city, or else a district with that slug.

    Cities are named groupings of whole districts (Greater Mumbai is the
    Mumbai and Mumbai Suburban districts). A slug that is not a curated city
    falls back to the district of that name, as in Phase 1.
    """
    city = gs.city_detail(db, slug)
    if city is not None:
        return city
    detail = ws.district_detail(db, slug)
    if detail is not None:
        detail = {**detail, "kind": "district"}
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
    """Search water bodies, cities, states, districts and stations at once.

    ``ask_suggested`` is true when the text reads as a question ("polluted
    rivers near Mumbai") rather than a name, so the client can send it to
    the grounded question endpoint instead of listing name matches.
    """
    from app.water.rag import Intent, classify_intent

    items = ws.search(db, q, limit=limit)
    words = q.split()
    intent = classify_intent(q)
    ask = len(words) >= 3 and intent is not Intent.UNKNOWN
    return {
        "query": q,
        "count": len(items),
        "items": items,
        "ask_suggested": ask,
        "intent": str(intent) if ask else None,
    }


# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------
@router.get("/water-overview", summary="Water intelligence headline counters")
def water_overview(db: DbSession) -> dict:
    """Counters for the dashboard, every one a count of ingested records."""
    return ws.overview(db)


@router.get("/water-coverage", summary="What the database holds")
def water_coverage(db: DbSession) -> dict:
    """Counts per state, computed from the tables; nothing estimated."""
    from app.water.coverage import cached_coverage_report

    return cached_coverage_report(db)


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


@router.get("/water-jobs", summary="Recent offline job runs")
def water_jobs(
    db: DbSession,
    limit: int = Query(20, ge=1, le=100),
    job_type: str | None = Query(None, description="ingestion, geometry, satellite…"),
) -> dict:
    """What the offline jobs did, and when each kind last succeeded.

    Read-only and small on purpose: enough to answer "is the data being
    refreshed, and did last night's run work?" without a console. The web
    application never runs these jobs -- it only reports what they recorded.
    """
    return ws.job_runs(db, limit=limit, job_type=job_type)


# ---------------------------------------------------------------------------
# Water intelligence Q&A
# ---------------------------------------------------------------------------
class WaterQuestion(BaseModel):
    """A natural-language question about Indian water bodies."""

    question: str = Field(..., min_length=3, max_length=500)


@router.post("/water/ask", summary="Ask a grounded question about water bodies")
def water_ask(db: DbSession, body: WaterQuestion) -> dict:
    """Answer from stored observations, with citations and a map action.

    Entity resolution and every figure come from database lookups. When no
    record supports an answer the response says so (``no_evidence``) rather
    than producing one.
    """
    from app.water.rag import answer

    return answer(db, body.question)

"""Map and geography queries: geometries, clusters, boundaries, cities.

Everything here reads stored, attributed data. Display-time simplification is
the only transformation, and it never changes what is stored.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Row, Select, func, or_, select
from sqlalchemy.orm import Session

from app.models.water import (
    District,
    MonitoringStation,
    State,
    WaterBody,
    WaterQualityObservation,
)
from app.models.water_geo import AdminBoundary, City, WaterBodyGeometry
from app.services import water_service as ws
from app.water import geo
from app.water.boundaries import SOURCES as BOUNDARY_SOURCES
from app.water.geometry import OSM_LICENCE, OSM_SOURCE
from app.water.matching import haversine_km
from app.water.status import status_rank

BBox = tuple[float, float, float, float]  # (min_lat, min_lon, max_lat, max_lon)

GEOMETRY_LIMIT = 800
"""Geometries per map request. Beyond this the client is zoomed out too far
for line and polygon detail to be legible anyway."""

CLUSTER_SINGLE_ZOOM = 11
"""From this zoom every station is sent individually."""

CORE_PARAMETERS = ("bod", "dissolved_oxygen", "ph", "fecal_coliform")

BOUNDARY_DISCLAIMER = (
    "Boundaries are from geoBoundaries for navigation and filtering. They are "
    "not the official boundaries of India as published by the Survey of India."
)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return value.isoformat()


def _body_bbox_filter(stmt: Select, bbox: BBox) -> Select:
    min_lat, min_lon, max_lat, max_lon = bbox
    return stmt.where(
        WaterBodyGeometry.max_lat >= min_lat,
        WaterBodyGeometry.min_lat <= max_lat,
        WaterBodyGeometry.max_lon >= min_lon,
        WaterBodyGeometry.min_lon <= max_lon,
    )


# ---------------------------------------------------------------------------
# Hydrology geometry
# ---------------------------------------------------------------------------
def map_geometries(
    db: Session,
    *,
    bbox: BBox | None = None,
    zoom: int | None = None,
    state: str | None = None,
    water_type: str | None = None,
    status: str | None = None,
    limit: int = GEOMETRY_LIMIT,
) -> dict:
    """Stored water-body geometries in a viewport, as a FeatureCollection."""
    stmt = select(WaterBodyGeometry, WaterBody).join(
        WaterBody, WaterBody.id == WaterBodyGeometry.water_body_id
    )
    if bbox:
        stmt = _body_bbox_filter(stmt, bbox)
    if state:
        stmt = stmt.join(State, State.id == WaterBody.state_id).where(
            or_(
                func.lower(State.slug) == state.lower(),
                func.upper(State.code) == state.upper(),
            )
        )
    if water_type:
        stmt = stmt.where(WaterBody.water_type == water_type)
    if status:
        stmt = stmt.where(WaterBody.cached_historical_status == status)
    rows = db.execute(
        stmt.order_by(WaterBody.observation_count.desc()).limit(limit + 1)
    ).all()
    truncated = len(rows) > limit

    features = []
    for g, body in rows[:limit]:
        geometry = geo.display_geometry(json.loads(g.geojson), zoom)
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "slug": body.slug,
                    "name": body.name,
                    "water_type": str(body.water_type),
                    "geometry_type": g.geometry_type,
                    "latest_available_status": body.cached_historical_status,
                    "status": body.cached_status,
                    "confidence": g.confidence,
                    "source": g.source,
                    "clipped": g.clipped,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "count": len(features),
        "truncated": truncated,
        "attribution": f"Geometry: {OSM_LICENCE}",
    }


def water_body_geometry(db: Session, body: WaterBody) -> dict | None:
    """Geometry with its full provenance, for the detail page."""
    row = db.scalar(
        select(WaterBodyGeometry).where(WaterBodyGeometry.water_body_id == body.id)
    )
    if row is None:
        return None
    return {
        "geometry": json.loads(row.geojson),
        "geometry_type": row.geometry_type,
        "bbox": [row.min_lon, row.min_lat, row.max_lon, row.max_lat],
        "provenance": {
            "source": row.source,
            "source_ids": row.source_ids,
            "licence": row.source_licence,
            "retrieved_at": _iso(row.retrieved_at),
            "version": row.version,
            "confidence": row.confidence,
            "match_method": row.match_method,
            "match_notes": row.match_notes,
            "feature_count": row.feature_count,
            "clipped": row.clipped,
            "clipped_note": (
                "Only the monitored reaches near stations are shown, not the whole river."
                if row.clipped
                else None
            ),
        },
    }


GEOMETRY_STATUS_TEXT: dict[str, str] = {
    "matched": "Geometry matched from OpenStreetMap.",
    "not_attempted": "Geometry has not been looked up yet.",
    "no_candidates": "No named OpenStreetMap water feature was found near the stations.",
    "not_near_stations": "Same-named features exist, but none is near the stations.",
    "ambiguous": "More than one feature fits equally well; none was chosen.",
    "no_station_coordinates": "No station has coordinates to anchor a geometry.",
    "name_too_generic": "The name is too generic to search for.",
    "unsupported_type": "No geometry source is used for this kind of water body.",
    "source_error": "The geometry source did not respond; it will be retried.",
}


# ---------------------------------------------------------------------------
# Station clusters
# ---------------------------------------------------------------------------
def station_clusters(
    db: Session,
    *,
    bbox: BBox | None = None,
    zoom: int = 5,
    state: str | None = None,
) -> dict:
    """Stations grouped on a zoom-dependent grid, computed server-side.

    At national zoom 4,000 markers are unreadable and slow; a cluster carries
    its count, its centre and the most severe latest-available status among
    its stations, so the overview still shows where concern is.
    """
    stmt = select(
        MonitoringStation.id,
        MonitoringStation.name,
        MonitoringStation.latitude,
        MonitoringStation.longitude,
        MonitoringStation.water_body_id,
        MonitoringStation.latest_observed_at,
    ).where(
        MonitoringStation.latitude.is_not(None),
        MonitoringStation.longitude.is_not(None),
        MonitoringStation.geo_quality != "missing",
    )
    if bbox:
        min_lat, min_lon, max_lat, max_lon = bbox
        stmt = stmt.where(
            MonitoringStation.latitude.between(min_lat, max_lat),
            MonitoringStation.longitude.between(min_lon, max_lon),
        )
    if state:
        stmt = stmt.join(State, State.id == MonitoringStation.state_id).where(
            or_(
                func.lower(State.slug) == state.lower(),
                func.upper(State.code) == state.upper(),
            )
        )
    rows = db.execute(stmt).all()
    body_ids = {r.water_body_id for r in rows if r.water_body_id}
    bodies = (
        {b.id: b for b in db.scalars(select(WaterBody).where(WaterBody.id.in_(body_ids)))}
        if body_ids
        else {}
    )

    def status_of(r: Row) -> str | None:
        body = bodies.get(r.water_body_id)
        return body.cached_historical_status if body else None

    if zoom >= CLUSTER_SINGLE_ZOOM:
        return {
            "zoom": zoom,
            "clustered": False,
            "items": [
                {
                    "kind": "station",
                    "id": r.id,
                    "name": r.name,
                    "latitude": r.latitude,
                    "longitude": r.longitude,
                    "water_body_slug": bodies[r.water_body_id].slug
                    if r.water_body_id in bodies
                    else None,
                    "latest_available_status": status_of(r),
                    "latest_observed_at": _iso(r.latest_observed_at),
                }
                for r in rows
            ],
        }

    cell = 360.0 / (2**zoom) / 4  # roughly 64 px cells
    grid: dict[tuple[int, int], list] = defaultdict(list)
    for r in rows:
        grid[(math.floor(r.latitude / cell), math.floor(r.longitude / cell))].append(r)

    items = []
    for members in grid.values():
        statuses = [s for s in (status_of(m) for m in members) if s]
        worst = max(statuses, key=lambda s: status_rank(s), default=None)
        if len(members) == 1:
            r = members[0]
            items.append(
                {
                    "kind": "station",
                    "id": r.id,
                    "name": r.name,
                    "latitude": r.latitude,
                    "longitude": r.longitude,
                    "latest_available_status": worst,
                    "latest_observed_at": _iso(r.latest_observed_at),
                }
            )
            continue
        items.append(
            {
                "kind": "cluster",
                "count": len(members),
                "latitude": sum(m.latitude for m in members) / len(members),
                "longitude": sum(m.longitude for m in members) / len(members),
                "worst_latest_available_status": worst,
                "status_counts": {s: statuses.count(s) for s in sorted(set(statuses))},
            }
        )
    return {"zoom": zoom, "clustered": True, "items": items}


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------
def boundaries(
    db: Session,
    *,
    level: str,
    state: str | None = None,
    bbox: BBox | None = None,
    zoom: int | None = None,
) -> dict:
    """State or district polygons, simplified for the zoom."""
    stmt = (
        select(AdminBoundary, State)
        .outerjoin(State, State.id == AdminBoundary.state_id)
        .where(AdminBoundary.level == level)
    )
    if state:
        stmt = stmt.where(
            or_(
                func.lower(State.slug) == state.lower(),
                func.upper(State.code) == state.upper(),
            )
        )
    if bbox:
        min_lat, min_lon, max_lat, max_lon = bbox
        stmt = stmt.where(
            AdminBoundary.max_lat >= min_lat,
            AdminBoundary.min_lat <= max_lat,
            AdminBoundary.max_lon >= min_lon,
            AdminBoundary.min_lon <= max_lon,
        )
    features = []
    for b, st in db.execute(stmt.order_by(AdminBoundary.name)).all():
        features.append(
            {
                "type": "Feature",
                "geometry": geo.display_geometry(json.loads(b.geojson), zoom),
                "properties": {
                    "name": b.name,
                    "level": b.level,
                    "parent": b.parent_name,
                    "state_code": st.code if st else None,
                    "state_slug": st.slug if st else None,
                    "has_water_data": st is not None,
                    "centroid": [b.centroid_lon, b.centroid_lat],
                    "bbox": [b.min_lon, b.min_lat, b.max_lon, b.max_lat],
                },
            }
        )
    src = BOUNDARY_SOURCES[level]
    return {
        "type": "FeatureCollection",
        "features": features,
        "count": len(features),
        "source": src.source,
        "licence": src.licence,
        "vintage": src.vintage,
        "disclaimer": BOUNDARY_DISCLAIMER,
    }


def boundary_summary(db: Session, level: str, state: State | None) -> dict | None:
    """Extent and provenance of one state's boundary, for detail pages."""
    if state is None:
        return None
    from app.water.boundaries import state_boundary

    b = state_boundary(db, state)
    if b is None:
        return None
    return {
        "name": b.name,
        "bbox": [b.min_lon, b.min_lat, b.max_lon, b.max_lat],
        "centroid": [b.centroid_lon, b.centroid_lat],
        "source": b.source,
        "licence": b.licence,
        "vintage": b.vintage,
        "disclaimer": BOUNDARY_DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Cities
# ---------------------------------------------------------------------------
def _city_dict(db: Session, city: City) -> dict:
    state = db.get(State, city.state_id) if city.state_id else None
    return {
        "name": city.name,
        "slug": city.slug,
        "state": state.name if state else None,
        "state_slug": state.slug if state else None,
        "aliases": city.aliases,
        "latitude": city.centroid_lat,
        "longitude": city.centroid_lon,
        "bbox": (
            [city.min_lon, city.min_lat, city.max_lon, city.max_lat]
            if city.min_lat is not None
            else None
        ),
        "definition": city.definition_note,
        "position_source": city.position_source,
    }


def list_cities(db: Session) -> list[dict]:
    """Every curated city."""
    return [_city_dict(db, c) for c in db.scalars(select(City).order_by(City.name))]


def city_detail(db: Session, slug: str) -> dict | None:
    """A city: its definition, districts, water bodies and stations."""
    city = db.scalar(select(City).where(func.lower(City.slug) == slug.lower()))
    if city is None:
        return None
    districts = (
        list(db.scalars(select(District).where(District.id.in_(city.district_ids))))
        if city.district_ids
        else []
    )
    district_ids = [d.id for d in districts]
    stations = (
        list(
            db.scalars(
                select(MonitoringStation)
                .where(MonitoringStation.district_id.in_(district_ids))
                .order_by(MonitoringStation.observation_count.desc())
            )
        )
        if district_ids
        else []
    )
    body_ids = {s.water_body_id for s in stations if s.water_body_id}
    bodies = (
        list(
            db.scalars(
                select(WaterBody)
                .where(WaterBody.id.in_(body_ids))
                .order_by(WaterBody.observation_count.desc())
            )
        )
        if body_ids
        else []
    )
    by_type: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    for b in bodies:
        by_type[str(b.water_type)] += 1
        by_status[b.cached_historical_status or "UNKNOWN"] += 1
    latest = max(
        (b.latest_observed_at for b in bodies if b.latest_observed_at), default=None
    )
    return {
        **_city_dict(db, city),
        "kind": "city",
        "districts": [{"name": d.name, "slug": d.slug} for d in districts],
        "water_body_count": len(bodies),
        "station_count": len(stations),
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "latest_available_status_counts": dict(by_status),
        "latest_observed_at": _iso(latest),
        "water_bodies": ws.summarise_bodies(db, bodies[:80]),
        "stations": ws.summarise_stations(db, stations[:80]),
        "empty_reason": (
            None
            if bodies
            else "No CPCB monitoring station in the source data is recorded in this "
            "city's districts."
        ),
    }


def bodies_near_city(
    db: Session, city: City, *, radius_km: float = 25.0, **kwargs: Any
) -> list[dict]:
    """Water bodies within ``radius_km`` of the city's extent.

    Distance is measured from the city's bounding box (0 inside it), so
    "near Mumbai" includes everything in Greater Mumbai plus a margin, not a
    circle around one arbitrary point.
    """
    if city.min_lat is None:
        return []
    centre_lat = (city.min_lat + city.max_lat) / 2
    centre_lon = (city.min_lon + city.max_lon) / 2
    half_diag = haversine_km(city.min_lat, city.min_lon, city.max_lat, city.max_lon) / 2
    candidates = ws.water_bodies_near(
        db, centre_lat, centre_lon, half_diag + radius_km, limit=500, **kwargs
    )
    box = (city.min_lon, city.min_lat, city.max_lon, city.max_lat)
    box_geom = {
        "type": "Polygon",
        "coordinates": [
            [
                [box[0], box[1]],
                [box[2], box[1]],
                [box[2], box[3]],
                [box[0], box[3]],
                [box[0], box[1]],
            ]
        ],
    }
    out = []
    for item in candidates:
        d = geo.distance_km(box_geom, item["longitude"], item["latitude"])
        if d <= radius_km:
            out.append({**item, "distance_km": round(d, 2)})
    out.sort(key=lambda i: (i["distance_km"], -i["observation_count"]))
    return out


# ---------------------------------------------------------------------------
# Data quality and availability
# ---------------------------------------------------------------------------
def data_quality(db: Session, body: WaterBody, status_detail: dict) -> dict:
    """HIGH / MODERATE / LIMITED / INSUFFICIENT from objective metadata.

    Every factor is a count or a recorded flag; the level is a fixed rule
    over them, shown alongside so a reader can check it. Freshness is kept
    out on purpose -- it has its own panel -- so old but thorough monitoring
    is not confused with thin monitoring.
    """
    first, last, months = db.execute(
        select(
            func.min(WaterQualityObservation.observed_at),
            func.max(WaterQualityObservation.observed_at),
            func.count(
                func.distinct(func.strftime("%Y-%m", WaterQualityObservation.observed_at))
            ),
        ).where(WaterQualityObservation.water_body_id == body.id)
    ).one()
    measured = set(
        db.scalars(
            select(WaterQualityObservation.parameter)
            .where(WaterQualityObservation.water_body_id == body.id)
            .distinct()
        )
    )
    core = [p for p in CORE_PARAMETERS if p in measured]
    stations = list(
        db.scalars(
            select(MonitoringStation).where(MonitoringStation.water_body_id == body.id)
        )
    )
    located = sum(1 for s in stations if s.latitude is not None and s.geo_quality == "ok")
    span_years = (
        round((last - first).days / 365.25, 1)
        if first is not None and last is not None
        else 0
    )

    factors = [
        {
            "factor": "Sampling months",
            "value": months or 0,
            "meets": (months or 0) >= 24,
            "rule": "At least 24 distinct months sampled.",
        },
        {
            "factor": "Record length",
            "value": f"{span_years} years",
            "meets": span_years >= 2,
            "rule": "At least 2 years between first and latest observation.",
        },
        {
            "factor": "Core parameters measured",
            "value": f"{len(core)} of {len(CORE_PARAMETERS)}",
            "meets": len(core) == len(CORE_PARAMETERS),
            "rule": "BOD, dissolved oxygen, pH and faecal coliform all measured.",
        },
        {
            "factor": "Stations with valid coordinates",
            "value": f"{located} of {len(stations)}",
            "meets": bool(stations) and located == len(stations),
            "rule": "Every station has coordinates that passed validation.",
        },
        {
            "factor": "Identity match confidence",
            "value": body.match_confidence,
            "meets": (body.match_confidence or 0) >= 0.8,
            "rule": "Stations resolved to this water body with confidence >= 0.8.",
        },
    ]
    failed = sum(1 for f in factors if not f["meets"])
    if not body.observation_count or not core:
        level = "INSUFFICIENT"
    elif failed == 0:
        level = "HIGH"
    elif failed == 1:
        level = "MODERATE"
    else:
        level = "LIMITED"
    return {
        "level": level,
        "factors": factors,
        "rule": (
            "INSUFFICIENT when nothing or no core parameter was measured; "
            "otherwise HIGH when every factor is met, MODERATE when one is not, "
            "LIMITED when two or more are not."
        ),
        "excludes": "Recency. See data availability.",
    }


def availability(body: WaterBody, status_detail: dict) -> dict:
    """LATEST MEASURED STATUS vs CURRENT DATA AVAILABILITY, kept apart."""
    freshness = status_detail.get("freshness", {})
    present = status_detail.get("describes_present_state", False)
    return {
        "latest_available_observation": _iso(body.latest_observed_at),
        "age_days": freshness.get("age_days"),
        "expected_cadence": freshness.get("expected_cadence_label"),
        "describes_present_state": present,
        "current_condition": (
            "Supported by recent data."
            if present
            else "Cannot be established from this dataset."
        ),
        "summary": freshness.get("summary"),
    }


def sources_panel(db: Session, body: WaterBody, detail: dict) -> list[dict]:
    """Every source behind the page, by role."""
    panel = [
        {
            "role": "Measurements",
            "name": s["name"],
            "organisation": s["organisation"],
            "url": s["url"],
            "licence": s["licence"],
            "latest": s["latest_observed_at"],
            "retrieved_at": s["retrieved_at"],
            "records": s["observation_count"],
        }
        for s in detail.get("sources", [])
    ]
    reference = detail.get("reference") or {}
    if reference.get("standard_code"):
        panel.append(
            {
                "role": "Reference standard",
                "name": reference.get("standard_name"),
                "organisation": reference.get("issuing_body"),
                "url": reference.get("source_url"),
                "licence": None,
                "latest": reference.get("effective_date"),
                "retrieved_at": None,
                "records": None,
            }
        )
    geometry = detail.get("geometry")
    if geometry:
        prov = geometry["provenance"]
        panel.append(
            {
                "role": "Geometry",
                "name": OSM_SOURCE,
                "organisation": "OpenStreetMap contributors",
                "url": "https://www.openstreetmap.org/copyright",
                "licence": prov["licence"],
                "latest": prov["version"],
                "retrieved_at": prov["retrieved_at"],
                "records": prov["feature_count"],
            }
        )
    for c in (detail.get("latest_available_status") or {}).get(
        "source_classifications", []
    ):
        panel.append(
            {
                "role": "Official classification",
                "name": c["classification_type"].replace("_", " "),
                "organisation": c["source"],
                "url": c["source_reference"],
                "licence": None,
                "latest": c["assessment_year"],
                "retrieved_at": None,
                "records": None,
            }
        )
    return panel


# ---------------------------------------------------------------------------
# Layer catalogue
# ---------------------------------------------------------------------------
BHUVAN_WMS = {
    "url": "https://bhuvan-vec1.nrsc.gov.in/bhuvan/wms",
    "layers": "basemap:waterbody_DEM",
    "format": "image/png",
    "transparent": True,
    "version": "1.1.1",
    "verified": "GetMap returned a rendered PNG on 2026-09-22.",
}


def layer_catalogue() -> dict:
    """What the map can show, grouped, with sources and attributions.

    Served by the API so layer sources, licences and the WMS endpoint are
    configured in one place, not in the frontend bundle.
    """
    return {
        "groups": [
            {
                "key": "hydrology",
                "label": "Hydrology",
                "layers": [
                    {
                        "key": "water_geometry",
                        "label": "Rivers and lakes (matched geometry)",
                        "kind": "geojson",
                        "endpoint": "/api/v1/map/geometries",
                        "default": True,
                        "min_zoom": 6,
                        "attribution": f"Geometry: {OSM_LICENCE}",
                        "note": "Only water bodies whose OSM geometry was matched "
                        "to CPCB stations. Rivers show monitored reaches only.",
                    },
                    {
                        "key": "bhuvan_waterbodies",
                        "label": "Surface water bodies (Bhuvan, raster)",
                        "kind": "wms",
                        "wms": BHUVAN_WMS,
                        "default": False,
                        "min_zoom": 8,
                        "attribution": "Water bodies: © NRSC / ISRO Bhuvan",
                        "note": "Reference raster from NRSC. Not linked to "
                        "monitoring data and not queryable (WFS is disabled).",
                    },
                ],
            },
            {
                "key": "monitoring",
                "label": "Monitoring",
                "layers": [
                    {
                        "key": "stations",
                        "label": "CPCB monitoring stations",
                        "kind": "clusters",
                        "endpoint": "/api/v1/map/station-clusters",
                        "default": True,
                        "attribution": "Stations: CPCB via National Water Data Portal",
                    },
                    {
                        "key": "water_points",
                        "label": "Water bodies without geometry (points)",
                        "kind": "points",
                        "endpoint": "/api/v1/map/water-bodies",
                        "default": True,
                        "note": "Positioned at the mean of their stations; not "
                        "a surveyed centre.",
                    },
                ],
            },
            {
                "key": "status",
                "label": "Status",
                "layers": [
                    {
                        "key": "status_overlay",
                        "label": "Latest measured status",
                        "kind": "style",
                        "default": True,
                        "note": "Colours the markers by the status as at the date "
                        "of the latest measurement. Water itself stays blue.",
                    }
                ],
            },
            {
                "key": "boundaries",
                "label": "Boundaries",
                "layers": [
                    {
                        "key": "states",
                        "label": "States and UTs",
                        "kind": "geojson",
                        "endpoint": "/api/v1/boundaries/states",
                        "default": True,
                        "attribution": "Boundaries: geoBoundaries (CC BY 2.5 IN)",
                        "note": BOUNDARY_DISCLAIMER,
                    },
                    {
                        "key": "districts",
                        "label": "Districts (selected state)",
                        "kind": "geojson",
                        "endpoint": "/api/v1/boundaries/districts",
                        "default": False,
                        "attribution": "Boundaries: geoBoundaries (ODbL)",
                        "note": BOUNDARY_DISCLAIMER,
                    },
                ],
            },
            {
                "key": "evidence",
                "label": "Evidence",
                "layers": [
                    {
                        "key": "imagery",
                        "label": "Satellite scenes (per water body)",
                        "kind": "detail_only",
                        "default": False,
                        "note": "Shown on a water body's page where a scene was "
                        "retrieved. Satellite values are uncalibrated proxies, "
                        "never laboratory measurements.",
                    }
                ],
            },
        ]
    }

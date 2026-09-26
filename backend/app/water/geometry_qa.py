"""Validation for stored geometry.

Every check answers a question a reader could reasonably ask: is this shape a
real shape, is it where it claims to be, and does it belong to the water body
it is attached to? Problems are **reported**, with the water body named.
Repairs happen only with ``--fix`` and every repair is listed, because a
silent fix hides a data problem instead of solving it.

On PostgreSQL the topology checks use PostGIS (``ST_IsValid``); on SQLite the
structural checks still run from the stored GeoJSON.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.water import MonitoringStation, WaterBody
from app.models.water_geo import WaterBodyGeometry
from app.water import geo

logger = get_logger(__name__)

# A single water body wider than this is almost certainly a bad match; the
# Ganga's full course is ~2,500 km, so the limit is generous on purpose.
MAX_EXTENT_KM = 3000.0
# India's bounding box, with a margin for the island territories.
INDIA_BBOX = (66.0, 5.0, 99.0, 38.5)
# A station further than this from its body's geometry is flagged.
MAX_STATION_DISTANCE_KM = 25.0
MIN_LINE_POINTS = 2
MIN_POLYGON_AREA_DEG2 = 1e-10


@dataclass(slots=True)
class Finding:
    """One problem with one stored geometry."""

    slug: str
    name: str
    check: str
    detail: str
    repaired: bool = False

    def to_dict(self) -> dict:
        """Serialise for the report."""
        return {
            "slug": self.slug,
            "name": self.name,
            "check": self.check,
            "detail": self.detail,
            "repaired": self.repaired,
        }


@dataclass(slots=True)
class Report:
    """Everything the QA pass found."""

    checked: int = 0
    findings: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        """Record one finding."""
        self.findings.append(finding)

    def to_dict(self) -> dict:
        """Serialise, grouped by check."""
        by_check: dict[str, int] = defaultdict(int)
        for f in self.findings:
            by_check[f.check] += 1
        return {
            "geometries_checked": self.checked,
            "findings": len(self.findings),
            "by_check": dict(sorted(by_check.items(), key=lambda kv: -kv[1])),
            "detail": [f.to_dict() for f in self.findings[:100]],
        }


def _extent_km(geometry: dict) -> float:
    from app.water.matching import haversine_km

    min_lon, min_lat, max_lon, max_lat = geo.bbox(geometry)
    return haversine_km(min_lat, min_lon, max_lat, max_lon)


def _structural_checks(
    row: WaterBodyGeometry, body: WaterBody, report: Report
) -> dict | None:
    try:
        geometry = json.loads(row.geojson)
    except (ValueError, TypeError):
        report.add(
            Finding(
                body.slug, body.name, "unparseable_geojson", "Stored GeoJSON is not JSON."
            )
        )
        return None
    if geometry.get("type") not in geo.GEOMETRY_TYPES:
        report.add(
            Finding(body.slug, body.name, "unsupported_type", str(geometry.get("type")))
        )
        return None

    points = list(geo.iter_coords(geometry))
    if len(points) < MIN_LINE_POINTS:
        report.add(
            Finding(body.slug, body.name, "degenerate", "Fewer than two vertices.")
        )
        return geometry
    if geometry["type"] in geo.POLYGON_TYPES:
        area = 0.0
        for polygon in (
            [geometry["coordinates"]]
            if geometry["type"] == "Polygon"
            else geometry["coordinates"]
        ):
            ring = polygon[0]
            area += abs(
                sum(
                    ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
                    for i in range(len(ring) - 1)
                )
                / 2
            )
        if area < MIN_POLYGON_AREA_DEG2:
            report.add(
                Finding(
                    body.slug, body.name, "zero_area_polygon", f"area={area:.3g} deg2"
                )
            )

    extent = _extent_km(geometry)
    if extent > MAX_EXTENT_KM:
        report.add(
            Finding(body.slug, body.name, "implausible_extent", f"{extent:.0f} km across")
        )
    min_lon, min_lat, max_lon, max_lat = geo.bbox(geometry)
    if not (
        INDIA_BBOX[0] <= min_lon <= INDIA_BBOX[2]
        and INDIA_BBOX[1] <= min_lat <= INDIA_BBOX[3]
        and INDIA_BBOX[0] <= max_lon <= INDIA_BBOX[2]
        and INDIA_BBOX[1] <= max_lat <= INDIA_BBOX[3]
    ):
        report.add(
            Finding(
                body.slug,
                body.name,
                "outside_india",
                f"bbox {min_lon:.2f},{min_lat:.2f},{max_lon:.2f},{max_lat:.2f}",
            )
        )
    if abs(row.min_lat - min_lat) > 0.01 or abs(row.max_lon - max_lon) > 0.01:
        report.add(
            Finding(
                body.slug,
                body.name,
                "stale_bbox_columns",
                "bbox columns disagree with geometry",
            )
        )
    return geometry


def _station_checks(
    db: Session, row: WaterBodyGeometry, body: WaterBody, geometry: dict, report: Report
) -> None:
    stations = db.scalars(
        select(MonitoringStation).where(
            MonitoringStation.water_body_id == body.id,
            MonitoringStation.latitude.is_not(None),
        )
    ).all()
    for station in stations:
        distance = geo.distance_km(geometry, station.longitude, station.latitude)
        if distance > MAX_STATION_DISTANCE_KM:
            report.add(
                Finding(
                    body.slug,
                    body.name,
                    "station_far_from_geometry",
                    f"{station.name}: {distance:.0f} km",
                )
            )


def _postgis_checks(
    db: Session, report: Report, readable: list[int], *, repair: bool
) -> None:
    """Topology checks, over the geometries the structural pass could read.

    ``readable`` matters: ``ST_GeomFromGeoJSON`` raises on text it cannot
    parse, and a row like that would abort the whole check. Those rows are
    already reported as ``unparseable_geojson``.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql" or not readable:
        return
    # The check is on the stored GeoJSON, which is the shape as retrieved and
    # is never rewritten. The derived geom column is made valid when it is
    # derived (see db/transfer.py), so a flaw in the source stays reported
    # while spatial queries still work.
    invalid = db.execute(
        text(
            """
            SELECT w.slug,
                   w.name,
                   ST_IsValidReason(ST_GeomFromGeoJSON(g.geojson)) AS reason
              FROM water_body_geometries g
              JOIN water_bodies w ON w.id = g.water_body_id
             WHERE g.id = ANY(:readable)
               AND NOT ST_IsValid(ST_GeomFromGeoJSON(g.geojson))
            """
        ),
        {"readable": readable},
    ).all()
    for slug, name, reason in invalid:
        report.add(
            Finding(
                slug,
                name,
                "invalid_source_geometry",
                f"{reason} (the derived geometry column is repaired with "
                "ST_MakeValid; the stored GeoJSON is left as retrieved)",
                repaired=False,
            )
        )

    unusable = db.execute(
        text(
            "SELECT COUNT(*) FROM water_body_geometries "
            "WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)"
        )
    ).scalar_one()
    if unusable:
        report.add(
            Finding(
                "-",
                f"{unusable} derived geometries",
                "invalid_geometry",
                "the derived column is invalid; run 'db sync-geometry'",
                repaired=repair,
            )
        )
        if repair:
            db.execute(
                text(
                    "UPDATE water_body_geometries SET geom = ST_MakeValid(geom) "
                    "WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)"
                )
            )
            db.commit()
            logger.info("geometry_repaired", extra={"count": unusable})

    wrong_srid = db.execute(
        text(
            "SELECT COUNT(*) FROM water_body_geometries "
            "WHERE geom IS NOT NULL AND ST_SRID(geom) <> 4326"
        )
    ).scalar_one()
    if wrong_srid:
        report.add(
            Finding("-", "-", "wrong_srid", f"{wrong_srid} geometries not in EPSG:4326")
        )


def run_checks(db: Session, *, repair: bool = False) -> dict:
    """Validate every stored geometry and return a report."""
    report = Report()
    rows = db.execute(
        select(WaterBodyGeometry, WaterBody).join(
            WaterBody, WaterBody.id == WaterBodyGeometry.water_body_id
        )
    ).all()
    seen_ids: dict[str, str] = {}
    readable: list[int] = []
    for row, body in rows:
        report.checked += 1
        geometry = _structural_checks(row, body, report)
        if geometry is None:
            continue
        readable.append(row.id)
        _station_checks(db, row, body, geometry, report)
        for element in row.source_ids or []:
            if element in seen_ids and seen_ids[element] != body.slug:
                report.add(
                    Finding(
                        body.slug,
                        body.name,
                        "duplicate_source_element",
                        f"{element} also used by {seen_ids[element]}",
                    )
                )
            seen_ids[element] = body.slug
    _postgis_checks(db, report, readable, repair=repair)
    logger.info(
        "geometry_qa", extra={"checked": report.checked, "findings": len(report.findings)}
    )
    return report.to_dict()

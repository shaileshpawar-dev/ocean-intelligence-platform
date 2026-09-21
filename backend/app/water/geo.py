"""Small, dependency-free GeoJSON geometry helpers.

The platform needs a handful of planar operations -- bounding boxes,
point-in-polygon, centroids, point-to-line distance, clipping a line to a
box -- over a few thousand features. Pulling GEOS in through shapely for that
would add a native dependency to every image; these functions are short,
tested, and good enough at the scales involved (district assignment, and
station-to-river distances of up to a few kilometres).

When the store moves to PostGIS, each of these has a direct equivalent
(``ST_Envelope``, ``ST_Contains``, ``ST_PointOnSurface``, ``ST_Distance`` on
geography, ``ST_ClipByBox2D``) and this module becomes the fallback for SQLite
only. See docs/POSTGIS_MIGRATION.md.
"""

from __future__ import annotations

import math
from collections.abc import Iterator

from app.water.matching import haversine_km

Coord = tuple[float, float]  # (lon, lat), GeoJSON order
BBox = tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)

POINT_TYPES = {"Point", "MultiPoint"}
LINE_TYPES = {"LineString", "MultiLineString"}
POLYGON_TYPES = {"Polygon", "MultiPolygon"}
GEOMETRY_TYPES = POINT_TYPES | LINE_TYPES | POLYGON_TYPES


def iter_coords(geometry: dict) -> Iterator[Coord]:
    """Every vertex, whatever the geometry type."""
    kind = geometry["type"]
    coords = geometry["coordinates"]
    if kind == "Point":
        yield tuple(coords[:2])
    elif kind in ("MultiPoint", "LineString"):
        for c in coords:
            yield tuple(c[:2])
    elif kind in ("MultiLineString", "Polygon"):
        for part in coords:
            for c in part:
                yield tuple(c[:2])
    elif kind == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                for c in ring:
                    yield tuple(c[:2])
    elif kind == "GeometryCollection":
        for g in geometry["geometries"]:
            yield from iter_coords(g)


def bbox(geometry: dict) -> BBox:
    """Bounding box as (min_lon, min_lat, max_lon, max_lat)."""
    xs, ys = zip(*iter_coords(geometry), strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def bbox_intersects(a: BBox, b: BBox) -> bool:
    """Whether two boxes overlap (touching counts)."""
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _polygons(geometry: dict) -> list[list[list[Coord]]]:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    return []


def _in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def contains_point(geometry: dict, lon: float, lat: float) -> bool:
    """Point-in-polygon with holes (even-odd rule)."""
    for poly in _polygons(geometry):
        if not poly or not _in_ring(lon, lat, poly[0]):
            continue
        if not any(_in_ring(lon, lat, hole) for hole in poly[1:]):
            return True
    return False


def _ring_area_centroid(ring: list) -> tuple[float, float, float]:
    area = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[i + 1][0], ring[i + 1][1]
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area /= 2.0
    if area == 0:
        return 0.0, ring[0][0], ring[0][1]
    return area, cx / (6 * area), cy / (6 * area)


def centroid(geometry: dict) -> Coord:
    """Area-weighted centroid for polygons, vertex mean otherwise.

    For a MultiPolygon the centroid of the largest part is returned, so an
    archipelago state does not get a centroid in open sea.
    """
    polys = _polygons(geometry)
    if polys:
        best = max(
            (_ring_area_centroid(p[0]) for p in polys if p),
            key=lambda t: abs(t[0]),
        )
        return best[1], best[2]
    pts = list(iter_coords(geometry))
    return (
        sum(p[0] for p in pts) / len(pts),
        sum(p[1] for p in pts) / len(pts),
    )


def round_geometry(geometry: dict, places: int = 4) -> dict:
    """Round coordinates (4 places is ~11 m), dropping consecutive repeats."""

    def ring(points: list) -> list:
        out: list = []
        for c in points:
            r = [round(c[0], places), round(c[1], places)]
            if not out or out[-1] != r:
                out.append(r)
        return out

    kind = geometry["type"]
    c = geometry["coordinates"]
    if kind == "Point":
        coords = [round(c[0], places), round(c[1], places)]
    elif kind in ("LineString", "MultiPoint"):
        coords = ring(c)
    elif kind in ("MultiLineString", "Polygon"):
        coords = [ring(p) for p in c]
    elif kind == "MultiPolygon":
        coords = [[ring(r) for r in p] for p in c]
    else:
        return geometry
    return {"type": kind, "coordinates": coords}


def _lines(geometry: dict) -> list[list]:
    kind = geometry["type"]
    if kind == "LineString":
        return [geometry["coordinates"]]
    if kind == "MultiLineString":
        return geometry["coordinates"]
    if kind == "Polygon":
        return geometry["coordinates"]
    if kind == "MultiPolygon":
        return [ring for poly in geometry["coordinates"] for ring in poly]
    return []


def _segment_distance_km(lon: float, lat: float, a: list, b: list) -> float:
    # Project onto the segment in a local equirectangular frame -- accurate to
    # well under 1% at the few-kilometre distances this is used for.
    k = math.cos(math.radians(lat))
    ax, ay = (a[0] - lon) * k, a[1] - lat
    bx, by = (b[0] - lon) * k, b[1] - lat
    dx, dy = bx - ax, by - ay
    seg = dx * dx + dy * dy
    t = 0.0 if seg == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg))
    px, py = ax + t * dx, ay + t * dy
    return haversine_km(lat, lon, lat + py, lon + px / k if k else lon)


def distance_km(geometry: dict, lon: float, lat: float) -> float:
    """Distance from a point to a geometry; 0 inside a polygon."""
    if geometry["type"] in POLYGON_TYPES and contains_point(geometry, lon, lat):
        return 0.0
    if geometry["type"] in POINT_TYPES:
        return min(haversine_km(lat, lon, c[1], c[0]) for c in iter_coords(geometry))
    best = math.inf
    for line in _lines(geometry):
        for i in range(len(line) - 1):
            best = min(best, _segment_distance_km(lon, lat, line[i], line[i + 1]))
        if len(line) == 1:
            best = min(best, haversine_km(lat, lon, line[0][1], line[0][0]))
    return best


def _clip_line(line: list, box: BBox) -> list[list]:
    """Keep the runs of vertices inside ``box`` (vertex-level clipping)."""
    parts: list[list] = []
    run: list = []
    for c in line:
        if box[0] <= c[0] <= box[2] and box[1] <= c[1] <= box[3]:
            run.append(c)
        elif run:
            if len(run) > 1:
                parts.append(run)
            run = []
    if len(run) > 1:
        parts.append(run)
    return parts


def clip_lines(geometry: dict, box: BBox) -> dict | None:
    """Clip a (Multi)LineString to a box. ``None`` when nothing survives.

    Vertex-level: segments crossing the box edge are cut at the last inside
    vertex. OSM river ways are densely noded, so the loss is metres.
    """
    parts: list[list] = []
    for line in _lines(geometry):
        parts.extend(_clip_line(line, box))
    if not parts:
        return None
    if len(parts) == 1:
        return {"type": "LineString", "coordinates": parts[0]}
    return {"type": "MultiLineString", "coordinates": parts}


def expand_bbox(box: BBox, km: float) -> BBox:
    """Grow a box by ``km`` on every side."""
    dlat = km / 111.0
    dlon = km / (111.0 * max(math.cos(math.radians((box[1] + box[3]) / 2)), 0.1))
    return box[0] - dlon, box[1] - dlat, box[2] + dlon, box[3] + dlat


def merge_boxes(boxes: list[BBox]) -> list[BBox]:
    """Union overlapping boxes until none overlap.

    Station windows along a river overlap; clipping a way to each of them
    separately would emit the shared stretch twice.
    """
    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        out: list[BBox] = []
        for box in merged:
            for i, other in enumerate(out):
                if bbox_intersects(box, other):
                    out[i] = (
                        min(box[0], other[0]),
                        min(box[1], other[1]),
                        max(box[2], other[2]),
                        max(box[3], other[3]),
                    )
                    changed = True
                    break
            else:
                out.append(box)
        merged = out
    return merged


def _thin(points: list, tolerance: float, closed: bool) -> list:
    if len(points) <= 2:
        return points
    kept = [points[0]]
    for p in points[1:-1]:
        last = kept[-1]
        if abs(p[0] - last[0]) > tolerance or abs(p[1] - last[1]) > tolerance:
            kept.append(p)
    kept.append(points[-1])
    if closed and len(kept) < 4:
        return points  # never collapse a ring below a valid polygon
    return kept


def simplify(geometry: dict, tolerance: float) -> dict:
    """Radial-distance thinning for display at a given zoom.

    Drops vertices closer than ``tolerance`` degrees to the previous kept
    one. Endpoints and ring closure are always kept, so lines stay connected
    and polygons stay valid. Display only -- stored geometry is untouched.
    """
    if tolerance <= 0:
        return geometry
    kind = geometry["type"]
    c = geometry["coordinates"]
    if kind == "LineString":
        coords = _thin(c, tolerance, False)
    elif kind == "MultiLineString":
        coords = [_thin(line, tolerance, False) for line in c]
    elif kind == "Polygon":
        coords = [_thin(ring, tolerance, True) for ring in c]
    elif kind == "MultiPolygon":
        coords = [[_thin(ring, tolerance, True) for ring in poly] for poly in c]
    else:
        return geometry
    return {"type": kind, "coordinates": coords}


def tolerance_for_zoom(zoom: int | None) -> float:
    """About one screen pixel at ``zoom`` in degrees (0 when unknown)."""
    if zoom is None:
        return 0.0
    return 360.0 / (256 * 2 ** max(0, min(zoom, 22)))


def display_geometry(geometry: dict, zoom: int | None) -> dict:
    """Simplify and round a geometry for display at ``zoom``.

    Precision follows the pixel size: 3 decimals (~110 m) is finer than a
    pixel at national zoom, 5 (~1 m) is enough at street level.
    """
    if zoom is None:
        return geometry
    places = 3 if zoom <= 7 else 4 if zoom <= 11 else 5
    return round_geometry(simplify(geometry, tolerance_for_zoom(zoom)), places)

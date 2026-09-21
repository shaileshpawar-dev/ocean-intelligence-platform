"""Real water-body geometry from OpenStreetMap, matched to CPCB stations.

What this does
--------------
For one water body it asks the Overpass API for features that (a) carry a
name matching the body's canonical name or an alias, (b) are water features of
the right kind, and (c) lie within a small window around one of the body's
monitoring stations. It then accepts the geometry only if the stations are
actually on or near it, and records how it decided.

What it refuses to do
---------------------
* Draw a shape nobody published. No buffers around points, no convex hulls.
* Guess between two candidates. If a station sits equally close to two
  same-named features, the body is marked ``ambiguous`` and gets no geometry.
* Accept a same-named feature that is not where the stations are.

Rivers are fetched as *monitored reaches*: the windows around the stations,
not the whole river. A national river would otherwise be a multi-megabyte
query and a multi-megabyte map feature, and the part far from any station says
nothing this platform can support with measurements.

Provenance recorded on every stored geometry: source, OSM element ids, licence
(ODbL), retrieval time, the OSM database timestamp Overpass reported (as the
version), the match method and the per-station distances behind the
confidence.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import WaterBodyType
from app.models.water import MonitoringStation, WaterBody
from app.models.water_geo import WaterBodyGeometry
from app.water import geo
from app.water.matching import CANONICAL_SPELLINGS, TYPE_KEYWORDS, normalise_name

logger = get_logger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Public mirrors (kumi.systems, mail.ru, private.coffee) were unreachable when
# this was written (2026-09-22), so the main instance is retried instead.
OVERPASS_ATTEMPTS = 2
RETRY_PAUSE_SECONDS = 10.0
OSM_SOURCE = "OpenStreetMap (Overpass API)"
OSM_LICENCE = "ODbL 1.0 — © OpenStreetMap contributors"
USER_AGENT = "OceanAI-IndiaWaterIntelligence/2.0 (geometry matching; low volume)"

_TYPE_WORDS = {k.upper() for k, _ in TYPE_KEYWORDS} | {
    "NALLAH",
    "NADI",
    "TALAO",
    "TALAV",
    "TALAVA",
    "SAGAR",
    "LAKE",
    "RIVER",
    "OF",
    "THE",
}
_NAME_SUFFIX = (
    r"( (river|nadi|nala|nalla|nallah|lake|talao|talav|talab|tank|creek|canal|"
    r"dam|reservoir|jheel|sarovar|sagar|tal|kund|kere|cheruvu|pond|drain))*"
)


@dataclass(frozen=True, slots=True)
class MatchPolicy:
    """Distances that decide acceptance, per kind of water body (km)."""

    window_km: float
    """Search window around each station."""

    on_km: float
    """A station this close is ``on_geometry``."""

    accept_km: float
    """Beyond this no station supports the feature; it is rejected."""

    kind: str
    """``line``, ``polygon`` or ``both``."""


POLICIES: dict[str, MatchPolicy] = {
    "line": MatchPolicy(window_km=6.0, on_km=0.5, accept_km=2.0, kind="line"),
    "polygon": MatchPolicy(window_km=2.5, on_km=0.2, accept_km=1.0, kind="polygon"),
    "both": MatchPolicy(window_km=4.0, on_km=0.5, accept_km=2.0, kind="both"),
}

TYPE_POLICY: dict[str, str] = {
    WaterBodyType.RIVER: "line",
    WaterBodyType.RIVER_STRETCH: "line",
    WaterBodyType.CANAL: "line",
    WaterBodyType.DRAIN: "line",
    WaterBodyType.LAKE: "polygon",
    WaterBodyType.POND: "polygon",
    WaterBodyType.RESERVOIR: "polygon",
    WaterBodyType.CREEK: "both",
    WaterBodyType.ESTUARY: "both",
}


@dataclass(slots=True)
class GeometryOutcome:
    """What happened for one water body."""

    status: str
    """``matched``, ``no_candidates``, ``not_near_stations``, ``ambiguous``,
    ``no_station_coordinates``, ``name_too_generic``, ``unsupported_type`` or
    ``source_error``."""

    detail: str = ""
    geometry: dict | None = None
    confidence: str | None = None
    source_ids: list[str] = field(default_factory=list)
    station_distances_km: dict[int, float] = field(default_factory=dict)


# Names OSM uses for rivers whose CPCB spelling differs: the canonical
# spellings the identity layer settled on, inverted, plus English exonyms that
# appear in OSM ``name`` / ``name:en`` tags.
SEARCH_VARIANTS: dict[str, tuple[str, ...]] = {
    "GANGA": ("GANGES",),
    "SATLUJ": ("SUTLEJ",),
    "YAMUNA": ("JAMUNA",),
    "JHELUM": ("JEHLUM",),
    "SONE": ("SON",),
    "KOSI": ("KOSHI",),
    "GHAGHRA": ("GHAGRA", "GHAGHARA"),
    "GOMTI": ("GOMATI",),
    "TEESTA": ("TISTA",),
    "SUBARNAREKHA": ("SUBARNREKHA", "SUVARNAREKHA"),
}
for _variant, _canonical in CANONICAL_SPELLINGS.items():
    SEARCH_VARIANTS[_canonical] = (*SEARCH_VARIANTS.get(_canonical, ()), _variant)

# OSM keys that carry a name a CPCB label might correspond to. In India the
# plain ``name`` is often in a local script, with the Latin form elsewhere.
NAME_KEYS = "^(name|name:en|alt_name|official_name|int_name|old_name)$"

_QUALIFIER = re.compile(r"\([^)]*\)")
_REGEX_SPECIAL = re.compile(r"([.^$*+?()\[\]{}|\\])")


def name_cores(body: WaterBody) -> list[str]:
    """Distinctive name tokens, e.g. ``MITHI`` for ``Mithi River``.

    Parenthesised qualifiers the platform adds to tell same-named bodies
    apart -- ``Ganga River (Bihar)`` -- are not part of the name in OSM.
    """
    cores: list[str] = []
    for name in [body.name, *(body.aliases or [])]:
        words = normalise_name(_QUALIFIER.sub(" ", name or "")).split()
        # Two readings: every type word removed ("MITHI"), and only the final
        # one removed. SAGAR is a type word in "RANI SAGAR" but part of the
        # proper name in "Hussain Sagar Lake".
        stripped = " ".join(t for t in words if t not in _TYPE_WORDS)
        last_dropped = words[:-1] if words and words[-1] in _TYPE_WORDS else words
        for core in (stripped, " ".join(last_dropped)):
            for candidate in (core, *SEARCH_VARIANTS.get(core, ())):
                if len(candidate) >= 3 and candidate not in cores:
                    cores.append(candidate)
    return cores


def _escape(text: str) -> str:
    # Overpass regexes are POSIX ERE: escape metacharacters only. Python's
    # re.escape also escapes spaces, which ERE does not define.
    return _REGEX_SPECIAL.sub(r"\\\1", text)


def _name_regex(cores: list[str]) -> str:
    alternatives = "|".join(_escape(c.lower()) for c in cores)
    return f"^({alternatives}){_NAME_SUFFIX}$"


def build_query(policy: MatchPolicy, cores: list[str], windows: list[geo.BBox]) -> str:
    """Overpass QL for named water features inside any station window."""
    regex = _name_regex(cores).replace('"', '\\"')
    clauses: list[str] = []
    for w in windows:
        box = f"({w[1]:.5f},{w[0]:.5f},{w[3]:.5f},{w[2]:.5f})"
        if policy.kind in ("line", "both"):
            clauses.append(
                f'way["waterway"~"^(river|stream|canal|drain|tidal_channel)$"]'
                f'[~"{NAME_KEYS}"~"{regex}",i]{box};'
            )
        if policy.kind in ("polygon", "both"):
            clauses.append(f'way["natural"="water"][~"{NAME_KEYS}"~"{regex}",i]{box};')
            clauses.append(
                f'relation["natural"="water"][~"{NAME_KEYS}"~"{regex}",i]{box};'
            )
            clauses.append(
                f'way["landuse"="reservoir"][~"{NAME_KEYS}"~"{regex}",i]{box};'
            )
    return f"[out:json][timeout:50];({''.join(clauses)});out tags geom;"


REQUEST_DEADLINE_SECONDS = 75.0
WINDOWS_PER_QUERY = 8
CHUNK_PAUSE_SECONDS = 2.0


class OverpassDeadlineError(httpx.HTTPError):
    """The server kept the connection open past the deadline."""


def _post_with_deadline(url: str, query: str) -> dict:
    # httpx timeouts are per network operation; a server trickling bytes can
    # hold a request open indefinitely. The deadline bounds the whole call.
    started = time.monotonic()
    chunks: list[bytes] = []
    with httpx.stream(
        "POST",
        url,
        data={"data": query},
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(30.0, connect=10.0),
    ) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            chunks.append(chunk)
            if time.monotonic() - started > REQUEST_DEADLINE_SECONDS:
                raise OverpassDeadlineError(
                    f"no complete response within {REQUEST_DEADLINE_SECONDS:g}s"
                )
    return json.loads(b"".join(chunks))


def overpass_fetch(query: str) -> dict:
    """POST a query to the public Overpass API.

    The public instance returns 429/504 under load. Each attempt is bounded
    by :data:`REQUEST_DEADLINE_SECONDS`; after the last one the body is
    recorded as ``source_error`` and retried on a later prefetch.
    """
    last: Exception | None = None
    for attempt in range(OVERPASS_ATTEMPTS):
        if attempt:
            time.sleep(RETRY_PAUSE_SECONDS)
        try:
            return _post_with_deadline(OVERPASS_URL, query)
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
    assert last is not None
    raise last


def _chain_rings(ways: list[list[list[float]]]) -> list[list[list[float]]]:
    """Join open way segments end-to-end into closed rings."""
    pending = [list(w) for w in ways if len(w) >= 2]
    rings: list[list[list[float]]] = []
    while pending:
        ring = pending.pop(0)
        progressed = True
        while ring[0] != ring[-1] and progressed:
            progressed = False
            for i, w in enumerate(pending):
                if w[0] == ring[-1]:
                    ring.extend(w[1:])
                elif w[-1] == ring[-1]:
                    ring.extend(reversed(w[:-1]))
                elif w[-1] == ring[0]:
                    ring[:0] = w[:-1]
                elif w[0] == ring[0]:
                    ring[:0] = list(reversed(w[1:]))
                else:
                    continue
                pending.pop(i)
                progressed = True
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def element_geometry(element: dict) -> dict | None:
    """GeoJSON for one Overpass element returned with ``out geom``."""
    if element["type"] == "way":
        pts = [[p["lon"], p["lat"]] for p in element.get("geometry", []) if p]
        if len(pts) < 2:
            return None
        tags = element.get("tags", {})
        closed = pts[0] == pts[-1] and len(pts) >= 4
        if closed and ("natural" in tags or "landuse" in tags):
            return {"type": "Polygon", "coordinates": [pts]}
        return {"type": "LineString", "coordinates": pts}
    if element["type"] == "relation":
        outers, inners = [], []
        for m in element.get("members", []):
            if m.get("type") != "way" or not m.get("geometry"):
                continue
            pts = [[p["lon"], p["lat"]] for p in m["geometry"] if p]
            (inners if m.get("role") == "inner" else outers).append(pts)
        outer_rings = _chain_rings(outers)
        if not outer_rings:
            return None
        inner_rings = _chain_rings(inners)
        polys = []
        for ring in outer_rings:
            shell = {"type": "Polygon", "coordinates": [ring]}
            holes = [h for h in inner_rings if geo.contains_point(shell, *h[0])]
            polys.append([ring, *holes])
        if len(polys) == 1:
            return {"type": "Polygon", "coordinates": polys[0]}
        return {"type": "MultiPolygon", "coordinates": polys}
    return None


def combine(parts: list[dict]) -> dict:
    """Merge line parts into a MultiLineString and polygons into a MultiPolygon.

    A body that is both (a creek mapped as a channel and as open water) keeps
    its polygons: the area is the more faithful representation.
    """
    polys = [p for p in parts if p["type"] in geo.POLYGON_TYPES]
    if polys:
        coords = []
        for p in polys:
            coords.extend(
                [p["coordinates"]] if p["type"] == "Polygon" else p["coordinates"]
            )
        if len(coords) == 1:
            return {"type": "Polygon", "coordinates": coords[0]}
        return {"type": "MultiPolygon", "coordinates": coords}
    lines = []
    for p in parts:
        lines.extend(
            [p["coordinates"]] if p["type"] == "LineString" else p["coordinates"]
        )
    if len(lines) == 1:
        return {"type": "LineString", "coordinates": lines[0]}
    return {"type": "MultiLineString", "coordinates": lines}


def match_geometry(
    body: WaterBody,
    stations: list[MonitoringStation],
    *,
    fetch: Callable[[str], dict] = overpass_fetch,
) -> GeometryOutcome:
    """Find, test and assemble geometry for ``body``. Does not write."""
    policy_key = TYPE_POLICY.get(body.water_type)
    if policy_key is None:
        return GeometryOutcome(
            "unsupported_type",
            f"No geometry source is used for {body.water_type} water bodies.",
        )
    policy = POLICIES[policy_key]
    located = [s for s in stations if s.latitude is not None and s.longitude is not None]
    if not located:
        return GeometryOutcome(
            "no_station_coordinates",
            "No station has coordinates, so no geometry can be tied to the data.",
        )
    cores = name_cores(body)
    if not cores:
        return GeometryOutcome(
            "name_too_generic",
            "The name has no distinctive part to search for once type words are removed.",
        )

    windows = geo.merge_boxes(
        [
            geo.expand_bbox(
                (s.longitude, s.latitude, s.longitude, s.latitude), policy.window_km
            )
            for s in located
        ]
    )
    # A national river can have 40+ station windows; one union query over all
    # of them is heavy for a shared server, so windows go in small chunks.
    payload: dict = {"elements": []}
    try:
        for i in range(0, len(windows), WINDOWS_PER_QUERY):
            if i:
                time.sleep(CHUNK_PAUSE_SECONDS)
            part = fetch(build_query(policy, cores, windows[i : i + WINDOWS_PER_QUERY]))
            payload["elements"].extend(part.get("elements", []))
            if "osm3s" in part:
                payload["osm3s"] = part["osm3s"]
    except (httpx.HTTPError, ValueError) as exc:
        return GeometryOutcome("source_error", f"Overpass request failed: {exc}")

    features: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for element in payload.get("elements", []):
        key = f"{element['type']}/{element['id']}"
        if key in seen:
            continue
        seen.add(key)
        g = element_geometry(element)
        if g is not None:
            features.append((key, g))
    if not features:
        return GeometryOutcome(
            "no_candidates",
            f"No OpenStreetMap water feature named {' / '.join(cores).title()} "
            "near the stations.",
        )

    # Rivers: keep only the windows around stations (monitored reaches).
    if policy.kind == "line":
        clip_boxes = windows
        clipped: list[tuple[str, dict]] = []
        for key, g in features:
            pieces = [p for w in clip_boxes if (p := geo.clip_lines(g, w)) is not None]
            if pieces:
                clipped.append((key, combine(pieces)))
        features = clipped

    chosen: dict[str, dict] = {}
    distances: dict[int, float] = {}
    for s in located:
        ranked = sorted(
            (
                (geo.distance_km(g, s.longitude, s.latitude), key, g)
                for key, g in features
            ),
            key=lambda t: t[0],
        )
        if not ranked:
            continue
        best = ranked[0]
        if (
            policy.kind != "line"
            and len(ranked) > 1
            and best[0] > 0
            and ranked[1][0] - best[0] < 0.1
            and ranked[1][0] <= policy.accept_km
        ):
            return GeometryOutcome(
                "ambiguous",
                f"Station {s.name} is equally close to {best[1]} and {ranked[1][1]}; "
                "not guessing between them.",
            )
        distances[s.id] = round(best[0], 3)
        if best[0] <= policy.accept_km:
            if policy.kind == "line":
                for d, key, g in ranked:
                    if d <= policy.accept_km:
                        chosen[key] = g
            else:
                chosen[best[1]] = best[2]

    if not chosen:
        nearest = min(distances.values()) if distances else None
        return GeometryOutcome(
            "not_near_stations",
            "Same-named features exist but none is within "
            f"{policy.accept_km:g} km of a station"
            + (f" (nearest {nearest:.1f} km)." if nearest is not None else "."),
            station_distances_km=distances,
        )

    supported = [d for d in distances.values() if d <= policy.accept_km]
    confidence = (
        "high"
        if len(supported) == len(distances) and max(supported) <= policy.on_km
        else "medium"
    )
    geometry = geo.round_geometry(combine(list(chosen.values())), 5)
    return GeometryOutcome(
        "matched",
        f"{len(chosen)} OSM element(s); {len(supported)} of {len(distances)} "
        f"station(s) within {policy.accept_km:g} km.",
        geometry=geometry,
        confidence=confidence,
        source_ids=sorted(chosen),
        station_distances_km=distances,
    )


def relationship_for(distance_km: float | None, policy: MatchPolicy) -> str:
    """How a station relates to its body's geometry."""
    if distance_km is None:
        return "name_match"
    if distance_km == 0.0 and policy.kind != "line":
        return "within_geometry"
    if distance_km <= policy.on_km:
        return "on_geometry"
    if distance_km <= policy.accept_km:
        return "near_geometry"
    return "name_match_only"


def fetch_and_store(
    db: Session,
    body: WaterBody,
    *,
    fetch: Callable[[str], dict] = overpass_fetch,
    osm_version: str | None = None,
) -> GeometryOutcome:
    """Match geometry for ``body`` and persist the result with provenance."""
    stations = list(
        db.scalars(
            select(MonitoringStation).where(MonitoringStation.water_body_id == body.id)
        )
    )
    version_box: dict[str, str | None] = {"v": osm_version}

    def recording_fetch(query: str) -> dict:
        payload = fetch(query)
        version_box["v"] = (payload.get("osm3s") or {}).get("timestamp_osm_base")
        return payload

    outcome = match_geometry(body, stations, fetch=recording_fetch)
    body.geometry_status = outcome.status

    existing = db.scalar(
        select(WaterBodyGeometry).where(
            WaterBodyGeometry.water_body_id == body.id,
            WaterBodyGeometry.source == OSM_SOURCE,
        )
    )
    if outcome.geometry is None:
        if existing is not None and outcome.status != "source_error":
            db.delete(existing)
        db.commit()
        return outcome

    policy = POLICIES[TYPE_POLICY[body.water_type]]
    min_lon, min_lat, max_lon, max_lat = geo.bbox(outcome.geometry)
    row = existing or WaterBodyGeometry(water_body_id=body.id, source=OSM_SOURCE)
    row.geometry_type = outcome.geometry["type"]
    row.geojson = json.dumps(outcome.geometry, separators=(",", ":"))
    row.min_lat, row.min_lon, row.max_lat, row.max_lon = (
        min_lat,
        min_lon,
        max_lat,
        max_lon,
    )
    row.source_ids = outcome.source_ids
    row.source_licence = OSM_LICENCE
    row.retrieved_at = datetime.now(UTC)
    row.version = version_box["v"]
    row.confidence = outcome.confidence or "medium"
    row.match_method = "name_and_station_proximity"
    row.match_notes = [
        outcome.detail,
        f"Window {policy.window_km:g} km per station; accepted within "
        f"{policy.accept_km:g} km.",
    ]
    row.feature_count = len(outcome.source_ids)
    row.clipped = policy.kind == "line"
    db.add(row)

    for s in stations:
        d = outcome.station_distances_km.get(s.id)
        s.geometry_distance_m = round(d * 1000) if d is not None else None
        s.relationship_type = relationship_for(d, policy)
    db.commit()
    return outcome


def prefetch(
    db: Session,
    *,
    state_code: str | None = None,
    slugs: list[str] | None = None,
    water_types: list[str] | None = None,
    limit: int | None = None,
    retry_statuses: tuple[str, ...] = ("not_attempted", "source_error"),
    pause_seconds: float = 6.0,
    error_backoff_seconds: float = 30.0,
    fetch: Callable[[str], dict] = overpass_fetch,
) -> dict:
    """Fetch geometry for many bodies politely (one request at a time)."""
    from app.models.water import State

    types = [t for t in (water_types or list(TYPE_POLICY)) if t in TYPE_POLICY]
    query = select(WaterBody).where(
        WaterBody.water_type.in_(types),
        WaterBody.geometry_status.in_(retry_statuses),
    )
    if slugs:
        query = select(WaterBody).where(WaterBody.slug.in_(slugs))
    elif state_code:
        query = query.join(State, State.id == WaterBody.state_id).where(
            State.code == state_code.upper()
        )
    query = query.order_by(WaterBody.observation_count.desc())
    if limit:
        query = query.limit(limit)

    counts: dict[str, int] = {}
    for i, body in enumerate(db.scalars(query).all()):
        if i:
            time.sleep(pause_seconds)
        outcome = fetch_and_store(db, body, fetch=fetch)
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
        if outcome.status == "source_error":
            # Usually 429/504 from the shared public instance: back off
            # rather than keep adding load.
            time.sleep(error_backoff_seconds)
        logger.info(
            "water_geometry",
            extra={"slug": body.slug, "status": outcome.status, "detail": outcome.detail},
        )
    return counts

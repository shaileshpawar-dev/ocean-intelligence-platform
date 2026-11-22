"""Match bulk OSM water features to water bodies, offline.

Input is the newline-delimited file written by :mod:`app.water.osm_extract`
(one named water feature per line). Nothing here touches the network, so the
whole country can be matched in one run and a deployment never depends on a
public API.

The pipeline, per water body:

    name cores  ->  candidate features (name index)
                ->  proximity test against its stations
                ->  connectivity (lines) / containment (areas)
                ->  merge
                ->  validate
                ->  store with provenance

Two rules carried over from Phase 2, because they are what keep the result
honest:

* a feature is only accepted when a monitoring station is on or near it, so
  a same-named river elsewhere in India is never adopted;
* when two features fit equally well and nothing separates them, the body is
  recorded as ``ambiguous`` and gets no geometry.

Lines additionally use **connectivity**: starting from the segments near
stations, the course is followed through segments that share an endpoint
(within :data:`JOIN_TOLERANCE_DEG`). That extends a river along its real
course without ever joining a disconnected river of the same name.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import WaterBodyType
from app.models.water import MonitoringStation, WaterBody
from app.models.water_geo import WaterBodyGeometry
from app.water import geo
from app.water.geometry import (
    POLICIES,
    TYPE_POLICY,
    MatchPolicy,
    name_cores,
    name_matches,
)
from app.water.matching import normalise_name

logger = get_logger(__name__)

SOURCE = "OpenStreetMap bulk extract (Geofabrik)"
LICENCE = "ODbL 1.0 — © OpenStreetMap contributors"
MATCH_METHOD = "bulk_name_and_station_proximity"

# Two line ends closer than this are treated as the same point (~11 m).
JOIN_TOLERANCE_DEG = 1e-4
# A river segment this close to a station anchors its component.
ANCHOR_KM = 2.0
# Candidate features are read only within this distance of a station, which
# keeps the name index cheap for very common names.
CANDIDATE_WINDOW_KM = 60.0
MAX_ELEMENT_IDS = 200

# Which OSM ``waterway`` values may back which water-body type. Without this,
# "Krishna Canal" and "Krishna River" both reduce to the core "KRISHNA" and
# the canal adopted the river's segments.
WATERWAY_AFFINITY: dict[str, set[str]] = {
    str(WaterBodyType.RIVER): {"river", "stream", "tidal_channel"},
    str(WaterBodyType.RIVER_STRETCH): {"river", "stream", "tidal_channel"},
    str(WaterBodyType.CANAL): {"canal"},
    str(WaterBodyType.DRAIN): {"drain", "ditch", "stream"},
    str(WaterBodyType.CREEK): {"river", "stream", "tidal_channel", "canal"},
    str(WaterBodyType.ESTUARY): {"river", "stream", "tidal_channel"},
}


@dataclass(slots=True)
class ImportOutcome:
    """What happened for one water body."""

    status: str
    detail: str = ""
    geometry: dict | None = None
    confidence: str | None = None
    source_ids: list[str] = field(default_factory=list)
    station_distances_km: dict[int, float] = field(default_factory=dict)
    feature_count: int = 0


class FeatureIndex:
    """Named water features from the extract, indexed by name token.

    The file is read once. Geometry is kept as parsed GeoJSON: an Indian
    extract holds a few hundred thousand named water features, which is a
    few hundred MB in memory -- acceptable for an offline job, and far
    cheaper than a network round trip per water body.
    """

    def __init__(self) -> None:
        """Start an empty index."""
        self.features: list[dict] = []
        self.by_name: dict[str, list[int]] = defaultdict(list)
        self.meta: dict = {}

    @classmethod
    def load(cls, path: Path) -> FeatureIndex:
        """Read an extract file into memory."""
        index = cls()
        meta_path = path.with_suffix(".meta.json")
        if meta_path.exists():
            index.meta = json.loads(meta_path.read_text(encoding="utf-8"))
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                # A feature with no coordinates cannot be matched or merged;
                # it would only surface later as an empty geometry.
                if not (record.get("geometry") or {}).get("coordinates"):
                    continue
                position = len(index.features)
                index.features.append(record)
                for name in record.get("names", {}).values():
                    key = normalise_name(name)
                    if key:
                        index.by_name[key].append(position)
                        # Also index the first word so "Mithi" finds
                        # "Mithi River" without scanning every feature.
                        head = key.split(" ")[0]
                        if head != key and len(head) >= 3:
                            index.by_name[head].append(position)
        logger.info(
            "feature_index_loaded",
            extra={"features": len(index.features), "names": len(index.by_name)},
        )
        return index

    def candidates(self, cores: list[str], box: geo.BBox) -> list[dict]:
        """Features whose name matches a core and whose bbox is in ``box``."""
        seen: set[int] = set()
        out: list[dict] = []
        for core in cores:
            key = normalise_name(core)
            for position in self.by_name.get(key, ()):
                if position in seen:
                    continue
                seen.add(position)
                record = self.features[position]
                b = record["bbox"]
                if not geo.bbox_intersects(box, (b[0], b[1], b[2], b[3])):
                    continue
                if not name_matches(record["names"], cores):
                    continue
                out.append(record)
        return out


def _line_parts(geometry: dict) -> list[list]:
    if geometry["type"] == "LineString":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiLineString":
        return list(geometry["coordinates"])
    return []


def _endpoints(geometry: dict) -> list[tuple[float, float]]:
    ends: list[tuple[float, float]] = []
    for part in _line_parts(geometry):
        if len(part) >= 2:
            ends.append((round(part[0][0], 4), round(part[0][1], 4)))
            ends.append((round(part[-1][0], 4), round(part[-1][1], 4)))
    return ends


def _connected_components(records: list[dict]) -> list[list[int]]:
    """Group line features that share an endpoint into courses."""
    parent = list(range(len(records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_end: dict[tuple[float, float], list[int]] = defaultdict(list)
    for i, record in enumerate(records):
        for end in _endpoints(record["geometry"]):
            by_end[end].append(i)
    for shared in by_end.values():
        for other in shared[1:]:
            parent[find(other)] = find(shared[0])

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(records)):
        groups[find(i)].append(i)
    return list(groups.values())


def _merge_lines(records: list[dict]) -> dict:
    parts: list[list] = []
    for record in records:
        parts.extend(_line_parts(record["geometry"]))
    if len(parts) == 1:
        return {"type": "LineString", "coordinates": parts[0]}
    return {"type": "MultiLineString", "coordinates": parts}


def _merge_areas(records: list[dict]) -> dict:
    polygons: list = []
    for record in records:
        g = record["geometry"]
        if g["type"] == "Polygon":
            polygons.append(g["coordinates"])
        elif g["type"] == "MultiPolygon":
            polygons.extend(g["coordinates"])
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def match_body(
    body: WaterBody, stations: list[MonitoringStation], index: FeatureIndex
) -> ImportOutcome:
    """Find and merge geometry for one water body. Does not write."""
    policy_key = TYPE_POLICY.get(body.water_type)
    if policy_key is None:
        return ImportOutcome("unsupported_type", "No geometry source for this type.")
    policy: MatchPolicy = POLICIES[policy_key]
    located = [s for s in stations if s.latitude is not None and s.longitude is not None]
    if not located:
        return ImportOutcome("no_station_coordinates", "No station has coordinates.")
    cores = name_cores(body)
    if not cores:
        return ImportOutcome("name_too_generic", "No distinctive name to match.")

    lons = [s.longitude for s in located]
    lats = [s.latitude for s in located]
    search_box = geo.expand_bbox(
        (min(lons), min(lats), max(lons), max(lats)), CANDIDATE_WINDOW_KM
    )
    records = index.candidates(cores, search_box)
    if not records:
        return ImportOutcome("no_candidates", "No named feature of this name nearby.")

    wanted_kind = "line" if policy.kind == "line" else "area"
    typed = [r for r in records if r["kind"] == wanted_kind]
    allowed = WATERWAY_AFFINITY.get(str(body.water_type))
    if allowed and wanted_kind == "line":
        typed = [r for r in typed if (r["tags"].get("waterway") or "") in allowed]
    if not typed:
        return ImportOutcome(
            "no_candidates",
            "Named features exist but none is the right kind of water feature "
            f"for a {str(body.water_type).replace('_', ' ')}.",
        )

    distances: dict[int, float] = {}
    if wanted_kind == "line":
        components = _connected_components(typed)
        chosen_records: list[dict] = []
        for component in components:
            members = [typed[i] for i in component]
            anchored = False
            for station in located:
                for record in members:
                    d = geo.distance_km(
                        record["geometry"], station.longitude, station.latitude
                    )
                    if d <= ANCHOR_KM:
                        anchored = True
                        distances[station.id] = min(distances.get(station.id, 9e9), d)
            if anchored:
                chosen_records.extend(members)
        if not chosen_records:
            nearest = min(
                (
                    geo.distance_km(r["geometry"], s.longitude, s.latitude)
                    for r in typed
                    for s in located
                ),
                default=None,
            )
            return ImportOutcome(
                "not_near_stations",
                f"Same-named features exist but the nearest is {nearest:.1f} km "
                "from a station."
                if nearest is not None
                else "No feature near a station.",
            )
        geometry = _merge_lines(chosen_records)
    else:
        chosen_records = []
        for station in located:
            ranked = sorted(
                (
                    (
                        geo.distance_km(
                            r["geometry"], station.longitude, station.latitude
                        ),
                        i,
                    )
                    for i, r in enumerate(typed)
                ),
                key=lambda t: t[0],
            )
            if not ranked:
                continue
            best_d, best_i = ranked[0]
            if (
                len(ranked) > 1
                and best_d > 0
                and ranked[1][0] - best_d < 0.1
                and ranked[1][0] <= policy.accept_km
            ):
                return ImportOutcome(
                    "ambiguous",
                    f"Station {station.name} is equally close to two same-named "
                    "features; not guessing.",
                )
            distances[station.id] = round(best_d, 3)
            if best_d <= policy.accept_km and typed[best_i] not in chosen_records:
                chosen_records.append(typed[best_i])
        if not chosen_records:
            nearest = min(distances.values(), default=None)
            return ImportOutcome(
                "not_near_stations",
                "Same-named features exist but none is within "
                f"{policy.accept_km:g} km of a station"
                + (f" (nearest {nearest:.1f} km)." if nearest is not None else "."),
                station_distances_km=distances,
            )
        geometry = _merge_areas(chosen_records)

    if not list(geo.iter_coords(geometry)):
        return ImportOutcome(
            "no_candidates", "Matching features carried no usable coordinates."
        )

    for station in located:
        if station.id not in distances:
            distances[station.id] = round(
                geo.distance_km(geometry, station.longitude, station.latitude), 3
            )
    supported = [d for d in distances.values() if d <= policy.accept_km]
    confidence = (
        "high"
        if supported
        and len(supported) == len(distances)
        and max(supported) <= policy.on_km
        else "medium"
    )
    return ImportOutcome(
        "matched",
        f"{len(chosen_records)} OSM feature(s) merged; "
        f"{len(supported)} of {len(distances)} stations within "
        f"{policy.accept_km:g} km.",
        geometry=geo.round_geometry(geometry, 5),
        confidence=confidence,
        source_ids=sorted({r["element"] for r in chosen_records})[:MAX_ELEMENT_IDS],
        station_distances_km=distances,
        feature_count=len(chosen_records),
    )


def store(
    db: Session, body: WaterBody, outcome: ImportOutcome, index: FeatureIndex
) -> None:
    """Persist one outcome, replacing any previous geometry for the body."""
    from app.water.geometry import relationship_for

    body.geometry_status = outcome.status
    existing = db.scalar(
        select(WaterBodyGeometry).where(WaterBodyGeometry.water_body_id == body.id)
    )
    if outcome.geometry is None:
        if existing is not None:
            db.delete(existing)
        return
    min_lon, min_lat, max_lon, max_lat = geo.bbox(outcome.geometry)
    row = existing or WaterBodyGeometry(water_body_id=body.id)
    row.source = SOURCE
    row.geometry_type = outcome.geometry["type"]
    row.geojson = json.dumps(outcome.geometry, separators=(",", ":"))
    row.min_lat, row.min_lon, row.max_lat, row.max_lon = (
        min_lat,
        min_lon,
        max_lat,
        max_lon,
    )
    row.source_ids = outcome.source_ids
    row.source_licence = LICENCE
    row.retrieved_at = datetime.now(UTC)
    row.version = index.meta.get("source_file") or index.meta.get("extracted_at")
    row.confidence = outcome.confidence or "medium"
    row.match_method = MATCH_METHOD
    row.match_notes = [
        outcome.detail,
        f"Extract: {index.meta.get('source_file', 'unknown')}",
    ]
    row.feature_count = outcome.feature_count
    row.clipped = False
    db.add(row)

    policy = POLICIES[TYPE_POLICY[body.water_type]]
    for station in db.scalars(
        select(MonitoringStation).where(MonitoringStation.water_body_id == body.id)
    ):
        d = outcome.station_distances_km.get(station.id)
        station.geometry_distance_m = round(d * 1000) if d is not None else None
        station.relationship_type = relationship_for(d, policy)


def import_geometry(
    db: Session,
    path: Path,
    *,
    water_types: list[str] | None = None,
    limit: int | None = None,
    only_missing: bool = False,
) -> dict:
    """Match every eligible water body against the extract."""
    index = FeatureIndex.load(path)
    types = [t for t in (water_types or list(TYPE_POLICY)) if t in TYPE_POLICY]
    query = select(WaterBody).where(WaterBody.water_type.in_(types))
    if only_missing:
        query = query.where(WaterBody.geometry_status != "matched")
    query = query.order_by(WaterBody.observation_count.desc())
    if limit:
        query = query.limit(limit)

    counts: dict[str, int] = defaultdict(int)
    bodies = list(db.scalars(query))
    for n, body in enumerate(bodies, start=1):
        stations = list(
            db.scalars(
                select(MonitoringStation).where(
                    MonitoringStation.water_body_id == body.id
                )
            )
        )
        outcome = match_body(body, stations, index)
        store(db, body, outcome, index)
        counts[outcome.status] += 1
        if n % 200 == 0:
            db.commit()
            logger.info("geometry_import_progress", extra={"done": n, "of": len(bodies)})
    db.commit()
    return {
        "bodies_considered": len(bodies),
        "extract": index.meta.get("source_file"),
        **dict(sorted(counts.items(), key=lambda kv: -kv[1])),
    }


def eligible_types() -> list[str]:
    """Water-body types geometry is attempted for."""
    return [str(t) for t in TYPE_POLICY if t != WaterBodyType.RIVER_STRETCH]

"""State and district boundaries from geoBoundaries.

Why geoBoundaries
-----------------
The CPCB extract carries no boundaries at all. Survey of India publishes the
authoritative administrative map, but not as an openly licensed, machine-
readable download. geoBoundaries redistributes open Indian boundaries with
their licences and provenance recorded:

* ADM1 (states / UTs) -- DataMeet and the Election Commission of India,
  CC BY 2.5 IN, 2011 vintage, 36 units, with ISO 3166-2 codes.
* ADM2 (districts) -- Pathways / Local Government Directory, ODbL,
  2021 vintage, 736 units, names only (no parent state).

Files are pinned to one geoBoundaries commit so a re-import is reproducible.
They are cached under ``data/raw/boundaries`` and never committed.

These boundaries are for navigation and filtering. They are not the legal
boundaries of India and the UI says so where they are shown.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.water import District, State
from app.models.water_geo import AdminBoundary
from app.water import geo
from app.water.matching import PLACE_ALIASES, normalise_name

GEOBOUNDARIES_COMMIT = "9469f09"
CACHE_DIR = Path(settings.water_cache_dir) / "boundaries"


@dataclass(frozen=True, slots=True)
class BoundarySource:
    """Where one boundary level comes from, and on what terms."""

    level: str
    url: str
    cache_name: str
    source: str
    licence: str
    vintage: str


SOURCES: dict[str, BoundarySource] = {
    "state": BoundarySource(
        level="state",
        url=(
            "https://github.com/wmgeolab/geoBoundaries/raw/"
            f"{GEOBOUNDARIES_COMMIT}/releaseData/gbOpen/IND/ADM1/"
            "geoBoundaries-IND-ADM1_simplified.geojson"
        ),
        cache_name="IND-ADM1.geojson",
        source="geoBoundaries IND ADM1 (DataMeet / Election Commission of India)",
        licence="CC BY 2.5 IN",
        vintage="2011",
    ),
    "district": BoundarySource(
        level="district",
        url=(
            "https://github.com/wmgeolab/geoBoundaries/raw/"
            f"{GEOBOUNDARIES_COMMIT}/releaseData/gbOpen/IND/ADM2/"
            "geoBoundaries-IND-ADM2_simplified.geojson"
        ),
        cache_name="IND-ADM2.geojson",
        source="geoBoundaries IND ADM2 (Pathways / Local Government Directory)",
        licence="ODbL 1.0",
        vintage="2021",
    ),
}

# ISO 3166-2:IN suffix -> the state code CPCB's file names use, where they
# differ. The 2011 ADM1 file already has the merged Dadra & Nagar Haveli and
# Daman & Diu UT (IN-DH); CPCB still publishes them separately.
ISO_TO_CPCB: dict[str, tuple[str, ...]] = {
    "CT": ("CG",),
    "OR": ("OD",),
    "TG": ("TS",),
    "UT": ("UK",),
    "DH": ("DN", "DD"),
}
CPCB_TO_ISO: dict[str, str] = {
    cpcb: iso for iso, codes in ISO_TO_CPCB.items() for cpcb in codes
}

# District names that differ between geoBoundaries and CPCB beyond spelling
# of the city itself (those go through PLACE_ALIASES).
DISTRICT_ALIASES: dict[str, tuple[str, ...]] = {
    "HYDRABAD": ("HYDERABAD",),
    "BANGALORE": ("BENGALURU URBAN", "BANGALORE URBAN", "BENGALURU"),
    "BANGALORE RURAL": ("BENGALURU RURAL",),
    "AHMADABAD": ("AHMEDABAD",),
    "AHMADNAGAR": ("AHMEDNAGAR",),
    "GURGAON": ("GURUGRAM",),
    "KHORDHA": ("KHURDA", "KHORDA"),
    "MYSORE": ("MYSURU",),
}


def plain(text: str) -> str:
    """Accent-folded display name (``Mahārāshtra`` -> ``Maharashtra``)."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def load_source(level: str, *, path: Path | None = None, offline: bool = False) -> dict:
    """The GeoJSON for ``level``, from ``path``, the cache, or the pinned URL."""
    src = SOURCES[level]
    target = path or CACHE_DIR / src.cache_name
    if not target.exists():
        if offline:
            raise FileNotFoundError(f"{target} not cached and offline import requested")
        target.parent.mkdir(parents=True, exist_ok=True)
        response = httpx.get(src.url, follow_redirects=True, timeout=120)
        response.raise_for_status()
        target.write_bytes(response.content)
    return json.loads(target.read_text(encoding="utf-8"))


def _name_keys(name: str) -> set[str]:
    key = normalise_name(name)
    keys = {key, *DISTRICT_ALIASES.get(key, ()), *PLACE_ALIASES.get(key, ())}
    return {normalise_name(k) for k in keys}


def _row(level: str, feature: dict, name: str, source_id: str) -> AdminBoundary:
    src = SOURCES[level]
    geometry = geo.round_geometry(feature["geometry"], 4)
    min_lon, min_lat, max_lon, max_lat = geo.bbox(geometry)
    c_lon, c_lat = geo.centroid(geometry)
    return AdminBoundary(
        level=level,
        name=name,
        normalized_name=normalise_name(name),
        geojson=json.dumps(geometry, separators=(",", ":")),
        min_lat=min_lat,
        min_lon=min_lon,
        max_lat=max_lat,
        max_lon=max_lon,
        centroid_lat=c_lat,
        centroid_lon=c_lon,
        source=src.source,
        source_id=source_id,
        licence=src.licence,
        vintage=src.vintage,
    )


PARENT_FALLBACK_KM = 25.0


def _parent_state(
    geometry: dict, row: AdminBoundary, state_rows: list[tuple[AdminBoundary, dict]]
) -> tuple[AdminBoundary, dict] | None:
    """The state a district lies in, by a vote of its vertices.

    The state file (2011) and the district file (2021) were drawn separately,
    so their shared edges do not coincide; a single centroid test puts
    Kamrup Metropolitan in Meghalaya. Sampling up to 60 vertices and taking
    the state that contains most of them is robust to that. A district with
    no vertex inside any state (islands on simplified outlines) falls back to
    the nearest state within :data:`PARENT_FALLBACK_KM`.
    """
    box = (row.min_lon, row.min_lat, row.max_lon, row.max_lat)
    candidates = [
        (s, g)
        for s, g in state_rows
        if geo.bbox_intersects(box, (s.min_lon, s.min_lat, s.max_lon, s.max_lat))
    ]
    vertices = list(geo.iter_coords(geometry))
    step = max(1, len(vertices) // 60)
    sample = [*vertices[::step], (row.centroid_lon, row.centroid_lat)]
    votes = [
        (sum(geo.contains_point(g, lon, lat) for lon, lat in sample), s, g)
        for s, g in candidates
    ]
    votes = [v for v in votes if v[0] > 0]
    if votes:
        _, s, g = max(votes, key=lambda v: v[0])
        return s, g
    nearest = min(
        (
            (geo.distance_km(g, row.centroid_lon, row.centroid_lat), s, g)
            for s, g in state_rows
        ),
        key=lambda t: t[0],
        default=None,
    )
    if nearest and nearest[0] <= PARENT_FALLBACK_KM:
        return nearest[1], nearest[2]
    return None


def import_boundaries(
    db: Session,
    *,
    state_path: Path | None = None,
    district_path: Path | None = None,
    offline: bool = False,
) -> dict:
    """Replace all boundaries with a fresh import. Returns counts."""
    states_by_code = {s.code: s for s in db.scalars(select(State))}
    db.execute(delete(AdminBoundary))

    adm1 = load_source("state", path=state_path, offline=offline)
    state_rows: list[tuple[AdminBoundary, dict]] = []
    for feature in adm1["features"]:
        props = feature["properties"]
        iso = (props.get("shapeISO") or "").removeprefix("IN-")
        row = _row(
            "state", feature, plain(props["shapeName"]), props.get("shapeISO") or ""
        )
        codes = ISO_TO_CPCB.get(iso, (iso,))
        linked = next((states_by_code[c] for c in codes if c in states_by_code), None)
        row.state_id = linked.id if linked else None
        db.add(row)
        state_rows.append((row, json.loads(row.geojson)))
    db.flush()

    districts_by_state: dict[int, dict[str, District]] = {}
    for d in db.scalars(select(District)):
        districts_by_state.setdefault(d.state_id, {})[normalise_name(d.name)] = d

    adm2 = load_source("district", path=district_path, offline=offline)
    linked_districts = 0
    unassigned = 0
    for feature in adm2["features"]:
        props = feature["properties"]
        row = _row("district", feature, plain(props["shapeName"]), props["shapeID"])
        parent = _parent_state(json.loads(row.geojson), row, state_rows)
        if parent is None:
            unassigned += 1
        else:
            state_row = parent[0]
            row.parent_name = state_row.name
            row.state_id = state_row.state_id
            if state_row.state_id is not None:
                candidates = districts_by_state.get(state_row.state_id, {})
                match = next(
                    (candidates[k] for k in _name_keys(row.name) if k in candidates),
                    None,
                )
                if match is not None:
                    row.district_id = match.id
                    linked_districts += 1
        db.add(row)
    db.commit()
    from app.services.geo_service import clear_boundary_cache

    clear_boundary_cache()
    return {
        "states": len(state_rows),
        "states_linked": sum(1 for r, _ in state_rows if r.state_id),
        "districts": len(adm2["features"]),
        "districts_linked_to_cpcb": linked_districts,
        "districts_without_parent": unassigned,
        "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def state_boundary(db: Session, state: State) -> AdminBoundary | None:
    """The ADM1 boundary for a CPCB state, via its ISO code."""
    iso = "IN-" + CPCB_TO_ISO.get(state.code, state.code)
    return db.scalar(
        select(AdminBoundary).where(
            AdminBoundary.level == "state", AdminBoundary.source_id == iso
        )
    )

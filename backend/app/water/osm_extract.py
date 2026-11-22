"""Extract named water features from an OpenStreetMap regional extract.

Why a bulk extract at all
-------------------------
Phase 2 matched geometry by asking the public Overpass API once per water
body. That is thousands of requests against a shared free service: it is
rate-limited, it blocked us repeatedly, a national pass took hours, and a
deployment could never depend on it. A Geofabrik regional extract is the
source the same data comes from, downloaded once (``india-latest.osm.pbf``,
~1.7 GB, ODbL), and read locally.

What this step produces
-----------------------
One pass over the extract writes a much smaller newline-delimited GeoJSON
file holding only *named* water features:

* ``waterway`` in river / stream / canal / drain / tidal_channel -> lines
* ``natural=water``, ``landuse=reservoir``, ``water=*`` -> areas
  (ways and multipolygon relations, assembled by osmium)

Each line records the OSM element id, every name tag, the water tags, the
bounding box and the geometry. Matching (:mod:`app.water.geometry_import`)
then runs entirely offline against this file, so importing geometry for the
whole country makes **no** network requests.

Run:

    python -m app.water.cli extract-osm --pbf data/raw/osm/india-latest.osm.pbf
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import osmium

from app.core.logging import get_logger

logger = get_logger(__name__)

WATERWAY_VALUES = {"river", "stream", "canal", "drain", "tidal_channel"}
AREA_TAGS = (("natural", "water"), ("landuse", "reservoir"), ("waterway", "riverbank"))
NAME_KEYS = ("name", "name:en", "alt_name", "official_name", "int_name", "old_name")
KEEP_TAGS = (
    "waterway",
    "natural",
    "water",
    "landuse",
    "intermittent",
    "wikidata",
    "wikipedia",
)


@dataclass(slots=True)
class ExtractStats:
    """What one pass over the extract produced."""

    lines: int = 0
    areas: int = 0
    skipped_unnamed: int = 0
    skipped_geometry_error: int = 0

    def to_dict(self) -> dict:
        """Serialise for the CLI."""
        return {
            "line_features": self.lines,
            "area_features": self.areas,
            "skipped_unnamed": self.skipped_unnamed,
            "skipped_geometry_error": self.skipped_geometry_error,
        }


def _names(tags: osmium.osm.TagList) -> dict[str, str]:
    return {k: tags[k] for k in NAME_KEYS if k in tags}


def _kept_tags(tags: osmium.osm.TagList) -> dict[str, str]:
    return {k: tags[k] for k in KEEP_TAGS if k in tags}


def _is_water_area(tags: osmium.osm.TagList) -> bool:
    return any(tags.get(k) == v for k, v in AREA_TAGS) or "water" in tags


def _is_waterway_line(tags: osmium.osm.TagList) -> bool:
    return tags.get("waterway") in WATERWAY_VALUES


def _bbox(geometry: dict) -> list[float]:
    xs: list[float] = []
    ys: list[float] = []

    def walk(coords: object) -> None:
        if isinstance(coords, (int, float)):
            return
        if (
            isinstance(coords, list)
            and len(coords) >= 2
            and all(isinstance(c, (int, float)) for c in coords[:2])
        ):
            xs.append(float(coords[0]))
            ys.append(float(coords[1]))
            return
        if isinstance(coords, list):
            for part in coords:
                walk(part)

    walk(geometry["coordinates"])
    return [min(xs), min(ys), max(xs), max(ys)]


def iter_features(pbf_path: Path, *, cache: str = "flex_mem") -> Iterator[dict]:
    """Yield one record per named water feature in the extract.

    ``cache`` is the osmium node-location store. ``flex_mem`` is fastest and
    needs several GB for a country-sized extract; pass
    ``sparse_file_array,<path>`` to keep it on disk instead.
    """
    factory = osmium.geom.GeoJSONFactory()
    stats = ExtractStats()

    processor = (
        osmium.FileProcessor(str(pbf_path))
        .with_locations(cache)
        .with_areas()
        .with_filter(osmium.filter.EmptyTagFilter())
    )
    for obj in processor:
        tags = obj.tags
        if not any(k in tags for k in NAME_KEYS):
            continue
        kind = None
        geometry_json = None
        try:
            if obj.is_area() and _is_water_area(tags):
                kind = "area"
                geometry_json = factory.create_multipolygon(obj)
            elif (
                not obj.is_area()
                and isinstance(obj, osmium.osm.Way)
                and _is_waterway_line(tags)
            ):
                kind = "line"
                geometry_json = factory.create_linestring(obj)
        except (RuntimeError, ValueError, osmium.InvalidLocationError):
            stats.skipped_geometry_error += 1
            continue
        if not kind or not geometry_json:
            continue
        geometry = json.loads(geometry_json)
        if not geometry.get("coordinates"):
            continue
        if kind == "line":
            stats.lines += 1
            element = f"way/{obj.id}"
        else:
            stats.areas += 1
            # An area id is the way id doubled (or relation id doubled + 1).
            element = (
                f"relation/{obj.orig_id()}"
                if obj.from_way() is False
                else f"way/{obj.orig_id()}"
            )
        yield {
            "element": element,
            "kind": kind,
            "names": _names(tags),
            "tags": _kept_tags(tags),
            "bbox": _bbox(geometry),
            "geometry": geometry,
        }
    logger.info("osm_extract_scanned", extra=stats.to_dict())


def write_features(pbf_path: Path, out_path: Path, *, cache: str = "flex_mem") -> dict:
    """Write the named water features of ``pbf_path`` to ``out_path``."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = areas = 0
    with out_path.open("w", encoding="utf-8") as handle:
        for record in iter_features(pbf_path, cache=cache):
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            if record["kind"] == "line":
                lines += 1
            else:
                areas += 1
    meta = {
        "source_file": pbf_path.name,
        "source": "OpenStreetMap via Geofabrik regional extract",
        "licence": "ODbL 1.0 — © OpenStreetMap contributors",
        "extracted_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "line_features": lines,
        "area_features": areas,
        "output": str(out_path),
        "output_mb": round(out_path.stat().st_size / 1e6, 1),
    }
    out_path.with_suffix(".meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    return meta

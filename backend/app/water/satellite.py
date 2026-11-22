"""Sentinel-2 scenes for water bodies, via Microsoft Planetary Computer.

One complete, honest path: find a recent Sentinel-2 L2A scene that covers the
water body, check -- over the body's own polygon, not the tile -- that the
water is actually visible, and only then record the scene, a true-colour
image of the body, and an uncalibrated turbidity *proxy*.

What the proxy is and is not
----------------------------
NDTI = (Red - Green) / (Red + Green), from bands B04 and B03 of the L2A
surface reflectance product, median over the polygon. It rises with
suspended sediment, but it is not turbidity: it is not calibrated against any
in-situ measurement here, it has no NTU unit, and it is affected by depth,
bottom reflectance, algae and residual shoreline pixels. It is labelled
``SATELLITE_OBSERVED`` everywhere and never compared with a standard or
mixed with CPCB laboratory values.

Scene acceptance, per water body
--------------------------------
* The tile's footprint contains the whole body (a partial tile would compute
  statistics over half a lake).
* Over the body's polygon, the Scene Classification Layer marks at least
  :data:`MIN_WATER_FRACTION` of pixels as water (class 6) and at most
  :data:`MAX_CLOUD_FRACTION` as cloud or cirrus (classes 8-10). The
  tile-level cloud percentage is not trusted for this: a scene reported as
  1% cloudy can have cirrus over exactly the lake of interest.

Every scene tried and why it was rejected is recorded with the image.

Rivers are not attempted: the stored river geometry is a centreline, and a
10 m pixel cannot isolate most Indian river channels reliably.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.water import WaterBody
from app.models.water_geo import WaterBodyGeometry, WaterImage
from app.water import geo

logger = get_logger(__name__)

STAC_SEARCH_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
DATA_API = "https://planetarycomputer.microsoft.com/api/data/v1"
COLLECTION = "sentinel-2-l2a"
PROVIDER = "Microsoft Planetary Computer"
SOURCE = "Copernicus Sentinel-2 L2A (ESA)"
SENSOR = "Sentinel-2 MSI"
LICENCE = "Copernicus Sentinel data, free and open (Sentinel Data Legal Notice)"

LOOKBACK_DAYS = 365
TILE_CLOUD_PREFILTER = 30.0
MAX_SCENES_TRIED = 8
MIN_WATER_FRACTION = 0.8
MAX_CLOUD_FRACTION = 0.05
SCL_WATER = 6
SCL_CLOUD = (8, 9, 10)
NDTI_EXPRESSION = "(B04-B03)/(B04+B03)"

PROXY_LABEL = "Satellite-derived turbidity proxy (NDTI, uncalibrated)"
PROXY_CAVEAT = (
    "NDTI is a relative index from surface reflectance, not a turbidity "
    "measurement. It has no NTU unit, is not calibrated against CPCB samples, "
    "and up to 20% of the pixels it summarises may be shoreline or vegetation."
)


@dataclass(slots=True)
class SceneOutcome:
    """The result of looking for a usable scene for one water body."""

    status: str
    """``retrieved``, ``no_polygon``, ``no_scene``, ``source_error``."""

    detail: str = ""
    image: WaterImage | None = None
    tried: list[dict] = field(default_factory=list)


def stac_search(bbox: geo.BBox, start: datetime, end: datetime) -> list[dict]:
    """Newest-first Sentinel-2 L2A items intersecting ``bbox``."""
    response = httpx.post(
        STAC_SEARCH_URL,
        json={
            "collections": [COLLECTION],
            "bbox": list(bbox),
            "datetime": f"{start:%Y-%m-%d}/{end:%Y-%m-%d}",
            "query": {"eo:cloud_cover": {"lt": TILE_CLOUD_PREFILTER}},
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
            "limit": MAX_SCENES_TRIED,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json().get("features", [])


def item_statistics(item_id: str, feature: dict, params: dict) -> dict:
    """Zonal statistics for one item over one GeoJSON feature."""
    response = httpx.post(
        f"{DATA_API}/item/statistics",
        params={"collection": COLLECTION, "item": item_id, **params},
        json=feature,
        timeout=120,
    )
    response.raise_for_status()
    stats = response.json()["properties"]["statistics"]
    return next(iter(stats.values()))


def image_url(item_id: str, bbox: geo.BBox, size: int) -> str:
    """A true-colour PNG of the box, rendered by the Planetary Computer."""
    minx, miny, maxx, maxy = bbox
    aspect = (maxx - minx) / max(maxy - miny, 1e-9)
    w, h = (
        (size, max(64, round(size / aspect)))
        if aspect >= 1
        else (
            max(64, round(size * aspect)),
            size,
        )
    )
    return (
        f"{DATA_API}/item/bbox/{minx:.5f},{miny:.5f},{maxx:.5f},{maxy:.5f}/"
        f"{w}x{h}.png?collection={COLLECTION}&item={item_id}&assets=visual"
    )


def _covers(item: dict, box: geo.BBox) -> bool:
    footprint = item.get("geometry")
    if not footprint:
        return False
    corners = [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])]
    return all(geo.contains_point(footprint, x, y) for x, y in corners)


def _scl_fractions(stats: dict) -> tuple[float, float, int]:
    counts, classes = stats["histogram"]
    total = sum(counts) or 1
    by_class = {int(c): n for n, c in zip(counts, classes, strict=True)}
    water = by_class.get(SCL_WATER, 0) / total
    cloud = sum(by_class.get(c, 0) for c in SCL_CLOUD) / total
    return water, cloud, int(total)


def find_scene(
    body: WaterBody,
    polygon: dict,
    *,
    now: datetime | None = None,
    search: Callable[[geo.BBox, datetime, datetime], list[dict]] = stac_search,
    stats: Callable[[str, dict, dict], dict] = item_statistics,
) -> SceneOutcome:
    """Pick the newest scene that passes the per-body checks. Does not write."""
    now = now or datetime.now(UTC)
    box = geo.bbox(polygon)
    feature = {"type": "Feature", "properties": {}, "geometry": polygon}
    try:
        items = search(box, now - timedelta(days=LOOKBACK_DAYS), now)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return SceneOutcome("source_error", f"Scene search failed: {exc}")

    tried: list[dict] = []
    for item in items[:MAX_SCENES_TRIED]:
        entry = {
            "scene_id": item["id"],
            "date": item["properties"]["datetime"][:10],
            "tile_cloud_cover": item["properties"].get("eo:cloud_cover"),
        }
        tried.append(entry)
        if not _covers(item, box):
            entry["rejected"] = "tile does not contain the whole water body"
            continue
        try:
            water, cloud, pixels = _scl_fractions(
                stats(item["id"], feature, {"assets": "SCL", "categorical": "true"})
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            entry["rejected"] = f"scene classification unavailable: {exc}"
            continue
        entry.update(water_fraction=round(water, 3), cloud_fraction=round(cloud, 3))
        if cloud > MAX_CLOUD_FRACTION:
            entry["rejected"] = f"{cloud:.0%} of the water body under cloud or cirrus"
            continue
        if water < MIN_WATER_FRACTION:
            entry["rejected"] = f"only {water:.0%} of the polygon classified as water"
            continue
        try:
            ndti = stats(
                item["id"],
                feature,
                {"expression": NDTI_EXPRESSION, "asset_as_band": "True"},
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            entry["rejected"] = f"band statistics unavailable: {exc}"
            continue
        entry["accepted"] = True
        pad = geo.expand_bbox(box, 0.3)
        acquired = datetime.fromisoformat(
            item["properties"]["datetime"].replace("Z", "+00:00")
        )
        image = WaterImage(
            image_id=f"s2:{item['id']}:{body.id}",
            water_body_id=body.id,
            evidence_type="SATELLITE",
            source=SOURCE,
            provider=PROVIDER,
            sensor=SENSOR,
            scene_id=item["id"],
            acquisition_date=acquired,
            thumbnail_url=image_url(item["id"], pad, 256),
            full_image_url=image_url(item["id"], pad, 1024),
            min_lon=pad[0],
            min_lat=pad[1],
            max_lon=pad[2],
            max_lat=pad[3],
            licence=LICENCE,
            retrieved_at=now,
            image_metadata={
                "tile": item["properties"].get("s2:mgrs_tile"),
                "tile_cloud_cover": item["properties"].get("eo:cloud_cover"),
                "scl_water_fraction": round(water, 3),
                "scl_cloud_fraction": round(cloud, 3),
                "scl_pixels": pixels,
                "proxy": {
                    "name": "ndti",
                    "label": PROXY_LABEL,
                    "evidence_type": "SATELLITE_OBSERVED",
                    "median": round(ndti["median"], 4),
                    "mean": round(ndti["mean"], 4),
                    "pixels": int(ndti.get("count", 0)),
                    "unit": None,
                    "calibrated": False,
                    "caveat": PROXY_CAVEAT,
                },
                "acceptance": {
                    "min_water_fraction": MIN_WATER_FRACTION,
                    "max_cloud_fraction": MAX_CLOUD_FRACTION,
                },
                "scenes_tried": tried,
            },
        )
        return SceneOutcome("retrieved", f"Scene {entry['date']} accepted.", image, tried)

    return SceneOutcome(
        "no_scene",
        f"None of the {len(tried)} recent scene(s) showed this water body clearly.",
        tried=tried,
    )


def fetch_imagery(
    db: Session,
    body: WaterBody,
    **kwargs: object,
) -> SceneOutcome:
    """Find and store a scene for ``body`` (polygon water bodies only)."""
    row = db.scalar(
        select(WaterBodyGeometry).where(WaterBodyGeometry.water_body_id == body.id)
    )
    if row is None or row.geometry_type not in geo.POLYGON_TYPES:
        return SceneOutcome(
            "no_polygon",
            "Satellite retrieval needs a matched lake or reservoir outline; "
            "river centrelines are not attempted.",
        )
    outcome = find_scene(body, json.loads(row.geojson), **kwargs)  # type: ignore[arg-type]
    if outcome.image is not None:
        existing = db.scalar(
            select(WaterImage).where(WaterImage.image_id == outcome.image.image_id)
        )
        if existing is not None:
            db.delete(existing)
            db.flush()
        db.add(outcome.image)
        db.commit()
    return outcome


def archive_scene_image(
    db: Session, image: WaterImage, *, timeout: int = 60
) -> dict | None:
    """Copy one scene's rendered image into the object store, once.

    Returns the stored reference, or ``None`` when there is nothing to do or
    the store would not take it. Idempotent: a scene already archived is left
    alone, so the job can be re-run over everything without re-downloading.

    The database keeps the reference, never the bytes.
    """
    from app.core.objects import evidence_key, get_object_store

    meta = dict(image.image_metadata or {})
    if meta.get("object"):
        return meta["object"]
    if not image.full_image_url or not image.scene_id:
        return None

    body = db.get(WaterBody, image.water_body_id)
    if body is None:
        return None

    try:
        response = httpx.get(image.full_image_url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        payload = response.content
        content_type = response.headers.get("content-type", "image/png")
    except Exception as exc:
        logger.warning(
            "scene_archive_fetch_failed",
            extra={"scene": image.scene_id, "error": str(exc)[:200]},
        )
        return None

    if not payload:
        return None

    store = get_object_store()
    ref = store.put(
        evidence_key(body.slug, image.scene_id),
        payload,
        content_type=content_type,
    )
    if ref is None:
        # Unavailable, denied, or misconfigured. The scene keeps its
        # metadata and its rendered URL; nothing is recorded that is not true.
        return None

    meta["object"] = ref.to_dict()
    image.image_metadata = meta
    db.add(image)
    db.commit()
    logger.info(
        "scene_archived",
        extra={"scene": image.scene_id, "uri": ref.uri, "bytes": ref.size_bytes},
    )
    return meta["object"]


def images_for(db: Session, body: WaterBody) -> list[dict]:
    """Stored imagery for the detail page, newest first."""
    rows = db.scalars(
        select(WaterImage)
        .where(WaterImage.water_body_id == body.id)
        .order_by(WaterImage.acquisition_date.desc())
    )
    out = []
    for r in rows:
        meta = r.image_metadata or {}
        out.append(
            {
                "image_id": r.image_id,
                "evidence_type": r.evidence_type,
                "source": r.source,
                "provider": r.provider,
                "sensor": r.sensor,
                "scene_id": r.scene_id,
                "acquisition_date": r.acquisition_date.date().isoformat()
                if r.acquisition_date
                else None,
                "thumbnail_url": r.thumbnail_url,
                "full_image_url": r.full_image_url,
                # Present only once the archive job has copied the rendered
                # image into the object store; absent means "not archived",
                # never "missing".
                "object": meta.get("object"),
                "bbox": [r.min_lon, r.min_lat, r.max_lon, r.max_lat],
                "licence": r.licence,
                "retrieved_at": r.retrieved_at.isoformat() if r.retrieved_at else None,
                "water_fraction": meta.get("scl_water_fraction"),
                "cloud_fraction": meta.get("scl_cloud_fraction"),
                "proxy": meta.get("proxy"),
                "scenes_tried": meta.get("scenes_tried", []),
            }
        )
    return out

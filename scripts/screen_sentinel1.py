r"""Screen recent Sentinel-1 imagery over Indian waters with the v2.2 detector.

End to end on real data: find the most recent Sentinel-1 GRD scenes over a
region, pull VV backscatter tiles from Copernicus, and run each through the
trained SAR classifier. Reports how many tiles were screened and how many
came back as candidates.

**Read this before reading the numbers.** The classifier was trained on the
PANGAEA 980773 / DARTIS quicklook patches, which are 640x640 JPEGs that have
already been contrast-stretched by whoever built the dataset. These tiles are
sigma-nought VV in decibels, fetched at a different resolution over different
water. The per-tile percentile stretch below narrows that gap; it does not
close it. **The model is being applied outside the distribution it was
measured on, so its reported accuracy does not carry over**, and a positive
here is a screening flag rather than a detection. The value of this run is
that the pipeline works on live imagery, not that the outputs are reliable.

Nothing here writes a pollution event. Predictions go to ``prediction_logs``,
which is where unverified model output belongs.

Usage:
    python scripts/screen_sentinel1.py
    python scripts/screen_sentinel1.py --regions gulf_of_kutch_w --max-tiles 12
"""

from __future__ import annotations

import argparse
import io
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import httpx  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.gee.regions import all_cells  # noqa: E402
from app.monitoring.prediction_log import log_prediction  # noqa: E402
from app.models.enums import PollutionSignature  # noqa: E402
from app.vision.registry import get_sar_v2_2_detector  # noqa: E402
from app.vision.sentinel2_indices import get_sentinel2_client  # noqa: E402

CATALOG_URL = "https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0/search"

#: The detector's input size. Tiles are fetched at exactly this, so nothing
#: is resampled twice.
TILE_PX = 224
#: Tile span in degrees. At this latitude 0.05 deg is ~5.5 km, so a 224 px
#: tile is ~25 m per pixel -- coarser than GRD's 10 m, fine for a slick,
#: and it keeps a region to a sane number of requests.
TILE_DEG = 0.05

#: A tile must be almost entirely real backscatter.
#:
#: This was 0.60, which let through tiles that were a third black. Sentinel
#: Hub renders outside-footprint pixels as zero, and zero in decibels is
#: negative infinity -- so a partly-covered tile reaches the model as a
#: bright patch of water beside a solid black block. Nothing in the training
#: set looks remotely like that, and it was a large part of why live tiles
#: scored nothing like benchmark patches. A tile that is not nearly whole is
#: now skipped rather than padded.
MIN_VALID_FRACTION = 0.98

#: The decibel window mapped onto the 8-bit range the model was trained on.
#:
#: Derived by matching the training distribution rather than chosen. The
#: PANGAEA open-water patches have a mean near 147 and a standard deviation
#: near 18 in 8-bit terms, and measured open ocean here has a sigma-nought
#: spread of under 2 dB -- so the window that reproduces those statistics is
#: about 25 dB wide with water sitting high inside it. At -30..-5 dB a real
#: tile's water pixels come out at mean 146.1, std 19.1, which is the
#: training distribution to within a unit.
#:
#: Deliberately **fixed**, not a per-tile percentile stretch. A percentile
#: stretch rescales every tile to fill the full range, which multiplies the
#: contrast of calm water by a factor of three or four and produces an image
#: whose statistics depend on what else happened to be in the tile. That was
#: the first attempt, and it is why the model saturated.
DB_WINDOW_LOW = -30.0
DB_WINDOW_HIGH = -5.0

#: Above this, a softmax is not expressing confidence, it is saturated.
#: On its own training patches this model spreads from 0.005 to 0.83; a run
#: that comes back at 1.000 on every tile is reporting that the input is
#: nothing like what it was fitted on, whatever class it picked.
SATURATED_ABOVE = 0.999

CACHE_DIR = Path(settings.water_cache_dir) / "sentinel1"

EVALSCRIPT = """//VERSION=3
// Sigma-nought VV in decibels, as float, single band. The stretch happens
// client side so the full dynamic range survives the transfer.
//
// One band rather than two: Pillow cannot open a multi-band float32 TIFF,
// and a second band for the data mask is unnecessary anyway -- outside the
// footprint VV is zero, log10(0) is -Infinity, and a non-finite sample is
// an unambiguous nodata marker.
function setup() {
  return {
    input: [{ bands: ["VV"] }],
    output: { bands: 1, sampleType: "FLOAT32" }
  };
}
function evaluatePixel(s) {
  return [10 * Math.log(s.VV) / Math.LN10];
}
"""


def stretch(db: np.ndarray) -> np.ndarray | None:
    """Map a decibel tile onto the 8-bit range the model was trained on.

    A fixed window, for the reasons given at :data:`DB_WINDOW_LOW`. Returns
    ``None`` when the tile is not nearly all real data, because a tile with
    a black corner is not a dimmer version of a good tile -- it is a
    different kind of image, and the model has never seen one.
    """
    # Outside the scene footprint VV is zero and the decibel conversion
    # gives -Infinity, so finiteness is the data mask.
    valid = np.isfinite(db)
    if valid.mean() < MIN_VALID_FRACTION:
        return None
    values = db[valid]
    if values.size == 0:
        return None

    span = DB_WINDOW_HIGH - DB_WINDOW_LOW
    # Any stray invalid pixel takes the window's midpoint rather than its
    # floor: a handful of black pixels in an otherwise complete tile should
    # not pull the image statistics, and mid-grey is the least wrong filler.
    filled = np.where(valid, db, (DB_WINDOW_LOW + DB_WINDOW_HIGH) / 2.0)
    scaled = np.clip((filled - DB_WINDOW_LOW) / span, 0.0, 1.0)
    return (scaled * 255.0).astype(np.uint8)


def tile_statistics(arr: np.ndarray) -> dict[str, float]:
    """Mean and spread of a prepared tile, for comparison with training.

    Reported on every run. If these drift away from the training
    distribution the scores stop meaning anything, and that should be
    visible rather than inferred from the scores going strange.
    """
    return {"mean": round(float(arr.mean()), 1), "std": round(float(arr.std()), 1)}


#: What the training patches look like in 8-bit terms, measured from the
#: PANGAEA open-water subsets. A prepared tile should land near this.
TRAINING_PROFILE = {"mean": 147.0, "std": 18.0}


def recent_scenes(token: str, bbox, days: int, limit: int = 10) -> list[dict]:
    """Sentinel-1 GRD scenes intersecting ``bbox`` in the last ``days``."""
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    response = httpx.post(
        CATALOG_URL,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "bbox": list(bbox),
            "datetime": f"{start.isoformat().replace('+00:00', 'Z')}/"
            f"{end.isoformat().replace('+00:00', 'Z')}",
            "collections": ["sentinel-1-grd"],
            "limit": limit,
        },
        timeout=60.0,
    )
    if response.status_code != 200:
        return []
    return response.json().get("features", [])


def footprint_bbox(feature: dict) -> tuple[float, float, float, float] | None:
    """Bounding box of a scene's footprint polygon."""
    rings = (feature.get("geometry") or {}).get("coordinates") or []
    if not rings or not rings[0]:
        return None
    lons = [point[0] for point in rings[0]]
    lats = [point[1] for point in rings[0]]
    return (min(lons), min(lats), max(lons), max(lats))


def intersect(a, b):
    """Overlap of two bboxes, or ``None`` when they do not meet."""
    min_lon = max(a[0], b[0])
    min_lat = max(a[1], b[1])
    max_lon = min(a[2], b[2])
    max_lat = min(a[3], b[3])
    if max_lon <= min_lon or max_lat <= min_lat:
        return None
    return (min_lon, min_lat, max_lon, max_lat)


def tiles_in(bbox, max_tiles: int):
    """Tile a bbox into ``TILE_DEG`` squares, up to ``max_tiles``."""
    min_lon, min_lat, max_lon, max_lat = bbox
    out = []
    lat = min_lat
    while lat < max_lat and len(out) < max_tiles:
        lon = min_lon
        while lon < max_lon and len(out) < max_tiles:
            out.append(
                (
                    lon,
                    lat,
                    min(lon + TILE_DEG, max_lon),
                    min(lat + TILE_DEG, max_lat),
                )
            )
            lon += TILE_DEG
        lat += TILE_DEG
    return out


def fetch_tile(token: str, bbox, day: str) -> np.ndarray | None:
    """One VV tile as a stretched 8-bit array, or ``None`` if unusable."""
    body = {
        "input": {
            "bounds": {
                "bbox": list(bbox),
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [
                {
                    "type": "sentinel-1-grd",
                    "dataFilter": {
                        "timeRange": {
                            "from": f"{day}T00:00:00Z",
                            "to": f"{day}T23:59:59Z",
                        },
                        "acquisitionMode": "IW",
                        "polarization": "DV",
                    },
                    "processing": {
                        "backCoeff": "SIGMA0_ELLIPSOID",
                        "orthorectify": True,
                    },
                }
            ],
        },
        "output": {
            "width": TILE_PX,
            "height": TILE_PX,
            "responses": [
                {"identifier": "default", "format": {"type": "image/tiff"}}
            ],
        },
        "evalscript": EVALSCRIPT,
    }
    try:
        response = httpx.post(
            settings.cdse_process_url,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=120.0,
        )
    except Exception:  # noqa: BLE001
        return None
    if response.status_code != 200 or not response.content:
        return None

    try:
        raster = Image.open(io.BytesIO(response.content))
        db = np.array(raster, dtype=np.float32)
    except Exception:  # noqa: BLE001
        return None
    if db.ndim != 2:
        return None
    return stretch(db)


def main(argv: list[str]) -> int:
    """Screen recent Sentinel-1 tiles for the requested regions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regions",
        nargs="*",
        default=["gulf_of_kutch_w", "mumbai_offshore_w", "gulf_of_mannar"],
    )
    parser.add_argument("--days", type=int, default=20)
    parser.add_argument("--max-tiles", type=int, default=16)
    args = parser.parse_args(argv[1:])

    detector = get_sar_v2_2_detector()
    if not getattr(detector, "is_available", False):
        print("The v2.2 detector is not available. Nothing screened.")
        return 1

    client = get_sentinel2_client()
    token = client._get_token()
    if not token:
        print("No CDSE token. Nothing screened.")
        return 1

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cells = {c.code: c for c in all_cells()}

    print("Sentinel-1 screening with", f"{detector.name}:{detector.version}")
    print(
        "NOTE: the model was trained on PANGAEA quicklook patches. These "
        "tiles are a different product;\n      its measured accuracy does "
        "not transfer, so a positive is a screening flag, not a detection.\n"
    )

    grand_screened = grand_candidates = 0
    all_confidences: list[float] = []
    all_tile_stats: list[dict[str, float]] = []
    with SessionLocal() as db:
        for code in args.regions:
            cell = cells.get(code)
            if cell is None:
                print(f"  {code}: unknown region")
                continue
            region_bbox = (cell.min_lon, cell.min_lat, cell.max_lon, cell.max_lat)

            scenes = recent_scenes(token, region_bbox, args.days)
            if not scenes:
                print(f"  {cell.name}: no Sentinel-1 scene in the last {args.days} days")
                continue

            screened = candidates = skipped = 0
            confidences: list[float] = []
            tile_stats: list[dict[str, float]] = []
            used_scene = None
            for scene in scenes:
                overlap = intersect(region_bbox, footprint_bbox(scene) or region_bbox)
                if overlap is None:
                    continue
                day = scene["properties"]["datetime"][:10]
                used_scene = scene["id"]

                for tile_bbox in tiles_in(overlap, args.max_tiles - screened):
                    array = fetch_tile(token, tile_bbox, day)
                    if array is None:
                        skipped += 1
                        continue

                    tile_stats.append(tile_statistics(array))
                    started = time.perf_counter()
                    detections = detector.predict(Image.fromarray(array, mode="L"))
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    screened += 1
                    # The v2.2 model is a scene classifier: it returns one
                    # Detection per tile whose signature is the class it
                    # chose. "A detection came back" therefore means "it
                    # answered", not "it found oil" -- counting the former
                    # as a candidate reported 24 of 24 on a run where the
                    # model had in fact said no_anomaly 24 times.
                    for detection in detections:
                        confidences.append(detection.confidence)
                        if detection.signature != PollutionSignature.NO_ANOMALY:
                            candidates += 1

                    log_prediction(
                        db,
                        request_id=f"s1scr_{uuid.uuid4().hex[:12]}",
                        detector_name=detector.name,
                        version=detector.version,
                        latency_ms=latency_ms,
                        detections=detections,
                        endpoint="scripts/screen_sentinel1.py",
                        input_stats={
                            "region": code,
                            "scene_id": used_scene,
                            "acquired_on": day,
                            "bbox": [round(v, 4) for v in tile_bbox],
                            "tile_px": TILE_PX,
                            "out_of_training_distribution": True,
                        },
                        commit=False,
                    )
                if screened >= args.max_tiles:
                    break

            db.commit()
            grand_screened += screened
            grand_candidates += candidates
            all_confidences.extend(confidences)
            all_tile_stats.extend(tile_stats)
            mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
            print(
                f"  {cell.name:24} {screened:3d} tiles screened, "
                f"{candidates:3d} candidate(s), {skipped:2d} skipped, "
                f"mean confidence {mean_conf:.4f}  "
                f"[{used_scene[:38] if used_scene else '-'}]"
            )

    print(
        f"\n{grand_screened} tiles screened, {grand_candidates} candidate(s). "
        "Logged to prediction_logs; no pollution event was created."
    )

    if all_tile_stats:
        mean_of_means = sum(t["mean"] for t in all_tile_stats) / len(all_tile_stats)
        mean_of_stds = sum(t["std"] for t in all_tile_stats) / len(all_tile_stats)
        print(
            f"\nPrepared tiles: mean {mean_of_means:.1f}, "
            f"std {mean_of_stds:.1f}. "
            f"Training patches: mean {TRAINING_PROFILE['mean']:.0f}, "
            f"std {TRAINING_PROFILE['std']:.0f}."
        )
        drift = abs(mean_of_means - TRAINING_PROFILE["mean"])
        if drift > 25:
            print(
                "  These are far from the distribution the model was fitted "
                "on, so its scores do not carry their measured accuracy."
            )

    if all_confidences:
        saturated = sum(c >= SATURATED_ABOVE for c in all_confidences)
        mean_conf = sum(all_confidences) / len(all_confidences)
        print(f"Mean confidence {mean_conf:.4f} over {len(all_confidences)} tiles.")
        if saturated == len(all_confidences):
            print(
                f"\nEVERY tile came back at confidence >= {SATURATED_ABOVE}. "
                "That is not certainty, it is a saturated softmax: on the "
                "patches this model was fitted and measured on, its scores "
                "spread from 0.005 to 0.83. A flat 1.000 across real "
                "Sentinel-1 tiles says the input is unlike anything in "
                "training, so neither the positives nor the negatives from "
                "this run carry weight. The pipeline works end to end; the "
                "model does not transfer to this product without being "
                "retrained on it."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""Windowed Cloud-Optimized GeoTIFF (COG) Crop Extractor and Optical Product Generator.

Retrieves localized 512x512 multi-spectral chips (B02, B03, B04, B05, B08, B11, SCL)
around candidate coordinates from Sentinel-2 Level-2A assets, applies quality screening,
and renders True-Colour, False-Colour, SCL Mask, and NDCI map image products.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.core.config import REPO_ROOT, settings
from app.core.logging import get_logger
from app.vision.copernicus_client import CDSEAuthManager
from app.vision.optical_screener import (
    SCL_CLOUD_HIGH_PROB,
    SCL_CLOUD_MEDIUM_PROB,
    SCL_CLOUD_SHADOWS,
    SCL_NO_DATA,
    SCL_NOT_VEGETATED,
    SCL_THIN_CIRRUS,
    SCL_WATER,
    compute_optical_quality_and_indices,
    render_false_colour,
    render_ndci_map,
    render_scl_mask,
    render_true_colour,
)

logger = get_logger(__name__)

def _marine_root() -> Path:
    """Marine evidence directory, anchored on the configured object store.

    ``REPO_ROOT`` is ``/`` inside the container, so the old constant pointed
    at an unwritable ``/data``. See ``sar_scene_processor._storage_root``.
    """
    configured = Path(settings.water_object_dir)
    base = configured if configured.is_absolute() else REPO_ROOT / configured
    return base / "evidence" / "marine"


EVIDENCE_MARINE_ROOT = _marine_root()


class COGExtractor:
    """Extracts windowed multi-spectral rasters and generates marine optical evidence products."""

    def __init__(self, chip_size: int = 512) -> None:
        self.chip_size = chip_size
        self.auth_manager = CDSEAuthManager.get_instance()

    def _get_target_dir(self, candidate_id: str, scene_id: str) -> Path:
        target_dir = EVIDENCE_MARINE_ROOT / candidate_id / scene_id
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir

    #: The chip's half-width in degrees. At 128 px this is roughly 10 m per
    #: pixel at these latitudes, matching Sentinel-2's native resolution for
    #: the visible and NIR bands.
    CHIP_HALF_DEG = 0.05

    #: How far either side of the SAR acquisition a Sentinel-2 scene may be
    #: taken from. Five days is a little over one revisit, so a candidate
    #: either has a near-contemporaneous optical view or it has none.
    MAX_TEMPORAL_OFFSET_DAYS = 5

    #: Scenes cloudier than this are not worth retrieving. The scene
    #: classification layer removes cloud pixel by pixel afterwards, but a
    #: scene that is mostly cloud leaves too little water to say anything.
    MAX_SCENE_CLOUD_PCT = 60

    BANDS = ("B02", "B03", "B04", "B05", "B08", "B11")

    class NoUsableScene(Exception):
        """No cloud-free Sentinel-2 scene exists close enough in time.

        Raised rather than returning anything. The panel this feeds used to
        synthesise plausible ocean reflectance when a real scene was
        unavailable, which meant an absent observation and a present one
        rendered identically. The caller reports the absence.
        """

    def _fetch_real_bands(
        self,
        lat: float,
        lon: float,
        scene_info: dict[str, Any],
    ) -> tuple[np.ndarray, ...]:
        """Retrieve real Sentinel-2 L2A surface reflectance for one chip.

        Six reflectance bands plus the scene classification layer, in a
        single Process API request returning a TAR of one-band GeoTIFFs.
        One band per output because Pillow cannot open a multi-band float
        TIFF -- a six-band response arrives intact and unreadable.

        Raises:
            NoUsableScene: Copernicus returned nothing usable for this
                location and window.
        """
        import io
        import tarfile

        import httpx

        from app.vision.sentinel2_indices import get_sentinel2_client

        token = get_sentinel2_client()._get_token()
        if not token:
            raise self.NoUsableScene("No Copernicus token available.")

        acquired = scene_info.get("acquisition_time")
        if not acquired:
            raise self.NoUsableScene("Scene carries no acquisition time.")
        moment = datetime.fromisoformat(str(acquired).replace("Z", "+00:00"))
        day = moment.date().isoformat()

        half = self.CHIP_HALF_DEG
        bbox = [lon - half, lat - half, lon + half, lat + half]

        outputs = ",\n      ".join(
            '{id:"%s",bands:1,sampleType:"FLOAT32"}' % band for band in self.BANDS
        )
        returns = ", ".join("%s:[s.%s]" % (band, band) for band in self.BANDS)
        band_list = ",".join('"%s"' % band for band in self.BANDS)
        evalscript = """//VERSION=3
function setup() {
  return {
    input: [{ bands: [%s, "SCL"] }],
    output: [
      %s,
      { id: "scl", bands: 1, sampleType: "UINT8" }
    ]
  };
}
function evaluatePixel(s) { return { %s, scl: [s.SCL] }; }
""" % (band_list, outputs, returns)

        responses = [
            {"identifier": band, "format": {"type": "image/tiff"}}
            for band in self.BANDS
        ] + [{"identifier": "scl", "format": {"type": "image/tiff"}}]

        body = {
            "input": {
                "bounds": {
                    "bbox": bbox,
                    "properties": {
                        "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"
                    },
                },
                "data": [
                    {
                        "type": "sentinel-2-l2a",
                        "dataFilter": {
                            "timeRange": {
                                "from": f"{day}T00:00:00Z",
                                "to": f"{day}T23:59:59Z",
                            },
                            "maxCloudCoverage": self.MAX_SCENE_CLOUD_PCT,
                        },
                    }
                ],
            },
            "output": {
                "width": self.chip_size,
                "height": self.chip_size,
                "responses": responses,
            },
            "evalscript": evalscript,
        }

        try:
            response = httpx.post(
                settings.cdse_process_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    # Without this the API returns only the first output and
                    # the other six bands are silently dropped.
                    "Accept": "application/tar",
                },
                json=body,
                timeout=180.0,
            )
        except Exception as exc:  # noqa: BLE001
            raise self.NoUsableScene(f"{type(exc).__name__} fetching chip") from exc

        if response.status_code != 200 or not response.content:
            raise self.NoUsableScene(
                f"Copernicus returned HTTP {response.status_code} for this chip."
            )

        try:
            archive = tarfile.open(fileobj=io.BytesIO(response.content))
            members = {
                name.replace(".tif", ""): np.array(
                    Image.open(io.BytesIO(archive.extractfile(name).read()))
                )
                for name in archive.getnames()
            }
        except Exception as exc:  # noqa: BLE001
            raise self.NoUsableScene("Chip response could not be read.") from exc

        missing = [b for b in (*self.BANDS, "scl") if b not in members]
        if missing:
            raise self.NoUsableScene(f"Chip response lacked {', '.join(missing)}.")

        bands = [members[b].astype(np.float32) for b in self.BANDS]
        scl = members["scl"].astype(np.uint8)

        # An all-zero chip is outside the scene footprint rather than very
        # dark water, and would read as a perfectly calm, perfectly black sea.
        if all(float(np.nanmax(b)) <= 0.0 for b in bands):
            raise self.NoUsableScene(
                "The scene footprint does not cover this position."
            )

        return (*bands, scl)

    def extract_and_process(
        self,
        candidate_id: str,
        lat: float,
        lon: float,
        scene_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract multi-spectral window, evaluate quality, and render evidence products.

        Returns complete evidence dictionary with file paths, quality metrics, and status.
        """
        scene_id = scene_info.get("scene_id") or "S2_UNKNOWN_SCENE"
        target_dir = self._get_target_dir(candidate_id, scene_id)

        # Define product filenames
        rgb_path = target_dir / "truecolour.png"
        false_color_path = target_dir / "falsecolour.png"
        scl_path = target_dir / "scl_mask.png"
        ndci_path = target_dir / "ndci_map.png"
        summary_path = target_dir / "summary.json"

        # 1. Real Sentinel-2 L2A surface reflectance. Raises NoUsableScene
        #    rather than substituting anything if none is available.
        b02, b03, b04, b05, b08, b11, scl = self._fetch_real_bands(lat, lon, scene_info)

        # 2. Compute quality metrics and spectral indices
        metrics, ndci_water, ndti_water = compute_optical_quality_and_indices(
            b02, b03, b04, b05, b08, b11, scl
        )

        # 3. Render and save all visual products
        render_true_colour(b04, b03, b02, rgb_path)
        render_false_colour(b11, b08, b04, false_color_path)
        render_scl_mask(scl, scl_path)
        render_ndci_map(ndci_water, scl, ndci_path)

        # 4. Serialize summary JSON
        summary_data = {
            "candidate_id": candidate_id,
            "scene_id": scene_id,
            "platform": scene_info.get("platform", "sentinel-2"),
            "acquisition_time": scene_info.get("acquisition_time"),
            "temporal_delta_hours": scene_info.get("temporal_delta_hours"),
            "temporal_window": scene_info.get("temporal_window"),
            "chip_size_pixels": self.chip_size,
            "coordinates": {"latitude": lat, "longitude": lon},
            "metrics": metrics.to_dict(),
            "rendered_products": {
                "truecolour_rgb": str(rgb_path),
                "falsecolour_swir": str(false_color_path),
                "scl_quality_mask": str(scl_path),
                "ndci_chlorophyll_map": str(ndci_path),
            },
        }

        with open(summary_path, "w", encoding="utf-8") as sf:
            json.dump(summary_data, sf, indent=2)

        logger.info(
            "Generated optical evidence for candidate %s, scene %s: flag=%s, water=%.1f%%, cloud=%.1f%%",
            candidate_id,
            scene_id,
            metrics.optical_quality_flag,
            metrics.water_fraction * 100,
            metrics.cloud_fraction * 100,
        )

        return {
            "candidate_id": candidate_id,
            "scene_id": scene_id,
            "platform": scene_info.get("platform", "sentinel-2"),
            "acquisition_time": scene_info.get("acquisition_time"),
            "temporal_delta_hours": scene_info.get("temporal_delta_hours"),
            "temporal_window": scene_info.get("temporal_window"),
            "scene_cloud_cover_pct": scene_info.get("cloud_cover_pct"),
            "tile_id": scene_info.get("tile_id", ""),
            "metrics": metrics,
            "rgb_thumbnail_path": str(rgb_path),
            "false_color_path": str(false_color_path),
            "scl_mask_path": str(scl_path),
            "ndci_map_path": str(ndci_path),
            "summary_path": str(summary_path),
            "summary_json": summary_data,
            "processing_status": "completed",
        }

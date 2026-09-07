"""Google Earth Engine provider for Sentinel-1 GRD.

The reducer pipeline is carried over from the original notebook, which was the
genuinely good part of that code: filter S1 GRD by bounds/date/mode/polarisation,
take the most recent scene, and reduce mean + p10 + p90 + stdDev of VV over the
cell. Changes:

* Credentials come from settings, never from a literal or an uploaded file.
* Initialisation failures degrade to ``is_available = False`` instead of
  raising at import time.
* Cells with no scene are omitted, not back-filled.
* No classification happens here. This layer returns measurements; the
  detector decides what they mean.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.gee.base import ObservationDTO, SatelliteDataProvider
from app.gee.regions import GridCell
from app.models.enums import EvidenceLevel

logger = get_logger(__name__)

COLLECTION = "COPERNICUS/S1_GRD"


class EarthEngineService(SatelliteDataProvider):
    """Sentinel-1 SAR observations via the Earth Engine Python API."""

    name = "earth-engine-sentinel1"

    def __init__(self) -> None:
        """Defer authentication until the first request."""
        self._ee: Any = None
        self._initialised = False
        self._init_error: str | None = None

    # -- Session -----------------------------------------------------------
    def _initialise(self) -> Any:
        """Authenticate once, lazily. Records failures instead of raising."""
        if self._initialised or self._init_error is not None:
            return self._ee

        if not settings.gee_configured:
            self._init_error = (
                "Earth Engine not configured. Set GEE_ENABLED=true, "
                "GEE_PROJECT_ID, GEE_SERVICE_ACCOUNT and "
                "GOOGLE_APPLICATION_CREDENTIALS."
            )
            logger.info("gee_not_configured")
            return None

        try:
            import ee

            credentials = ee.ServiceAccountCredentials(
                settings.gee_service_account,
                settings.google_application_credentials,
            )
            ee.Initialize(credentials, project=settings.gee_project_id)
            self._ee = ee
            self._initialised = True
            logger.info("gee_initialised", extra={"project": settings.gee_project_id})
        except Exception as exc:
            self._init_error = f"{type(exc).__name__}: {exc}"
            logger.warning("gee_init_failed", extra={"reason": self._init_error})
        return self._ee

    @property
    def is_available(self) -> bool:
        """True when an Earth Engine session is established."""
        return self._initialise() is not None

    # -- Observations ------------------------------------------------------
    def get_observations(
        self, cells: list[GridCell], lookback_days: int | None = None
    ) -> list[ObservationDTO]:
        """Fetch the latest VV statistics for each cell.

        A cell with no scene in the window is skipped. Per-cell failures are
        logged and skipped so one bad cell cannot abort an ingestion run.
        """
        ee = self._initialise()
        if ee is None:
            raise RuntimeError(f"Earth Engine unavailable: {self._init_error}")

        days = lookback_days or settings.ingest_lookback_days
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        end_s, start_s = end.strftime("%Y-%m-%d"), start.strftime("%Y-%m-%d")

        observations: list[ObservationDTO] = []
        for cell in cells:
            try:
                obs = self._observe_cell(ee, cell, start_s, end_s)
                if obs is not None:
                    observations.append(obs)
            except Exception as exc:
                logger.warning(
                    "gee_cell_failed",
                    extra={"cell": cell.code, "error": f"{type(exc).__name__}: {exc}"},
                )
        logger.info(
            "gee_ingest_complete",
            extra={"requested": len(cells), "returned": len(observations)},
        )
        return observations

    def _observe_cell(
        self, ee: Any, cell: GridCell, start: str, end: str
    ) -> ObservationDTO | None:
        """Reduce the most recent VV scene over one cell."""
        bbox = ee.Geometry.Rectangle(cell.bbox)
        collection = (
            ee.ImageCollection(COLLECTION)
            .filterBounds(bbox)
            .filterDate(start, end)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            .select("VV")
            .sort("system:time_start", False)
        )

        count = collection.size().getInfo()
        if count == 0:
            return None

        image = collection.first()
        reducer = (
            ee.Reducer.mean()
            .combine(ee.Reducer.percentile([10, 90]), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True)
            .combine(ee.Reducer.minMax(), sharedInputs=True)
        )
        stats = image.reduceRegion(
            reducer=reducer,
            geometry=bbox,
            scale=settings.ingest_scale_m,
            bestEffort=True,
            maxPixels=int(1e9),
        ).getInfo()

        mean_db = stats.get("VV_mean")
        if mean_db is None:
            # The reducer found no valid pixels (e.g. full masking).
            return None

        props = image.getInfo().get("properties", {})
        acquired = datetime.fromtimestamp(
            props.get("system:time_start", 0) / 1000, tz=UTC
        )
        lat, lon = cell.centroid

        return ObservationDTO(
            cell_code=cell.code,
            cell_name=cell.name,
            collection=COLLECTION,
            platform=(props.get("platform_number") and "Sentinel-1") or "Sentinel-1",
            acquired_at=acquired,
            latitude=lat,
            longitude=lon,
            bbox=cell.bbox,
            area_km2=round(cell.area_km2, 2),
            mean_db=mean_db,
            p10_db=stats.get("VV_p10"),
            p90_db=stats.get("VV_p90"),
            stddev_db=stats.get("VV_stdDev"),
            min_db=stats.get("VV_min"),
            max_db=stats.get("VV_max"),
            scene_id=props.get("system:index"),
            instrument_mode=props.get("instrumentMode"),
            polarisation="VV",
            orbit_pass=props.get("orbitProperties_pass"),
            scale_m=settings.ingest_scale_m,
            scene_count=count,
            evidence_level=EvidenceLevel.OBSERVED,
            extra={"relative_orbit": props.get("relativeOrbitNumber_start")},
        )

    # -- Imagery -----------------------------------------------------------
    def get_thumbnail_url(self, bbox: list[float], dimensions: int = 512) -> str | None:
        """Render the most recent VV scene over ``bbox`` as a greyscale PNG.

        Uses a plain grey ramp rather than the original false-colour palette:
        a viewer inspecting a dark formation needs to read relative
        backscatter, and a rainbow ramp actively obstructs that.
        """
        ee = self._initialise()
        if ee is None:
            return None
        try:
            region = ee.Geometry.Rectangle(bbox)
            image = (
                ee.ImageCollection(COLLECTION)
                .filterBounds(region)
                .filter(ee.Filter.eq("instrumentMode", "IW"))
                .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
                .select("VV")
                .sort("system:time_start", False)
                .first()
            )
            return image.getThumbURL(
                {
                    "min": -25,
                    "max": 0,
                    "region": region,
                    "dimensions": dimensions,
                    "format": "png",
                }
            )
        except Exception as exc:
            logger.warning(
                "gee_thumbnail_failed",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )
            return None

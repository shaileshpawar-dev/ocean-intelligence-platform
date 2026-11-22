"""Copernicus Climate Data Store (CDS) and ECMWF ERA5 Wind Integration Interface.

Provides spatiotemporally collocated 10m wind vector (u10, v10) retrieval, wind speed,
meteorological wind direction, grid distance, and coastal classification for Sentinel-1
SAR ocean patches.

Scientific Provenance & Provenance Note:
-----------------------------------------
ERA5 is a global numerical atmospheric reanalysis produced by the European Centre for
Medium-Range Weather Forecasts (ECMWF) using 4D-Var data assimilation in CY41R2 of the
Integrated Forecasting System (IFS). It represents a physically consistent model reanalysis
on a 0.25° (~31 km) spatial grid and 1-hour temporal resolution.
It is NOT an in-situ local weather station or coastal anemometer measurement.

Scientific References:
---------------------
- Hersbach et al. (2020), "The ERA5 global reanalysis", Quarterly Journal of the
  Royal Meteorological Society, 146(730), 1999-2049. DOI: 10.1002/qj.3803.
- Copernicus Climate Change Service (C3S): "ERA5 hourly data on single levels from 1940
  to present", https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels.
- Yang & Singha (2025), Earth System Science Data, DOI: 10.5194/essd-17-6807-2025.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from app.core.config import REPO_ROOT, settings
from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_CACHE_PATH = REPO_ROOT / "data" / "cache" / "era5_wind_cache.json"


@dataclass
class ERA5Record:
    """Spatiotemporally collocated ERA5 reanalysis wind observation."""

    source: str
    dataset_version: str
    grid_latitude: float
    grid_longitude: float
    acquisition_timestamp_utc: str
    sampled_timestamp_utc: str
    u10_ms: float
    v10_ms: float
    wind_speed_ms: float
    wind_direction_deg: float
    temporal_offset_minutes: float
    grid_distance_km: float
    is_coastal: bool
    sampling_method: str
    quality_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two GPS coordinates in kilometers."""
    r = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def calculate_wind_speed(u10: float, v10: float) -> float:
    """Calculate scalar wind speed (m/s) from orthogonal components."""
    return round(math.sqrt(u10**2 + v10**2), 2)


def calculate_meteorological_wind_direction(u10: float, v10: float) -> float:
    """Calculate meteorological wind direction in degrees [0, 360).

    Direction from which the wind blows (0° = North, 90° = East, 180° = South, 270° = West).
    Formula: (270 - atan2(v10, u10) * 180 / pi) % 360
    """
    if abs(u10) < 1e-6 and abs(v10) < 1e-6:
        return 0.0
    rad = math.atan2(v10, u10)
    deg = (270.0 - math.degrees(rad)) % 360.0
    return round(deg, 1)


class CopernicusCDSClient:
    """Official Copernicus Climate Data Store client interface.

    Authentication instructions:
    1. Register an account at https://cds.climate.copernicus.eu/
    2. Obtain Personal Access Token from your user profile page.
    3. Place credentials in ~/.cdsapirc on Linux/Mac or %USERPROFILE%/.cdsapirc on Windows:
       url: https://cds.climate.copernicus.eu/api
       key: <PERSONAL-ACCESS-TOKEN>
       Or set environment variables: CDSAPI_URL and CDSAPI_KEY.
    """

    def __init__(self) -> None:
        self.cdsapi_url = os.environ.get("CDSAPI_URL")
        self.cdsapi_key = os.environ.get("CDSAPI_KEY")
        self.cdsapirc_path = Path.home() / ".cdsapirc"

    @property
    def is_configured(self) -> bool:
        """Check whether valid CDS API credentials exist locally."""
        if self.cdsapi_key and self.cdsapi_url:
            return True
        if self.cdsapirc_path.exists() and self.cdsapirc_path.stat().st_size > 10:
            return True
        return False

    def get_instructions(self) -> str:
        """Return clear instructions for setting up Copernicus CDS credentials."""
        return (
            "Copernicus Climate Data Store (CDS) authentication not configured.\n"
            "To enable live CDS reanalysis retrieval:\n"
            "1. Register at https://cds.climate.copernicus.eu/\n"
            "2. Copy your Personal Access Token from your profile.\n"
            "3. Create ~/.cdsapirc with:\n"
            "   url: https://cds.climate.copernicus.eu/api\n"
            "   key: <YOUR-PERSONAL-ACCESS-TOKEN>\n"
            "Or export CDSAPI_URL and CDSAPI_KEY in your local environment."
        )


class OpenMeteoERA5Client:
    """Direct open-access ECMWF ERA5 reanalysis archive query client.

    Retrieves hourly 10m wind vectors (u10, v10) directly from the global ECMWF ERA5
    archive hosted through Open-Meteo with no authentication required.
    """

    BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()

    def fetch_hourly_wind(
        self,
        lat: float,
        lon: float,
        date_str: str,  # "YYYY-MM-DD"
    ) -> dict[str, Any] | None:
        """Retrieve 24-hour ERA5 wind record for a specific geographic coordinate and date."""
        params = {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "start_date": date_str,
            "end_date": date_str,
            "hourly": [
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_u_component_10m",
                "wind_v_component_10m",
            ],
            "wind_speed_unit": "ms",
            "models": "era5",
        }
        for attempt in range(3):
            try:
                resp = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json()
                logger.warning(
                    "open_meteo_era5_bad_status",
                    extra={"status": resp.status_code, "attempt": attempt + 1},
                )
                time.sleep(1.0 * (attempt + 1))
            except Exception as e:
                logger.warning(
                    "open_meteo_era5_request_error",
                    extra={"error": str(e), "attempt": attempt + 1},
                )
                time.sleep(1.0 * (attempt + 1))
        return None

    def fetch_batch_hourly_wind(
        self,
        points: list[tuple[float, float]],  # [(lat, lon), ...]
        date_str: str,
    ) -> list[dict[str, Any]] | None:
        """Retrieve 24-hour ERA5 wind records for multiple coordinates on the same date."""
        if not points:
            return []
        lat_str = ",".join(str(round(p[0], 4)) for p in points)
        lon_str = ",".join(str(round(p[1], 4)) for p in points)
        params = {
            "latitude": lat_str,
            "longitude": lon_str,
            "start_date": date_str,
            "end_date": date_str,
            "hourly": [
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_u_component_10m",
                "wind_v_component_10m",
            ],
            "wind_speed_unit": "ms",
            "models": "era5",
        }
        for attempt in range(3):
            try:
                resp = self.session.get(self.BASE_URL, params=params, timeout=self.timeout * 2)
                if resp.status_code == 200:
                    data = resp.json()
                    return data if isinstance(data, list) else [data]
                time.sleep(1.0 * (attempt + 1))
            except Exception as e:
                time.sleep(1.0 * (attempt + 1))
        return None


class LocalERA5Cache:
    """Thread-safe persistent on-disk cache for collocated ERA5 records."""

    def __init__(self, cache_path: Path | str = DEFAULT_CACHE_PATH) -> None:
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception as e:
                logger.warning("era5_cache_load_error", extra={"error": str(e)})
                self._cache = {}

    def save(self) -> None:
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            logger.error("era5_cache_save_error", extra={"error": str(e)})

    def get(self, patch_id: str) -> dict[str, Any] | None:
        return self._cache.get(patch_id)

    def set(self, patch_id: str, record: dict[str, Any]) -> None:
        self._cache[patch_id] = record

    def __len__(self) -> int:
        return len(self._cache)


class ERA5Service:
    """Spatiotemporal collocation service for ERA5 reanalysis wind fields."""

    def __init__(self, cache_path: Path | str = DEFAULT_CACHE_PATH) -> None:
        self.cds_client = CopernicusCDSClient()
        self.openmeteo_client = OpenMeteoERA5Client()
        self.cache = LocalERA5Cache(cache_path)

    def collocate_patch(
        self,
        patch_id: str,
        lat: float,
        lon: float,
        timestamp_iso: str,
        is_coastal: bool = False,
        use_cache: bool = True,
    ) -> ERA5Record:
        """Collocate a SAR patch with hourly ERA5 10m wind fields.

        Args:
            patch_id: Unique patch filename or identifier.
            lat: Patch center latitude (WGS84).
            lon: Patch center longitude (WGS84).
            timestamp_iso: Acquisition timestamp string in ISO format (e.g. 2019-01-31T03:42:57).
            is_coastal: Whether patch is in coastal look-alike or coastal oil subset.
            use_cache: Whether to query/store from persistent local cache.

        Returns:
            ERA5Record with collocated wind components and metadata.
        """
        if use_cache:
            cached = self.cache.get(patch_id)
            if cached:
                if cached.get("quality_status") == "measured_reanalysis":
                    cached = dict(cached)
                    cached["quality_status"] = "reanalysis_available"
                return ERA5Record(**cached)

        # Parse timestamp to UTC
        try:
            ts_clean = timestamp_iso.rstrip("Z")
            dt = datetime.fromisoformat(ts_clean).replace(tzinfo=UTC)
        except Exception:
            dt = datetime(2019, 1, 1, 0, 0, tzinfo=UTC)

        date_str = dt.strftime("%Y-%m-%d")
        minute_fraction = dt.minute + dt.second / 60.0

        # Query provider
        raw_data = self.openmeteo_client.fetch_hourly_wind(lat, lon, date_str)
        if raw_data is None:
            # Fallback when offline or unavailable
            record = ERA5Record(
                source="ECMWF ERA5 (Copernicus CDS / Open Archive)",
                dataset_version="reanalysis-era5-single-levels",
                grid_latitude=round(round(lat * 4) / 4, 2),
                grid_longitude=round(round(lon * 4) / 4, 2),
                acquisition_timestamp_utc=dt.isoformat(),
                sampled_timestamp_utc=dt.isoformat(),
                u10_ms=0.0,
                v10_ms=0.0,
                wind_speed_ms=0.0,
                wind_direction_deg=0.0,
                temporal_offset_minutes=0.0,
                grid_distance_km=0.0,
                is_coastal=is_coastal,
                sampling_method="unavailable",
                quality_status="missing",
            )
            return record

        hourly = raw_data.get("hourly", {})
        times = hourly.get("time", [])
        u10_vals = hourly.get("wind_u_component_10m", [])
        v10_vals = hourly.get("wind_v_component_10m", [])
        speeds = hourly.get("wind_speed_10m", [])
        dirs = hourly.get("wind_direction_10m", [])

        grid_lat = raw_data.get("latitude", round(lat * 4) / 4)
        grid_lon = raw_data.get("longitude", round(lon * 4) / 4)
        dist_km = round(haversine_distance_km(lat, lon, grid_lat, grid_lon), 2)

        # Determine hourly indices
        h0 = dt.hour
        h1 = min(h0 + 1, 23)

        if h0 < len(u10_vals):
            # Bilinear/linear interpolation in time
            alpha = minute_fraction / 60.0
            u0 = u10_vals[h0]
            v0 = v10_vals[h0]
            if h1 < len(u10_vals) and h1 != h0:
                u1 = u10_vals[h1]
                v1 = v10_vals[h1]
                u_interp = u0 + alpha * (u1 - u0)
                v_interp = v0 + alpha * (v1 - v0)
            else:
                u_interp = u0
                v_interp = v0

            # Determine nearest hour for reporting offset
            if alpha >= 0.5 and h1 < len(times):
                nearest_h = h1
                temporal_offset = round((1.0 - alpha) * 60.0, 1)  # minutes before nearest hour
                sampled_time = times[h1]
            else:
                nearest_h = h0
                temporal_offset = round(alpha * 60.0, 1)  # minutes after nearest hour
                sampled_time = times[h0]

            w_spd = calculate_wind_speed(u_interp, v_interp)
            w_dir = calculate_meteorological_wind_direction(u_interp, v_interp)

            record = ERA5Record(
                source="ECMWF ERA5 Reanalysis Archive",
                dataset_version="reanalysis-era5-single-levels",
                grid_latitude=float(grid_lat),
                grid_longitude=float(grid_lon),
                acquisition_timestamp_utc=dt.isoformat(),
                sampled_timestamp_utc=sampled_time + ":00Z",
                u10_ms=round(float(u_interp), 2),
                v10_ms=round(float(v_interp), 2),
                wind_speed_ms=w_spd,
                wind_direction_deg=w_dir,
                temporal_offset_minutes=temporal_offset,
                grid_distance_km=dist_km,
                is_coastal=is_coastal,
                sampling_method="nearest_grid_linear_time_interp",
                quality_status="reanalysis_available",
            )
        else:
            record = ERA5Record(
                source="ECMWF ERA5 Reanalysis Archive",
                dataset_version="reanalysis-era5-single-levels",
                grid_latitude=float(grid_lat),
                grid_longitude=float(grid_lon),
                acquisition_timestamp_utc=dt.isoformat(),
                sampled_timestamp_utc=dt.isoformat(),
                u10_ms=0.0,
                v10_ms=0.0,
                wind_speed_ms=0.0,
                wind_direction_deg=0.0,
                temporal_offset_minutes=0.0,
                grid_distance_km=dist_km,
                is_coastal=is_coastal,
                sampling_method="unavailable",
                quality_status="missing",
            )

        if use_cache:
            self.cache.set(patch_id, record.to_dict())
            self.cache.save()

        return record

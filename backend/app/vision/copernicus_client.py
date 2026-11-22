"""Copernicus Data Space Ecosystem (CDSE) STAC v1 client.

Provides discovery, point-in-polygon spatial matching, token-based authentication,
and asset mapping for Sentinel-2 Level-2A Bottom-of-Atmosphere optical imagery.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.config import REPO_ROOT, settings
from app.core.logging import get_logger

logger = get_logger(__name__)

def _cache_dir() -> Path:
    """Where STAC responses are cached, honouring the configured cache dir.

    ``REPO_ROOT`` is ``/`` inside the container, so the old constant pointed
    at an unwritable ``/data`` and this module could not even be imported
    there. Third occurrence of the same trap -- see
    ``sar_scene_processor._storage_root`` and ``cog_extractor._marine_root``.
    """
    configured = Path(settings.water_cache_dir)
    base = configured if configured.is_absolute() else REPO_ROOT / configured
    return base / "cdse_stac"


CACHE_DIR = _cache_dir()
# Created on first use, not at import. A directory that cannot be made is a
# problem for whoever caches a response, not a reason for the module to be
# unimportable -- which is what took the whole optical panel down.


def point_in_polygon(x: float, y: float, poly_coords: list[list[float]]) -> bool:
    """Ray-casting algorithm for point-in-polygon spatial verification."""
    n = len(poly_coords)
    inside = False
    if n < 3:
        return False
    p1x, p1y = poly_coords[0]
    for i in range(n + 1):
        p2x, p2y = poly_coords[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def point_in_geometry(lon: float, lat: float, geometry: dict[str, Any] | None) -> bool:
    """Verify whether (lon, lat) intersects GeoJSON Polygon or MultiPolygon."""
    if not geometry:
        return False
    gtype = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if gtype == "Polygon" and coords:
        return point_in_polygon(lon, lat, coords[0])
    elif gtype == "MultiPolygon" and coords:
        return any(point_in_polygon(lon, lat, poly[0]) for poly in coords if poly)
    return False


class CDSEAuthManager:
    """Manages OpenID Connect (OIDC) authentication tokens for Copernicus Data Space."""

    _instance: CDSEAuthManager | None = None

    def __init__(self) -> None:
        self.access_token: str | None = None
        self.expires_at: float = 0.0

    @classmethod
    def get_instance(cls) -> CDSEAuthManager:
        if cls._instance is None:
            cls._instance = CDSEAuthManager()
        return cls._instance

    @property
    def is_configured(self) -> bool:
        """True if user credentials exist in configuration."""
        return bool(settings.cdse_username and settings.cdse_password)

    def get_valid_token(self) -> str | None:
        """Retrieve cached access token or request a fresh token if expired."""
        if not self.is_configured:
            return None

        # If token is still valid (with 60-second grace buffer), reuse it
        now = time.time()
        if self.access_token and now < (self.expires_at - 60):
            return self.access_token

        # Acquire new token
        try:
            payload = {
                "grant_type": "password",
                "client_id": "cdse-public",
                "username": settings.cdse_username,
                "password": settings.cdse_password,
            }
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(settings.cdse_token_url, data=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    self.access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 600)
                    self.expires_at = now + expires_in
                    logger.info("Successfully acquired Copernicus OIDC session token (valid for %ss)", expires_in)
                    return self.access_token
                else:
                    logger.warning("Failed to authenticate with CDSE: HTTP %s (%s)", resp.status_code, resp.text[:120])
                    return None
        except Exception as exc:
            logger.error("Exception requesting CDSE access token: %s", exc)
            return None


class CopernicusSTACClient:
    """Client for querying Sentinel-2 Level-2A imagery in Copernicus Data Space."""

    def __init__(self) -> None:
        self.base_url = settings.cdse_stac_url.rstrip("/")
        self.collection = "sentinel-2-l2a"
        self.auth_manager = CDSEAuthManager.get_instance()

    def _get_cache_path(self, lon: float, lat: float, t_min_str: str, t_max_str: str) -> Path:
        key = f"stac_{lon:.4f}_{lat:.4f}_{t_min_str}_{t_max_str}.json".replace(":", "-")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return CACHE_DIR / key

    def search_scenes(
        self,
        lon: float,
        lat: float,
        start_time: datetime,
        end_time: datetime,
        limit: int = 50,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Search CDSE STAC for Sentinel-2 L2A granules intersecting (lon, lat)."""
        t_min_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        t_max_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        cache_path = self._get_cache_path(lon, lat, t_min_str, t_max_str)

        if use_cache and cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached_features = json.load(f)
                    return cached_features
            except Exception as e:
                logger.warning("Failed to read cache %s: %s", cache_path, e)

        search_url = f"{self.base_url}/search"
        payload = {
            "collections": [self.collection],
            "intersects": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
            "datetime": f"{t_min_str}/{t_max_str}",
            "limit": limit,
        }

        headers = {}
        token = self.auth_manager.get_valid_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        retries = 3
        for attempt in range(retries):
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.post(search_url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_features = data.get("features", [])
                        
                        # Filter to verified point-in-geometry intersections
                        verified_features = []
                        for f in raw_features:
                            if point_in_geometry(lon, lat, f.get("geometry")):
                                verified_features.append(f)

                        # Write to local cache
                        if use_cache:
                            try:
                                with open(cache_path, "w", encoding="utf-8") as cf:
                                    json.dump(verified_features, cf)
                            except Exception as ce:
                                logger.warning("Failed to write STAC cache: %s", ce)

                        return verified_features
                    elif resp.status_code in (429, 500, 502, 503):
                        time.sleep(1.5 * (attempt + 1))
                    else:
                        logger.warning("CDSE STAC query returned HTTP %s: %s", resp.status_code, resp.text[:120])
                        return []
            except Exception as ex:
                logger.warning("CDSE STAC search attempt %s failed: %s", attempt + 1, ex)
                time.sleep(1.5 * (attempt + 1))

        return []

    def get_candidate_optical_scenes(
        self,
        lat: float,
        lon: float,
        sar_timestamp: datetime,
        primary_window_days: float = 3.0,
        # Five days is a little over one Sentinel-2 revisit. Beyond that a
        # scene is not describing the same water the radar saw: a slick
        # moves, disperses and weathers within days, so a "match" ten days
        # out illustrates the location rather than the event.
        secondary_window_days: float = 5.0,
    ) -> list[dict[str, Any]]:
        """Find, align, and grade all Sentinel-2 Level-2A scenes matching a SAR candidate."""
        if sar_timestamp.tzinfo is None:
            sar_timestamp = sar_timestamp.replace(tzinfo=UTC)

        start_time = sar_timestamp - timedelta(days=secondary_window_days)
        end_time = sar_timestamp + timedelta(days=secondary_window_days)

        features = self.search_scenes(lon, lat, start_time, end_time)
        matched_scenes: list[dict[str, Any]] = []

        for f in features:
            f_id = f.get("id", "")
            props = f.get("properties", {})
            s2_dt_str = props.get("datetime")
            if not s2_dt_str:
                continue
            s2_dt = datetime.fromisoformat(s2_dt_str.replace("Z", "+00:00"))
            
            delta_seconds = (s2_dt - sar_timestamp).total_seconds()
            abs_delta_seconds = abs(delta_seconds)
            delta_hours = round(delta_seconds / 3600.0, 2)
            delta_days = round(abs_delta_seconds / 86400.0, 2)

            is_primary = abs_delta_seconds <= (primary_window_days * 86400.0)
            window_type = "primary_3d" if is_primary else "secondary_10d"

            cloud_cover = props.get("eo:cloud_cover", 0.0)
            if cloud_cover < 10.0:
                cloud_cat = "clean"
            elif cloud_cover < 20.0:
                cloud_cat = "moderate"
            elif cloud_cover < 50.0:
                cloud_cat = "contaminated"
            else:
                cloud_cat = "covered"

            # Grade matching utility
            if is_primary and cloud_cover < 20.0:
                quality_grade = "High Quality (<=3d, <20% cloud)"
            elif is_primary:
                quality_grade = "Sub-optimal (<=3d, >=20% cloud)"
            elif cloud_cover < 20.0:
                quality_grade = "Context Only (3-10d, <20% cloud)"
            else:
                quality_grade = "Context Only (3-10d, >=20% cloud)"

            assets = f.get("assets", {})
            available_bands = [
                b for b in ["B02_10m", "B03_10m", "B04_10m", "B08_10m", "B05_20m", "B06_20m", "B07_20m", "B11_20m", "B12_20m", "SCL_20m", "TCI_10m"]
                if b in assets
            ]

            # Tile identification
            tile_id = ""
            if "_T" in f_id:
                parts = f_id.split("_")
                for p in parts:
                    if p.startswith("T") and len(p) == 6:
                        tile_id = p
                        break

            matched_scenes.append({
                "scene_id": f_id,
                "platform": props.get("platform", "sentinel-2"),
                "acquisition_time": s2_dt_str,
                "temporal_delta_hours": delta_hours,
                "temporal_delta_days": delta_days,
                "temporal_window": window_type,
                "cloud_cover_pct": cloud_cover,
                "cloud_category": cloud_cat,
                "quality_grade": quality_grade,
                "tile_id": tile_id,
                "available_bands": available_bands,
                "has_scl": "SCL_20m" in assets or "SCL" in assets,
                "bbox": f.get("bbox", []),
                "geometry": f.get("geometry"),
                "assets": {k: {"href": v.get("href"), "type": v.get("type")} for k, v in assets.items() if k in available_bands or k == "PRODUCT"},
                "is_best_match": False,
            })

        # Determine best match
        if matched_scenes:
            # Prefer primary with low cloud (<20%), then closest delta
            primary_clean = [s for s in matched_scenes if s["temporal_window"] == "primary_3d" and s["cloud_cover_pct"] < 20.0]
            if primary_clean:
                best = min(primary_clean, key=lambda s: abs(s["temporal_delta_hours"]))
            else:
                primary_any = [s for s in matched_scenes if s["temporal_window"] == "primary_3d"]
                if primary_any:
                    best = min(primary_any, key=lambda s: abs(s["temporal_delta_hours"]))
                else:
                    best = min(matched_scenes, key=lambda s: abs(s["temporal_delta_hours"]))
            best["is_best_match"] = True

        # Sort: best match first, then ascending absolute temporal offset
        matched_scenes.sort(key=lambda s: (not s["is_best_match"], abs(s["temporal_delta_hours"])))
        return matched_scenes

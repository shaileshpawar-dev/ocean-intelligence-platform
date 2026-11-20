"""Pydantic schemas for full-scene Sentinel-1 SAR processing and inference."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SARSceneListItem(BaseModel):
    """Summary of an indexed Sentinel-1 SAR scene."""

    scene_id: str
    platform: str
    polarization: str
    acquisition_time: datetime
    bbox: list[float]  # [min_lon, min_lat, max_lon, max_lat]
    candidate_count: int
    is_processed: bool
    candidate_tiles_detected: int | None = None
    footprints_geojson_url: str
    heatmap_url: str


class SARSceneListResponse(BaseModel):
    """Paginated list of available Sentinel-1 SAR scenes."""

    total: int
    scenes: list[SARSceneListItem]


class ProcessSARSceneIn(BaseModel):
    """Parameters for running overlapping-window tiled inference across a SAR scene."""

    confidence_threshold: float = Field(default=0.50, ge=0.10, le=0.99)
    tile_size: int = Field(default=256, ge=128, le=1024)
    overlap_pct: float = Field(default=0.25, ge=0.0, le=0.50)


class SARSceneProcessOut(BaseModel):
    """Result of full-scene tiled SAR inference."""

    scene_id: str
    total_tiles: int
    candidates_count: int
    processing_duration_seconds: float
    footprints_geojson_url: str
    heatmap_url: str
    metadata: dict[str, Any]

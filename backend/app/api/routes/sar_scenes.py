"""FastAPI router for full-scene Sentinel-1 SAR intelligence and tiled inference."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.sar_scene import (
    ProcessSARSceneIn,
    SARSceneListItem,
    SARSceneListResponse,
    SARSceneProcessOut,
)
from app.services import sar_scene_service

router = APIRouter(prefix="/sar-scenes", tags=["sar-scenes"])


@router.get("", response_model=SARSceneListResponse)
def list_sar_scenes(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, description="Search by scene ID or platform"),
    db: Session = Depends(get_db),
) -> SARSceneListResponse:
    """List indexed Sentinel-1 SAR acquisition scenes with candidate metrics and processing status."""
    return sar_scene_service.list_sar_scenes(
        db=db,
        limit=limit,
        offset=offset,
        search=search,
    )


@router.get("/{scene_id}", response_model=dict[str, Any])
def get_sar_scene_metadata(
    scene_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve full acquisition metadata, polarization, and calibration config for a SAR scene."""
    metadata = sar_scene_service.get_sar_scene_metadata(db=db, scene_id=scene_id)
    return metadata.to_dict()


@router.post("/{scene_id}/process", response_model=SARSceneProcessOut)
def process_sar_scene(
    scene_id: str,
    payload: ProcessSARSceneIn = ProcessSARSceneIn(),
    db: Session = Depends(get_db),
) -> SARSceneProcessOut:
    """Execute overlapping sliding-window tiled inference across the SAR scene."""
    return sar_scene_service.process_sar_scene(
        db=db,
        scene_id=scene_id,
        confidence_threshold=payload.confidence_threshold,
        tile_size=payload.tile_size,
        overlap_pct=payload.overlap_pct,
    )


@router.get("/{scene_id}/footprints")
def get_sar_scene_footprints(
    scene_id: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Retrieve GeoJSON candidate footprints with confidence, contrast, and tile coordinates.

    Automatically triggers tiled inference if scene has not yet been processed.
    """
    geojson = sar_scene_service.get_scene_footprints(db=db, scene_id=scene_id)
    return JSONResponse(content=geojson)


@router.get("/{scene_id}/heatmap")
def get_sar_scene_heatmap(
    scene_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Retrieve stitched full-scene probability heatmap PNG for geospatial map overlay.

    Automatically triggers tiled inference and 2D Hanning blending if not yet processed.
    """
    heatmap_path = sar_scene_service.get_scene_heatmap_path(db=db, scene_id=scene_id)
    if not heatmap_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Heatmap for scene {scene_id} could not be generated.",
        )
    return FileResponse(
        heatmap_path,
        media_type="image/png",
        filename=f"{scene_id}_heatmap.png",
    )

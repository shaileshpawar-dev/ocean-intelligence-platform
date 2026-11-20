"""Service layer for full-scene Sentinel-1 SAR processing and discovery."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.sar_candidate import SARCandidate
from app.schemas.sar_scene import (
    SARSceneListItem,
    SARSceneListResponse,
    SARSceneProcessOut,
)
from app.vision.sar_scene_processor import (
    SCENE_STORAGE_ROOT,
    FullSceneSARProcessor,
    SARSceneMetadata,
)

logger = get_logger(__name__)


def _normalize_scene_id(raw_scene_id: str) -> str:
    """Normalize raw SAFE granule name into standard scene identifier."""
    cleaned = raw_scene_id.strip()
    if ";" in cleaned:
        cleaned = cleaned.split(";")[0].strip()
    if cleaned.endswith(".SAFE"):
        cleaned = cleaned[:-5]
    return cleaned


def _parse_scene_timestamp(scene_id: str) -> datetime:
    """Extract UTC timestamp from standard Sentinel-1 SAFE naming convention."""
    try:
        parts = scene_id.split("_")
        if len(parts) >= 5 and "T" in parts[4]:
            return datetime.strptime(parts[4], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    except Exception:
        pass
    return datetime.now(UTC)


def list_sar_scenes(
    db: Session,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
) -> SARSceneListResponse:
    """List indexed Sentinel-1 SAR scenes with candidate aggregates and processing status."""
    # Query distinct scenes from candidate database
    query = (
        select(
            SARCandidate.safe_scene,
            func.count(SARCandidate.id).label("cand_count"),
            func.min(SARCandidate.latitude).label("min_lat"),
            func.max(SARCandidate.latitude).label("max_lat"),
            func.min(SARCandidate.longitude).label("min_lon"),
            func.max(SARCandidate.longitude).label("max_lon"),
            func.min(SARCandidate.acquisition_timestamp).label("min_time"),
        )
        .where(SARCandidate.safe_scene.is_not(None))
        .group_by(SARCandidate.safe_scene)
    )

    rows = db.execute(query).all()

    # Aggregate by normalized scene_id
    scene_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        norm_id = _normalize_scene_id(row.safe_scene)
        if norm_id not in scene_map:
            platform = "Sentinel-1A" if norm_id.startswith("S1A") else "Sentinel-1B"
            pol = "VV+VH" if "1SDV" in norm_id else "VV"
            acq_time = row.min_time or _parse_scene_timestamp(norm_id)
            if acq_time.tzinfo is None:
                acq_time = acq_time.replace(tzinfo=UTC)

            # Pad bounding box around candidate points (approx 0.4 degrees for full swath)
            min_lon = max(-180.0, float(row.min_lon) - 0.3)
            max_lon = min(180.0, float(row.max_lon) + 0.3)
            min_lat = max(-90.0, float(row.min_lat) - 0.3)
            max_lat = min(90.0, float(row.max_lat) + 0.3)

            scene_map[norm_id] = {
                "scene_id": norm_id,
                "platform": platform,
                "polarization": pol,
                "acquisition_time": acq_time,
                "bbox": [round(min_lon, 4), round(min_lat, 4), round(max_lon, 4), round(max_lat, 4)],
                "candidate_count": int(row.cand_count),
            }
        else:
            scene_map[norm_id]["candidate_count"] += int(row.cand_count)

    # Also scan disk for scenes that may have been processed independently
    if SCENE_STORAGE_ROOT.exists():
        for scene_folder in SCENE_STORAGE_ROOT.iterdir():
            if scene_folder.is_dir() and scene_folder.name not in scene_map:
                meta_file = scene_folder / "metadata.json"
                if meta_file.exists():
                    try:
                        with open(meta_file, encoding="utf-8") as mf:
                            m = json.load(mf)
                        scene_map[scene_folder.name] = {
                            "scene_id": scene_folder.name,
                            "platform": m.get("platform", "Sentinel-1"),
                            "polarization": m.get("polarization", "VV"),
                            "acquisition_time": datetime.fromisoformat(m["acquisition_time"]) if "acquisition_time" in m else _parse_scene_timestamp(scene_folder.name),
                            "bbox": m.get("bbox", [30.0, 30.0, 35.0, 35.0]),
                            "candidate_count": m.get("candidate_tiles_detected", 0),
                        }
                    except Exception:
                        pass

    # Convert to list and sort by candidate_count descending, then acquisition_time
    scenes_list: list[SARSceneListItem] = []
    for sid, sdata in scene_map.items():
        if search and search.lower() not in sid.lower():
            continue

        scene_dir = SCENE_STORAGE_ROOT / sid
        geojson_path = scene_dir / "candidate_footprints.geojson"
        heatmap_path = scene_dir / "probability_heatmap.png"
        is_processed = geojson_path.exists() and heatmap_path.exists()

        candidate_tiles_detected = None
        if is_processed:
            meta_file = scene_dir / "metadata.json"
            if meta_file.exists():
                try:
                    with open(meta_file, encoding="utf-8") as mf:
                        cand_meta = json.load(mf)
                    candidate_tiles_detected = cand_meta.get("candidate_tiles_detected")
                except Exception:
                    pass

        scenes_list.append(
            SARSceneListItem(
                scene_id=sid,
                platform=sdata["platform"],
                polarization=sdata["polarization"],
                acquisition_time=sdata["acquisition_time"],
                bbox=sdata["bbox"],
                candidate_count=sdata["candidate_count"],
                is_processed=is_processed,
                candidate_tiles_detected=candidate_tiles_detected,
                footprints_geojson_url=f"/api/v1/sar-scenes/{sid}/footprints",
                heatmap_url=f"/api/v1/sar-scenes/{sid}/heatmap",
            )
        )

    scenes_list.sort(key=lambda s: (s.is_processed, s.candidate_count), reverse=True)

    total = len(scenes_list)
    paginated = scenes_list[offset : offset + limit]

    return SARSceneListResponse(total=total, scenes=paginated)


def get_sar_scene_metadata(db: Session, scene_id: str) -> SARSceneMetadata:
    """Retrieve or build complete SAR scene metadata for a given scene identifier."""
    norm_id = _normalize_scene_id(scene_id)
    scene_dir = SCENE_STORAGE_ROOT / norm_id
    meta_path = scene_dir / "metadata.json"

    # If already cached on disk, construct from metadata.json
    if meta_path.exists():
        try:
            with open(meta_path, encoding="utf-8") as mf:
                data = json.load(mf)
            acq_time = datetime.fromisoformat(data["acquisition_time"])
            return SARSceneMetadata(
                scene_id=norm_id,
                platform=data.get("platform", "Sentinel-1B"),
                polarization=data.get("polarization", "VV+VH"),
                acquisition_time=acq_time,
                bbox=data.get("bbox", [31.4, 34.0, 33.6, 35.6]),
                orbit_direction=data.get("orbit_direction", "DESCENDING"),
                incidence_angle_min=data.get("incidence_angle_min", 30.5),
                incidence_angle_max=data.get("incidence_angle_max", 45.2),
                radiometric_calibration=data.get("radiometric_calibration", "sigma0_db"),
                preprocessing_config=data.get("preprocessing_config", {
                    "speckle_filter": "Lee 5x5",
                    "terrain_correction": "Range-Doppler",
                    "pixel_spacing_m": 10.0,
                }),
                model_version=data.get("model_version", "2.2.0-experimental"),
                inference_config=data.get("inference_config", {
                    "tile_size": 256,
                    "overlap_pct": 0.25,
                    "stride": 192,
                    "blending": "2d_hanning",
                }),
            )
        except Exception as exc:
            logger.warning("Error reading scene metadata from disk: %s", exc)

    # Query candidate coordinates in DB
    query = (
        select(
            func.min(SARCandidate.latitude).label("min_lat"),
            func.max(SARCandidate.latitude).label("max_lat"),
            func.min(SARCandidate.longitude).label("min_lon"),
            func.max(SARCandidate.longitude).label("max_lon"),
            func.min(SARCandidate.acquisition_timestamp).label("min_time"),
        )
        .where(SARCandidate.safe_scene.contains(norm_id))
    )
    row = db.execute(query).first()

    platform = "Sentinel-1A" if norm_id.startswith("S1A") else "Sentinel-1B"
    polarization = "VV+VH" if "1SDV" in norm_id else "VV"
    acq_time = _parse_scene_timestamp(norm_id)

    if row and row.min_lat is not None:
        min_lon = max(-180.0, float(row.min_lon) - 0.3)
        max_lon = min(180.0, float(row.max_lon) + 0.3)
        min_lat = max(-90.0, float(row.min_lat) - 0.3)
        max_lat = min(90.0, float(row.max_lat) + 0.3)
        bbox = [round(min_lon, 4), round(min_lat, 4), round(max_lon, 4), round(max_lat, 4)]
        if row.min_time:
            acq_time = row.min_time if row.min_time.tzinfo else row.min_time.replace(tzinfo=UTC)
    else:
        # Mediterranean or Arabian Sea default bounding box
        bbox = [31.4, 34.0, 33.6, 35.6]

    return SARSceneMetadata(
        scene_id=norm_id,
        platform=platform,
        polarization=polarization,
        acquisition_time=acq_time,
        bbox=bbox,
        orbit_direction="DESCENDING",
        incidence_angle_min=30.5,
        incidence_angle_max=45.2,
        radiometric_calibration="sigma0_db",
        preprocessing_config={
            "speckle_filter": "Lee 5x5",
            "terrain_correction": "Range-Doppler",
            "pixel_spacing_m": 10.0,
        },
        model_version="2.2.0-experimental",
        inference_config={
            "tile_size": 256,
            "overlap_pct": 0.25,
            "stride": 192,
            "blending": "2d_hanning",
        },
    )


def process_sar_scene(
    db: Session,
    scene_id: str,
    confidence_threshold: float = 0.50,
    tile_size: int = 256,
    overlap_pct: float = 0.25,
) -> SARSceneProcessOut:
    """Execute full-scene overlapping-window tiled inference across a Sentinel-1 scene."""
    metadata = get_sar_scene_metadata(db, scene_id)
    metadata.inference_config["confidence_threshold"] = confidence_threshold
    metadata.inference_config["tile_size"] = tile_size
    metadata.inference_config["overlap_pct"] = overlap_pct

    processor = FullSceneSARProcessor(
        tile_size=tile_size,
        overlap_pct=overlap_pct,
        confidence_threshold=confidence_threshold,
        model_version=metadata.model_version,
    )

    result = processor.process_scene(metadata)
    meta = result["metadata"]

    return SARSceneProcessOut(
        scene_id=metadata.scene_id,
        total_tiles=result["total_tiles"],
        candidates_count=result["candidates_count"],
        processing_duration_seconds=meta.get("processing_duration_seconds", 0.0),
        footprints_geojson_url=f"/api/v1/sar-scenes/{metadata.scene_id}/footprints",
        heatmap_url=f"/api/v1/sar-scenes/{metadata.scene_id}/heatmap",
        metadata=meta,
    )


def get_scene_footprints(db: Session, scene_id: str) -> dict[str, Any]:
    """Retrieve GeoJSON candidate footprints for a scene, processing if not already cached."""
    norm_id = _normalize_scene_id(scene_id)
    geojson_path = SCENE_STORAGE_ROOT / norm_id / "candidate_footprints.geojson"

    if not geojson_path.exists():
        logger.info("Scene %s not yet processed; triggering automatic tiled processing", norm_id)
        process_sar_scene(db, norm_id)

    with open(geojson_path, encoding="utf-8") as gf:
        return json.load(gf)


def get_scene_heatmap_path(db: Session, scene_id: str) -> Path:
    """Retrieve probability heatmap PNG file path, processing if not already cached."""
    norm_id = _normalize_scene_id(scene_id)
    heatmap_path = SCENE_STORAGE_ROOT / norm_id / "probability_heatmap.png"

    if not heatmap_path.exists():
        logger.info("Scene heatmap %s not yet generated; triggering automatic tiled processing", norm_id)
        process_sar_scene(db, norm_id)

    return heatmap_path

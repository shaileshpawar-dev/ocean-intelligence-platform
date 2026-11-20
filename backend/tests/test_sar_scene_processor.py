"""Unit and integration tests for full-scene SAR processing and tiled inference (Phase 14.2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.database import SessionLocal
from app.main import app
from app.models.sar_candidate import SARCandidate
from app.vision.sar_scene_processor import (
    CandidateFootprint,
    FullSceneSARProcessor,
    SARSceneMetadata,
    _create_hanning_window_2d,
)

client = TestClient(app)


def test_hanning_window_blending() -> None:
    """Verify 2D Hanning window tapers to zero at tile borders and peaks at center."""
    size = 256
    window = _create_hanning_window_2d(size)
    assert window.shape == (size, size)
    assert window.dtype == np.float32

    # Edges should be close to 0.0
    assert window[0, 0] == pytest.approx(0.0, abs=1e-4)
    assert window[0, size // 2] == pytest.approx(0.0, abs=1e-4)
    assert window[size - 1, size // 2] == pytest.approx(0.0, abs=1e-4)

    # Center should peak at 1.0
    center_val = window[size // 2, size // 2]
    assert center_val == pytest.approx(1.0, abs=0.01)

    # Diagonal symmetry
    assert np.allclose(window, window.T)


def test_full_scene_processor_execution(tmp_path: Path) -> None:
    """Test overlapping sliding-window inference and geospatial reconstruction."""
    test_scene_id = "S1A_IW_GRDH_1SDV_20190412T035040_TEST_PROC"
    meta = SARSceneMetadata(
        scene_id=test_scene_id,
        platform="Sentinel-1A",
        polarization="VV+VH",
        acquisition_time=datetime(2019, 4, 12, 3, 50, 40, tzinfo=UTC),
        bbox=[31.4, 34.0, 33.6, 35.6],
        orbit_direction="DESCENDING",
        incidence_angle_min=30.5,
        incidence_angle_max=45.2,
        radiometric_calibration="sigma0_db",
        preprocessing_config={"speckle_filter": "Lee 5x5", "terrain_correction": "Range-Doppler"},
        model_version="2.2.0-experimental",
        inference_config={"tile_size": 256, "overlap_pct": 0.25, "stride": 192},
    )

    processor = FullSceneSARProcessor(
        tile_size=256,
        overlap_pct=0.25,
        confidence_threshold=0.50,
        model_version="2.2.0-experimental",
    )

    result = processor.process_scene(meta, scene_raster_shape=(768, 768))

    assert result["scene_id"] == test_scene_id
    assert result["total_tiles"] == 16  # (768-256)/192 = 2.66 -> offsets: 0, 192, 384, 512 (4x4 = 16 tiles)
    assert result["candidates_count"] >= 1

    geojson = result["geojson"]
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == result["candidates_count"]

    # Verify candidate footprint feature properties
    first_feature = geojson["features"][0]
    assert first_feature["type"] == "Feature"
    assert first_feature["geometry"]["type"] == "Polygon"
    assert len(first_feature["geometry"]["coordinates"][0]) == 5  # Closed 5-point polygon
    props = first_feature["properties"]
    assert "footprint_id" in props
    assert props["confidence_p_oil"] >= 0.50
    assert "contrast_db" in props
    assert "mean_backscatter_db" in props
    assert props["screening_status"] == "candidate_requires_review"

    # Verify heatmap PNG file
    heatmap_path = Path(result["heatmap_path"])
    assert heatmap_path.exists()
    with Image.open(heatmap_path) as img:
        assert img.format == "PNG"
        assert img.size == (768, 768)
        assert img.mode == "RGBA"


def test_api_list_sar_scenes() -> None:
    """Test GET /api/v1/sar-scenes returns indexed scenes."""
    response = client.get("/api/v1/sar-scenes?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "scenes" in data
    assert data["total"] >= 1
    assert len(data["scenes"]) <= 10

    first_scene = data["scenes"][0]
    assert "scene_id" in first_scene
    assert "platform" in first_scene
    assert "polarization" in first_scene
    assert "bbox" in first_scene
    assert len(first_scene["bbox"]) == 4
    assert "is_processed" in first_scene
    assert "footprints_geojson_url" in first_scene
    assert "heatmap_url" in first_scene


def test_api_get_scene_metadata() -> None:
    """Test GET /api/v1/sar-scenes/{scene_id} returns acquisition details."""
    list_resp = client.get("/api/v1/sar-scenes?limit=1")
    assert list_resp.status_code == 200
    scene_id = list_resp.json()["scenes"][0]["scene_id"]

    response = client.get(f"/api/v1/sar-scenes/{scene_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["scene_id"] == scene_id
    assert "platform" in data
    assert "polarization" in data
    assert "acquisition_time" in data
    assert "radiometric_calibration" in data
    assert data["radiometric_calibration"] == "sigma0_db"


def test_api_process_and_retrieve_footprints_and_heatmap() -> None:
    """Test POST process, GET footprints GeoJSON, and GET heatmap image."""
    list_resp = client.get("/api/v1/sar-scenes?limit=1")
    scene_id = list_resp.json()["scenes"][0]["scene_id"]

    # Trigger processing
    proc_resp = client.post(
        f"/api/v1/sar-scenes/{scene_id}/process",
        json={"confidence_threshold": 0.50, "tile_size": 256, "overlap_pct": 0.25},
    )
    assert proc_resp.status_code == 200
    proc_data = proc_resp.json()
    assert proc_data["scene_id"] == scene_id
    assert proc_data["total_tiles"] >= 1
    assert "candidates_count" in proc_data

    # Retrieve footprints GeoJSON
    fp_resp = client.get(f"/api/v1/sar-scenes/{scene_id}/footprints")
    assert fp_resp.status_code == 200
    geojson = fp_resp.json()
    assert geojson["type"] == "FeatureCollection"
    assert "features" in geojson

    # Retrieve heatmap PNG
    hm_resp = client.get(f"/api/v1/sar-scenes/{scene_id}/heatmap")
    assert hm_resp.status_code == 200
    assert hm_resp.headers["content-type"] == "image/png"
    assert len(hm_resp.content) > 1000

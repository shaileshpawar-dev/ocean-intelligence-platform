"""Unit and integration tests for Sentinel-2 Optical Evidence API (Phase 14.1)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import SessionLocal
from app.models.sar_candidate import SARCandidate, SARCandidateOpticalEvidence
from app.services.candidate_service import seed_candidates_from_audit
from test_candidate_api import seed_acceptance_fixtures

client = TestClient(app)


class TestOpticalEvidenceAPI:
    """Verifies end-to-end Sentinel-2 optical discovery, extraction, and presentation."""

    @pytest.fixture(autouse=True)
    def setup_fixture(self):
        db = SessionLocal()
        seed_candidates_from_audit(db)
        cand = db.query(SARCandidate).filter_by(candidate_id="cand_test_standard_001").first()
        if not cand:
            seed_acceptance_fixtures(db)
        cand = db.query(SARCandidate).filter_by(candidate_id="cand_test_standard_001").first()
        assert cand is not None, "Test candidate cand_test_standard_001 must exist in DB."
        db.close()

    def test_discover_optical_scenes(self):
        """Verify discovering matching Sentinel-2 scenes for candidate."""
        resp = client.get("/api/v1/sar-candidates/cand_test_standard_001/optical-scenes")
        assert resp.status_code == 200
        scenes = resp.json()
        assert isinstance(scenes, list)
        assert len(scenes) > 0

        # Inspect properties of discovered scenes
        first = scenes[0]
        assert "scene_id" in first
        assert "platform" in first
        assert "temporal_delta_hours" in first
        assert "cloud_cover_pct" in first
        assert "quality_grade" in first
        assert "temporal_window" in first
        assert any(s["is_best_match"] for s in scenes)

    def test_process_optical_evidence(self):
        """Verify processing optical evidence extracts chips, computes metrics, and persists record."""
        payload = {"chip_size": 256}
        resp = client.post(
            "/api/v1/sar-candidates/cand_test_standard_001/optical-evidence/process",
            json=payload,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["candidate_id"] == "cand_test_standard_001"
        assert "scene_id" in data
        assert "optical_quality_flag" in data
        assert data["optical_quality_flag"] in (
            "OPTICAL_VALID_CLEAR",
            "OPTICAL_CLOUD_OBSCURED",
            "OPTICAL_HIGH_ALGAL_CONTEXT",
            "OPTICAL_PARTIALLY_CLOUDED",
            "OPTICAL_LOW_WATER_FRACTION",
        )
        assert data["local_water_fraction"] >= 0.0
        assert data["local_cloud_fraction"] >= 0.0
        assert data["has_rgb_image"] is True
        assert data["has_false_color_image"] is True
        assert data["has_scl_mask"] is True
        assert data["has_ndci_map"] is True
        assert data["processing_status"] == "completed"

    def test_list_and_detail_candidate_optical_evidence(self):
        """Verify optical evidence is listed and included in candidate detail."""
        # 1. Listing endpoint
        resp_list = client.get("/api/v1/sar-candidates/cand_test_standard_001/optical-evidence")
        assert resp_list.status_code == 200
        records = resp_list.json()
        assert len(records) >= 1
        evidence_id = records[0]["id"]

        # 2. Detail drawer endpoint includes optical_evidence array
        resp_detail = client.get("/api/v1/sar-candidates/cand_test_standard_001")
        assert resp_detail.status_code == 200
        detail = resp_detail.json()
        assert "optical_evidence" in detail
        assert len(detail["optical_evidence"]) >= 1
        assert detail["optical_evidence"][0]["id"] == evidence_id

        # 3. Test serving each optical product image
        for ptype in ["rgb", "false_color", "scl", "ndci"]:
            img_resp = client.get(
                f"/api/v1/sar-candidates/cand_test_standard_001/optical-evidence/{evidence_id}/image/{ptype}"
            )
            assert img_resp.status_code == 200, f"Failed serving {ptype} image: {img_resp.text}"
            assert img_resp.headers["content-type"] == "image/png"
            assert len(img_resp.content) > 500

    def test_optical_evidence_nonexistent_candidate(self):
        """Verify 404 for unknown candidate."""
        resp = client.get("/api/v1/sar-candidates/cand_nonexistent_999/optical-scenes")
        assert resp.status_code == 404

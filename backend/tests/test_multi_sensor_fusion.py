"""Unit and integration tests for Multi-Sensor Evidence Fusion Engine (Phase 14.3)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.sar_candidate import SARCandidate
from app.services.candidate_service import seed_candidates_from_audit
from app.vision.multi_sensor import (
    ConcordanceLevel,
    EvidenceConsistency,
    ModalityType,
    MultiSensorIntegrator,
)
from test_candidate_api import seed_acceptance_fixtures

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db() -> None:
    """Ensure candidate fixtures exist in test database."""
    db = SessionLocal()
    seed_candidates_from_audit(db)
    cand = db.query(SARCandidate).filter_by(candidate_id="cand_test_standard_001").first()
    if not cand:
        seed_acceptance_fixtures(db)
    db.close()


def test_multi_sensor_concordance_scoring() -> None:
    """Test multi-sensor physical integration logic across diverse environmental scenarios."""
    integrator = MultiSensorIntegrator()
    base_time = datetime(2019, 7, 31, 8, 36, 0, tzinfo=UTC)

    # Scenario 1: Multi-Sensor Concordance (SAR positive + favorable wind + optical corroboration)
    res_concordant = integrator.integrate(
        candidate_id="cand_test_concordant",
        latitude=34.5,
        longitude=33.2,
        sar_confidence=0.88,
        screening_status="candidate_requires_review",
        model_version="2.2.0-experimental",
        sar_time=base_time,
        wind_speed_ms=6.5,
        wind_direction_deg=180.0,
        era5_temporal_offset_min=10.0,
        optical_evidence={
            "scene_id": "S2B_MSIL2A_TEST_01",
            "acquisition_timestamp": base_time.isoformat(),
            "temporal_offset_hours": 1.2,
            "cloud_coverage_fraction": 0.05,
            "valid_water_fraction": 0.95,
            "mean_ndci": -0.04,
            "p90_ndci": -0.01,
            "mean_swir_ratio": 0.52,  # Anomalous glint contrast
            "optical_quality_flag": "optimal",
        },
    )
    assert res_concordant.concordance_level == ConcordanceLevel.MULTI_SENSOR_CONCORDANCE
    assert res_concordant.concordance_score >= 0.85
    assert len(res_concordant.evidence_items) == 3

    # Scenario 2: Biogenic Look-alike (High NDCI chlorophyll algal bloom)
    res_algae = integrator.integrate(
        candidate_id="cand_test_algae",
        latitude=34.5,
        longitude=33.2,
        sar_confidence=0.82,
        screening_status="candidate_requires_review",
        model_version="2.2.0-experimental",
        sar_time=base_time,
        wind_speed_ms=5.0,
        optical_evidence={
            "scene_id": "S2B_MSIL2A_TEST_02",
            "acquisition_timestamp": base_time.isoformat(),
            "temporal_offset_hours": 0.8,
            "cloud_coverage_fraction": 0.02,
            "valid_water_fraction": 0.98,
            "mean_ndci": 0.14,  # High chlorophyll!
            "p90_ndci": 0.22,
            "mean_swir_ratio": 0.12,
            "optical_quality_flag": "optimal",
        },
    )
    assert res_algae.concordance_level == ConcordanceLevel.BIOGENIC_LOOKALIKE
    assert res_algae.concordance_score <= 0.25
    assert "algal film" in res_algae.triangulation_summary.lower()

    # Scenario 3: Low Wind Calm Sea Ambiguity (< 3 m/s)
    res_low_wind = integrator.integrate(
        candidate_id="cand_test_low_wind",
        latitude=34.5,
        longitude=33.2,
        sar_confidence=0.75,
        screening_status="low_wind_ambiguity_review",
        model_version="2.2.0-experimental",
        sar_time=base_time,
        wind_speed_ms=1.8,
        optical_evidence=None,
    )
    assert res_low_wind.concordance_level == ConcordanceLevel.CALM_WATER_AMBIGUITY
    assert res_low_wind.concordance_score < 0.50

    # Scenario 4: High Wind Dispersion (> 12 m/s)
    res_high_wind = integrator.integrate(
        candidate_id="cand_test_high_wind",
        latitude=34.5,
        longitude=33.2,
        sar_confidence=0.68,
        screening_status="candidate_requires_review",
        model_version="2.2.0-experimental",
        sar_time=base_time,
        wind_speed_ms=14.2,
        optical_evidence=None,
    )
    assert res_high_wind.concordance_level == ConcordanceLevel.DISPERSED_HIGH_WIND
    assert res_high_wind.concordance_score < 0.40


def test_api_get_candidate_fusion() -> None:
    """Test GET /api/v1/sar-candidates/{candidate_id}/fusion endpoint."""
    response = client.get("/api/v1/sar-candidates/cand_test_standard_001/fusion")
    assert response.status_code == 200
    data = response.json()

    assert data["candidate_id"] == "cand_test_standard_001"
    assert "concordance_score" in data
    assert "concordance_level" in data
    assert "triangulation_summary" in data
    assert "recommended_action" in data
    assert "evidence_items" in data
    assert len(data["evidence_items"]) >= 2

    # Verify 404 on nonexistent candidate
    err_resp = client.get("/api/v1/sar-candidates/cand_nonexistent_999/fusion")
    assert err_resp.status_code == 404

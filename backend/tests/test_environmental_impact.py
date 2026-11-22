"""Unit and integration tests for environmental receptors and vulnerability assessment (Phase 17)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.environmental_impact import MarineReceptor
from app.models.sar_candidate import SARCandidate
from app.services.candidate_service import seed_candidates_from_audit
from app.vision.environmental_impact_screener import (
    DEFAULT_MARINE_RECEPTORS,
    EnvironmentalImpactScreener,
    seed_marine_receptors,
)
from test_candidate_api import seed_acceptance_fixtures

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db() -> None:
    """Ensure candidate and receptor test fixtures exist."""
    db = SessionLocal()
    seed_candidates_from_audit(db)
    cand = db.query(SARCandidate).filter_by(candidate_id="cand_test_standard_001").first()
    if not cand:
        seed_acceptance_fixtures(db)
    seed_marine_receptors(db)
    db.close()


def test_seed_marine_receptors() -> None:
    """Verify default ecologically sensitive marine receptors are registered."""
    db = SessionLocal()
    receptors = db.query(MarineReceptor).all()
    assert len(receptors) >= len(DEFAULT_MARINE_RECEPTORS)
    db.close()


def test_environmental_impact_screener_calculation() -> None:
    """Verify spatial vulnerability scoring and severity assignment."""
    db = SessionLocal()
    screener = EnvironmentalImpactScreener()

    # cand_test_standard_001 is at (24.85, 67.01) near Gulf of Kachchh Marine National Park (22.45, 69.40)
    impacts = screener.evaluate_candidate(db, "cand_test_standard_001")
    assert len(impacts) >= 1

    first_impact = impacts[0]
    assert first_impact.candidate_id == "cand_test_standard_001"
    assert first_impact.distance_km > 0.0
    assert 0.0 <= first_impact.vulnerability_score <= 100.0
    assert first_impact.impact_severity in ("CRITICAL", "HIGH", "MODERATE", "LOW")
    assert first_impact.priority_action is not None
    db.close()


def test_api_list_marine_receptors() -> None:
    """Test GET /api/v1/receptors."""
    response = client.get("/api/v1/receptors")
    assert response.status_code == 200
    receptors = response.json()
    assert len(receptors) >= 7

    coral_resp = client.get("/api/v1/receptors?category=CORAL_REEF")
    assert coral_resp.status_code == 200
    corals = coral_resp.json()
    assert len(corals) >= 1
    assert all(c["category"] == "CORAL_REEF" for c in corals)


def test_api_candidate_environmental_impact() -> None:
    """Test GET and POST environmental impact endpoints for a candidate."""
    get_resp = client.get("/api/v1/sar-candidates/cand_test_standard_001/impact")
    assert get_resp.status_code == 200
    data = get_resp.json()

    assert data["candidate_id"] == "cand_test_standard_001"
    assert "max_vulnerability_score" in data
    assert "highest_severity" in data
    assert "impacts" in data
    assert len(data["impacts"]) >= 1

    # Test trigger re-evaluation
    post_resp = client.post("/api/v1/sar-candidates/cand_test_standard_001/impact/evaluate")
    assert post_resp.status_code == 200
    post_data = post_resp.json()
    assert post_data["candidate_id"] == "cand_test_standard_001"
    assert post_data["max_vulnerability_score"] == data["max_vulnerability_score"]

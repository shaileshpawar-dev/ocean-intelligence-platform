"""Unit and integration tests for AIS vessel tracking and candidate trajectory association (Phase 15)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.demo.seed_vessels import seed_vessels_and_tracks
from app.main import app
from app.models.sar_candidate import SARCandidate
from app.models.vessel import Vessel, VesselPosition
from app.services.candidate_service import seed_candidates_from_audit
from app.vision.ais_associator import (
    AISAssociationEngine,
    haversine_distance_km,
    initial_bearing_deg,
    interpolate_position,
)
from test_candidate_api import seed_acceptance_fixtures

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db() -> None:
    """Ensure candidate and vessel test fixtures exist."""
    db = SessionLocal()
    seed_candidates_from_audit(db)
    cand = db.query(SARCandidate).filter_by(candidate_id="cand_test_standard_001").first()
    if not cand:
        seed_acceptance_fixtures(db)
    seed_vessels_and_tracks(db)
    db.close()


def test_haversine_and_bearing_calculation() -> None:
    """Verify spherical geometry formulas."""
    # Distance between Karachi (24.86, 67.00) and Mumbai (18.96, 72.82) is ~885 km
    dist = haversine_distance_km(24.86, 67.00, 18.96, 72.82)
    assert 850.0 < dist < 920.0

    # Bearing from (0, 0) to (1, 0) should be 0 deg (North)
    bearing_north = initial_bearing_deg(0.0, 0.0, 1.0, 0.0)
    assert bearing_north == pytest.approx(0.0, abs=0.5)

    # Bearing from (0, 0) to (0, 1) should be 90 deg (East)
    bearing_east = initial_bearing_deg(0.0, 0.0, 0.0, 1.0)
    assert bearing_east == pytest.approx(90.0, abs=0.5)


def test_trajectory_interpolation() -> None:
    """Verify linear trajectory interpolation between pings."""
    t0 = datetime(2026, 11, 12, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 11, 12, 11, 0, 0, tzinfo=UTC)
    t_mid = datetime(2026, 11, 12, 10, 30, 0, tzinfo=UTC)

    p1 = VesselPosition(
        mmsi="123456789",
        timestamp=t0,
        latitude=20.0,
        longitude=65.0,
        speed_knots=10.0,
    )
    p2 = VesselPosition(
        mmsi="123456789",
        timestamp=t1,
        latitude=21.0,
        longitude=67.0,
        speed_knots=12.0,
    )

    mid_lat, mid_lon, mid_spd = interpolate_position(p1, p2, t_mid)
    assert mid_lat == pytest.approx(20.5, abs=1e-4)
    assert mid_lon == pytest.approx(66.0, abs=1e-4)
    assert mid_spd == pytest.approx(11.0, abs=1e-4)


def test_api_list_vessels_and_detail() -> None:
    """Test vessel registry listing and detail route."""
    response = client.get("/api/v1/vessels")
    assert response.status_code == 200
    vessels = response.json()
    assert len(vessels) >= 6

    first_mmsi = vessels[0]["mmsi"]
    detail_resp = client.get(f"/api/v1/vessels/{first_mmsi}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["mmsi"] == first_mmsi
    assert "positions" in detail
    assert len(detail["positions"]) >= 1


def test_api_candidate_vessel_correlations() -> None:
    """Test candidate vessel association endpoints."""
    # cand_test_standard_001 is near Chem Polaris
    response = client.get("/api/v1/sar-candidates/cand_test_standard_001/vessels")
    assert response.status_code == 200
    assocs = response.json()
    assert len(assocs) >= 1

    primary = next((a for a in assocs if a["is_primary_suspect"]), None)
    assert primary is not None
    assert primary["mmsi"] == "636015000"  # Chem Polaris
    assert primary["association_score"] >= 0.80
    assert primary["spatial_distance_km"] <= 10.0

    # Test trigger re-correlation
    post_resp = client.post("/api/v1/sar-candidates/cand_test_standard_001/vessels/correlate")
    assert post_resp.status_code == 200
    re_assocs = post_resp.json()
    assert len(re_assocs) == len(assocs)

"""Unit and integration tests for Lagrangian oil drift simulation and weathering (Phase 16)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.sar_candidate import SARCandidate
from app.services.candidate_service import seed_candidates_from_audit
from app.vision.lagrangian_drift import LagrangianDriftEngine
from test_candidate_api import seed_acceptance_fixtures

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db() -> None:
    """Ensure candidate test fixtures exist."""
    db = SessionLocal()
    seed_candidates_from_audit(db)
    cand = db.query(SARCandidate).filter_by(candidate_id="cand_test_standard_001").first()
    if not cand:
        seed_acceptance_fixtures(db)
    db.close()


def test_lagrangian_drift_physics() -> None:
    """Verify Lagrangian advection, random walk diffusion, and weathering mass balance."""
    engine = LagrangianDriftEngine()
    start_time = datetime(2026, 11, 12, 0, 0, 0, tzinfo=UTC)

    result = engine.simulate(
        origin_lat=24.5,
        origin_lon=67.0,
        start_time=start_time,
        duration_hours=24,
        num_particles=100,
        oil_type="Medium Crude",
        spill_volume_m3=50.0,
        wind_speed_ms=8.0,
        wind_direction_deg=270.0,  # Westerly wind (blowing eastward)
        current_speed_ms=0.25,
        current_direction_deg=90.0,  # Eastward current
    )

    assert result.duration_hours == 24
    assert len(result.mass_balance_timeline) == 25  # T=0 to T=24
    assert result.final_evaporated_pct > 15.0  # Evaporative loss within 24h
    assert result.final_floating_pct > 0.0

    # Mass balance accounting at each step
    for snapshot in result.mass_balance_timeline:
        total_mass = (
            snapshot.evaporated_pct
            + snapshot.floating_pct
            + snapshot.beached_pct
            + snapshot.dispersed_pct
        )
        assert total_mass == pytest.approx(100.0, abs=1.0)

    # GeoJSON verification
    geojson = result.geojson
    assert geojson["type"] == "FeatureCollection"
    track = next(f for f in geojson["features"] if f["geometry"]["type"] == "LineString")
    assert "total_drift_km" in track["properties"]
    assert track["properties"]["total_drift_km"] > 5.0  # Significant advection occurred


def test_api_drift_simulate_custom() -> None:
    """Test POST /api/v1/drift/simulate with arbitrary coordinates."""
    payload = {
        "origin_lat": 22.0,
        "origin_lon": 68.0,
        "duration_hours": 24,
        "oil_type": "Light Crude",
        "spill_volume_m3": 100.0,
        "wind_speed_ms": 7.0,
        "wind_direction_deg": 180.0,
        "current_speed_ms": 0.20,
        "current_direction_deg": 90.0,
    }
    response = client.post("/api/v1/drift/simulate", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert "simulation_id" in data
    assert data["origin_lat"] == 22.0
    assert data["oil_type"] == "Light Crude"
    assert data["final_evaporated_pct"] > 0.0
    assert len(data["mass_balance_timeline"]) == 25

    # Retrieve by simulation_id
    sim_id = data["simulation_id"]
    get_resp = client.get(f"/api/v1/drift/simulations/{sim_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["simulation_id"] == sim_id


def test_api_candidate_drift_simulation() -> None:
    """Test candidate-specific drift endpoints."""
    # GET auto-runs or retrieves simulation for cand_test_standard_001
    get_resp = client.get("/api/v1/sar-candidates/cand_test_standard_001/drift")
    assert get_resp.status_code == 200
    data = get_resp.json()

    assert data["candidate_id"] == "cand_test_standard_001"
    assert "beaching_risk_level" in data
    assert "mass_balance_timeline" in data
    assert "geojson" in data

    # POST custom duration on candidate
    post_resp = client.post(
        "/api/v1/sar-candidates/cand_test_standard_001/drift",
        json={"duration_hours": 48, "oil_type": "Heavy Fuel Oil"},
    )
    assert post_resp.status_code == 200
    post_data = post_resp.json()
    assert post_data["duration_hours"] == 48
    assert post_data["oil_type"] == "Heavy Fuel Oil"

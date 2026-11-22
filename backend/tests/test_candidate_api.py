"""Unit and integration tests for SAR candidate review dashboard API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.services.candidate_service import seed_candidates_from_audit
from app.core.database import SessionLocal
from app.models.sar_candidate import SARCandidate, SARCandidateReview
from app.models.base import utcnow

from datetime import datetime, timezone

client = TestClient(app)


def seed_acceptance_fixtures(db) -> None:
    """Seed the 6 dedicated test acceptance fixtures and 7 review event records.
    
    This mirrors the browser acceptance test environment from Phase 13.3, bringing
    the total database count to 306 evaluated samples (207 eligible candidates,
    99 background non-detections).
    """
    test_records = [
        {
            "candidate_id": "cand_test_standard_001",
            "internal_sample_id": "cand_test_internal_001",
            "neutral_image_id": "patch_test_standard_001.jpg",
            "image_name": "nw-1556-09-000132.jpg",
            "safe_scene": "S1A_IW_GRDH_1SDV_20211202T020822_20211202T020847_040823_04D90C_TEST",
            "subset": "ow",
            "cluster": "test_cluster_std",
            "component_id": 1,
            "split": "test_acceptance_phase13_3",
            "latitude": 24.8500,
            "longitude": 67.0100,
            "is_coastal": True,
            "acquisition_timestamp": datetime(2021, 12, 2, 2, 8, 22, tzinfo=timezone.utc),
            "detector_name": "sar-oil-slick-v2.2",
            "model_version": "2.2.0-experimental",
            "raw_confidence": 0.942,
            "confidence_is_calibrated": False,
            "wind_speed_ms": 5.40,
            "wind_direction_deg": 145.0,
            "era5_source": "ECMWF ERA5 Reanalysis Archive",
            "grid_latitude": 24.75,
            "grid_longitude": 67.00,
            "temporal_offset_minutes": 8.0,
            "grid_distance_km": 11.2,
            "quality_status": "valid_collocation",
            "environmental_warnings": [],
            "screening_status": "candidate_requires_review",
            "retained_for_analyst_review": True,
            "review_status": "inconclusive",
            "latest_review_decision": "inconclusive",
            "latest_reviewer_id": "analyst_accept_01",
            "latest_reviewed_at": datetime(2026, 11, 4, 9, 15, tzinfo=timezone.utc),
        },
        {
            "candidate_id": "cand_test_lowwind_002",
            "internal_sample_id": "cand_test_internal_002",
            "neutral_image_id": "patch_test_lowwind_002.jpg",
            "image_name": "nw-1327-08-000078.jpg",
            "safe_scene": "S1A_IW_GRDH_1SDV_20210814T012345_040823_04D90C_TEST",
            "subset": "nw",
            "cluster": "test_cluster_lowwind",
            "component_id": 2,
            "split": "test_acceptance_phase13_3",
            "latitude": 18.9100,
            "longitude": 72.8200,
            "is_coastal": True,
            "acquisition_timestamp": datetime(2021, 8, 14, 1, 23, 45, tzinfo=timezone.utc),
            "detector_name": "sar-oil-slick-v2.2",
            "model_version": "2.2.0-experimental",
            "raw_confidence": 0.887,
            "confidence_is_calibrated": False,
            "wind_speed_ms": 1.80,
            "wind_direction_deg": 210.0,
            "era5_source": "ECMWF ERA5 Reanalysis Archive",
            "grid_latitude": 19.00,
            "grid_longitude": 72.75,
            "temporal_offset_minutes": 23.0,
            "grid_distance_km": 12.5,
            "quality_status": "valid_collocation",
            "environmental_warnings": [
                "Low wind speed (< 3.0 m/s): high risk of biogenic film or calm water look-alike",
                "Coastal proximity (< 25 km): potential coastal wind shadow or land runoff",
            ],
            "screening_status": "low_wind_ambiguity_review",
            "retained_for_analyst_review": True,
            "review_status": "rejected_lookalike",
            "latest_review_decision": "rejected_lookalike",
            "latest_reviewer_id": "analyst_accept_02",
            "latest_reviewed_at": datetime(2026, 11, 4, 9, 16, tzinfo=timezone.utc),
        },
        {
            "candidate_id": "cand_test_inconclusive_003",
            "internal_sample_id": "cand_test_internal_003",
            "neutral_image_id": "patch_test_inconclusive_003.jpg",
            "image_name": "nw-1515-09-000091.jpg",
            "safe_scene": "S1A_IW_GRDH_1SDV_20211115T034500_040823_04D90C_TEST",
            "subset": "ow",
            "cluster": "test_cluster_inconc",
            "component_id": 3,
            "split": "test_acceptance_phase13_3",
            "latitude": 12.9800,
            "longitude": 80.2500,
            "is_coastal": True,
            "acquisition_timestamp": datetime(2021, 11, 15, 3, 45, 0, tzinfo=timezone.utc),
            "detector_name": "sar-oil-slick-v2.2",
            "model_version": "2.2.0-experimental",
            "raw_confidence": 0.582,
            "confidence_is_calibrated": False,
            "wind_speed_ms": 4.10,
            "wind_direction_deg": 75.0,
            "era5_source": "ECMWF ERA5 Reanalysis Archive",
            "grid_latitude": 13.00,
            "grid_longitude": 80.25,
            "temporal_offset_minutes": 15.0,
            "grid_distance_km": 2.2,
            "quality_status": "valid_collocation",
            "environmental_warnings": [],
            "screening_status": "candidate_requires_review",
            "retained_for_analyst_review": True,
            "review_status": "inconclusive",
            "latest_review_decision": "inconclusive",
            "latest_reviewer_id": "analyst_accept_03",
            "latest_reviewed_at": datetime(2026, 11, 4, 9, 17, tzinfo=timezone.utc),
        },
        {
            "candidate_id": "cand_test_evidence_004",
            "internal_sample_id": "cand_test_internal_004",
            "neutral_image_id": "patch_test_evidence_004.jpg",
            "image_name": "nw-0785-05-000039.jpg",
            "safe_scene": "S1A_IW_GRDH_1SDV_20210920T041230_040823_04D90C_TEST",
            "subset": "nw",
            "cluster": "test_cluster_evid",
            "component_id": 4,
            "split": "test_acceptance_phase13_3",
            "latitude": 15.3500,
            "longitude": 73.8000,
            "is_coastal": True,
            "acquisition_timestamp": datetime(2021, 9, 20, 4, 12, 30, tzinfo=timezone.utc),
            "detector_name": "sar-oil-slick-v2.2",
            "model_version": "2.2.0-experimental",
            "raw_confidence": 0.725,
            "confidence_is_calibrated": False,
            "wind_speed_ms": 2.40,
            "wind_direction_deg": 190.0,
            "era5_source": "ECMWF ERA5 Reanalysis Archive",
            "grid_latitude": 15.25,
            "grid_longitude": 73.75,
            "temporal_offset_minutes": 12.0,
            "grid_distance_km": 13.1,
            "quality_status": "valid_collocation",
            "environmental_warnings": [
                "Low wind speed (< 3.0 m/s): high risk of biogenic film or calm water look-alike"
            ],
            "screening_status": "low_wind_ambiguity_review",
            "retained_for_analyst_review": True,
            "review_status": "requires_additional_evidence",
            "latest_review_decision": "requires_additional_evidence",
            "latest_reviewer_id": "analyst_accept_04",
            "latest_reviewed_at": datetime(2026, 11, 4, 9, 18, tzinfo=timezone.utc),
        },
        {
            "candidate_id": "cand_test_no_era5_005",
            "internal_sample_id": "cand_test_internal_005",
            "neutral_image_id": "patch_test_no_era5_005.jpg",
            "image_name": "nw-0940-06-000028.jpg",
            "safe_scene": "S1A_IW_GRDH_1SDV_20210510T120000_040823_04D90C_TEST",
            "subset": "ow",
            "cluster": "test_cluster_noera5",
            "component_id": 5,
            "split": "test_acceptance_phase13_3",
            "latitude": 10.0000,
            "longitude": 90.0000,
            "is_coastal": False,
            "acquisition_timestamp": datetime(2021, 5, 10, 12, 0, 0, tzinfo=timezone.utc),
            "detector_name": "sar-oil-slick-v2.2",
            "model_version": "2.2.0-experimental",
            "raw_confidence": 0.812,
            "confidence_is_calibrated": False,
            "wind_speed_ms": None,
            "wind_direction_deg": None,
            "era5_source": "ECMWF ERA5 Reanalysis Archive",
            "grid_latitude": None,
            "grid_longitude": None,
            "temporal_offset_minutes": None,
            "grid_distance_km": None,
            "quality_status": "reanalysis_pending",
            "environmental_warnings": ["ERA5 wind field unavailable for this spatiotemporal coordinate"],
            "screening_status": "candidate_requires_review",
            "retained_for_analyst_review": True,
            "review_status": "awaiting_review",
        },
        {
            "candidate_id": "cand_test_missing_image_006",
            "internal_sample_id": "cand_test_internal_006",
            "neutral_image_id": "patch_missing_nonexistent_9999.jpg",
            "image_name": "patch_missing_nonexistent_9999.jpg",
            "safe_scene": "S1A_IW_GRDH_1SDV_20210101T000000_TEST",
            "subset": "ow",
            "cluster": "test_cluster_missing",
            "component_id": 6,
            "split": "test_acceptance_phase13_3",
            "latitude": 11.5000,
            "longitude": 92.5000,
            "is_coastal": False,
            "acquisition_timestamp": datetime(2021, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            "detector_name": "sar-oil-slick-v2.2",
            "model_version": "2.2.0-experimental",
            "raw_confidence": 0.777,
            "confidence_is_calibrated": False,
            "wind_speed_ms": 6.20,
            "wind_direction_deg": 120.0,
            "era5_source": "ECMWF ERA5 Reanalysis Archive",
            "grid_latitude": 11.50,
            "grid_longitude": 92.50,
            "temporal_offset_minutes": 5.0,
            "grid_distance_km": 5.0,
            "quality_status": "valid_collocation",
            "environmental_warnings": [],
            "screening_status": "candidate_requires_review",
            "retained_for_analyst_review": True,
            "review_status": "awaiting_review",
        },
    ]

    for rec in test_records:
        cand = SARCandidate(**rec)
        db.add(cand)
    db.commit()

    # Add the 7 review event records matching the browser acceptance test
    cand_1 = db.query(SARCandidate).filter_by(candidate_id="cand_test_standard_001").first()
    cand_2 = db.query(SARCandidate).filter_by(candidate_id="cand_test_lowwind_002").first()
    cand_3 = db.query(SARCandidate).filter_by(candidate_id="cand_test_inconclusive_003").first()
    cand_4 = db.query(SARCandidate).filter_by(candidate_id="cand_test_evidence_004").first()

    revs = [
        # cand 001: 4 reviews (multi-review audit trail)
        SARCandidateReview(
            review_id="rev_test_seed_001a",
            candidate_id=cand_1.id,
            previous_status="awaiting_review",
            decision="potential_oil_slick",
            reviewer_id="analyst_accept_01",
            notes="Initial positive assessment",
            model_version="2.2.0-experimental",
            reviewed_at=datetime(2026, 11, 4, 9, 10, tzinfo=timezone.utc),
            created_at=datetime(2026, 11, 4, 9, 10, tzinfo=timezone.utc),
        ),
        SARCandidateReview(
            review_id="rev_test_seed_001b",
            candidate_id=cand_1.id,
            previous_status="potential_oil_slick",
            decision="rejected_lookalike",
            reviewer_id="analyst_accept_01",
            notes="Lookalike re-assessment",
            model_version="2.2.0-experimental",
            reviewed_at=datetime(2026, 11, 4, 9, 12, tzinfo=timezone.utc),
            created_at=datetime(2026, 11, 4, 9, 12, tzinfo=timezone.utc),
        ),
        SARCandidateReview(
            review_id="rev_test_seed_001c",
            candidate_id=cand_1.id,
            previous_status="rejected_lookalike",
            decision="requires_additional_evidence",
            reviewer_id="analyst_accept_01",
            notes="Requesting additional optical passes",
            model_version="2.2.0-experimental",
            reviewed_at=datetime(2026, 11, 4, 9, 14, tzinfo=timezone.utc),
            created_at=datetime(2026, 11, 4, 9, 14, tzinfo=timezone.utc),
        ),
        SARCandidateReview(
            review_id="rev_test_seed_001d",
            candidate_id=cand_1.id,
            previous_status="requires_additional_evidence",
            decision="inconclusive",
            reviewer_id="analyst_accept_01",
            notes="Final inconclusive determination",
            model_version="2.2.0-experimental",
            reviewed_at=datetime(2026, 11, 4, 9, 15, tzinfo=timezone.utc),
            created_at=datetime(2026, 11, 4, 9, 15, tzinfo=timezone.utc),
        ),
        # cand 002: 1 review
        SARCandidateReview(
            review_id="rev_test_seed_002",
            candidate_id=cand_2.id,
            previous_status="awaiting_review",
            decision="rejected_lookalike",
            reviewer_id="analyst_accept_02",
            notes="Low wind calm water lookalike rejected",
            model_version="2.2.0-experimental",
            reviewed_at=datetime(2026, 11, 4, 9, 16, tzinfo=timezone.utc),
            created_at=datetime(2026, 11, 4, 9, 16, tzinfo=timezone.utc),
        ),
        # cand 003: 1 review
        SARCandidateReview(
            review_id="rev_test_seed_003",
            candidate_id=cand_3.id,
            previous_status="awaiting_review",
            decision="inconclusive",
            reviewer_id="analyst_accept_03",
            notes="Inconclusive radar texture",
            model_version="2.2.0-experimental",
            reviewed_at=datetime(2026, 11, 4, 9, 17, tzinfo=timezone.utc),
            created_at=datetime(2026, 11, 4, 9, 17, tzinfo=timezone.utc),
        ),
        # cand 004: 1 review
        SARCandidateReview(
            review_id="rev_test_seed_004",
            candidate_id=cand_4.id,
            previous_status="awaiting_review",
            decision="requires_additional_evidence",
            reviewer_id="analyst_accept_04",
            notes="Awaiting high-resolution optical imagery",
            model_version="2.2.0-experimental",
            reviewed_at=datetime(2026, 11, 4, 9, 18, tzinfo=timezone.utc),
            created_at=datetime(2026, 11, 4, 9, 18, tzinfo=timezone.utc),
        ),
    ]
    for r in revs:
        db.add(r)
    db.commit()


@pytest.fixture(scope="module", autouse=True)
def setup_candidates() -> None:
    """Ensure candidate data and test acceptance fixtures are seeded into test database."""
    with SessionLocal() as db:
        seed_candidates_from_audit(db)
        seed_acceptance_fixtures(db)


class TestCandidateListingAndSummary:
    def test_list_candidates_unfiltered(self) -> None:
        resp = client.get("/api/v1/sar-candidates?limit=20")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "count" in data
        assert data["count"] >= 100
        assert len(data["items"]) == 20

        cand = data["items"][0]
        assert "candidate_id" in cand
        assert "raw_confidence" in cand
        assert "confidence_is_calibrated" in cand
        assert cand["confidence_is_calibrated"] is False
        assert "wind_speed_ms" in cand
        assert "screening_status" in cand
        assert "review_status" in cand
        assert "quality_status" in cand
        assert cand["quality_status"] in ("reanalysis_available", "valid_collocation", "reanalysis_pending")

        # Ground truth blinding: subset and cluster must NOT be exposed
        assert "subset" not in cand
        assert "cluster" not in cand
        assert cand["image_name"].startswith("patch_")

    def test_candidate_summary_reconciled_kpis(self) -> None:
        resp = client.get("/api/v1/sar-candidates/summary")
        assert resp.status_code == 200
        summary = resp.json()

        # Reconciled KPI properties
        assert "total_monitored_samples" in summary
        assert "total_evaluated_samples" in summary
        assert "eligible_candidates" in summary
        assert "standard_review_candidates" in summary
        assert "standard_wind_review" in summary
        assert "low_wind_ambiguity_candidates" in summary
        assert "low_wind_ambiguity" in summary
        assert "high_wind_ambiguity" in summary
        assert "wind_unavailable" in summary
        assert "no_candidate_detected" in summary
        assert "background_non_detections" in summary
        assert "awaiting_analyst_review" in summary
        assert "reviewed_candidates" in summary
        assert "decisions" in summary

        # Funnel mathematical reconciliation
        total = summary["total_evaluated_samples"]
        eligible = summary["eligible_candidates"]
        standard_wind = summary["standard_wind_review"]
        low_wind = summary["low_wind_ambiguity"]
        high_wind = summary["high_wind_ambiguity"]
        wind_unavail = summary["wind_unavailable"]
        no_cand = summary["no_candidate_detected"]
        awaiting = summary["awaiting_analyst_review"]
        reviewed = summary["reviewed_candidates"]

        # Mutually exclusive and exhaustive checks
        assert eligible == standard_wind + low_wind + high_wind + wind_unavail
        assert total == eligible + no_cand
        assert awaiting == eligible - reviewed

        # Exact database verified counts
        assert standard_wind == 136
        assert low_wind == 70
        assert high_wind == 0
        assert wind_unavail == 1
        assert no_cand == 99
        assert eligible == 207
        assert total == 306
        assert awaiting == 203
        assert reviewed == 4

    def test_benchmark_research_sample_isolation(self) -> None:
        """Verify the 300 research samples have 0 reviews and remain completely isolated from test fixtures."""
        with SessionLocal() as db:
            research_samples = (
                db.query(SARCandidate)
                .filter(SARCandidate.split != "test_acceptance_phase13_3")
                .all()
            )
            assert len(research_samples) == 300

            # 201 are eligible detected candidates, 99 are background non-detections
            eligible_research = [s for s in research_samples if s.retained_for_analyst_review]
            background_research = [s for s in research_samples if not s.retained_for_analyst_review]
            assert len(eligible_research) == 201
            assert len(background_research) == 99

            # Zero review events exist for research samples
            research_ids = [s.id for s in research_samples]
            research_reviews = (
                db.query(SARCandidateReview)
                .filter(SARCandidateReview.candidate_id.in_(research_ids))
                .count()
            )
            assert research_reviews == 0

            # Acceptance test fixtures count = 6, with 7 review events
            fixture_samples = (
                db.query(SARCandidate)
                .filter(SARCandidate.split == "test_acceptance_phase13_3")
                .all()
            )
            assert len(fixture_samples) == 6
            fixture_ids = [s.id for s in fixture_samples]
            fixture_reviews = (
                db.query(SARCandidateReview)
                .filter(SARCandidateReview.candidate_id.in_(fixture_ids))
                .count()
            )
            assert fixture_reviews == 7

    def test_high_wind_ambiguity_dynamic_update(self) -> None:
        """Verify high_wind_ambiguity metric dynamically updates when wind speed > 12.0 m/s."""
        # 1. Baseline check: 0 high-wind ambiguity candidates
        base_resp = client.get("/api/v1/sar-candidates/summary")
        assert base_resp.status_code == 200
        assert base_resp.json()["high_wind_ambiguity"] == 0

        # 2. Insert high-wind candidate (wind speed 14.5 m/s > 12.0 m/s threshold)
        with SessionLocal() as db:
            hw_cand = SARCandidate(
                candidate_id="cand_test_dynamic_high_wind_999",
                internal_sample_id="cand_test_hw_internal",
                neutral_image_id="patch_test_hw_999.jpg",
                image_name="patch_test_hw_999.jpg",
                safe_scene="S1A_IW_GRDH_HIGH_WIND_TEST",
                subset="ow",
                cluster="test_hw",
                component_id=99,
                split="test_acceptance",
                latitude=16.0,
                longitude=71.0,
                is_coastal=False,
                acquisition_timestamp=utcnow(),
                detector_name="sar-oil-slick-v2.2",
                model_version="2.2.0-experimental",
                raw_confidence=0.88,
                confidence_is_calibrated=False,
                wind_speed_ms=14.5,
                wind_direction_deg=270.0,
                era5_source="ECMWF ERA5 Reanalysis Archive",
                quality_status="valid_collocation",
                environmental_warnings=["High wind speed (14.50 m/s > 12.0 m/s): Dispersion risk"],
                screening_status="high_wind_ambiguity_review",
                retained_for_analyst_review=True,
                review_status="awaiting_review",
            )
            db.merge(hw_cand)
            db.commit()

        # 3. Verify dynamic summary update
        up_resp = client.get("/api/v1/sar-candidates/summary")
        assert up_resp.status_code == 200
        up_sum = up_resp.json()
        assert up_sum["high_wind_ambiguity"] == 1
        assert up_sum["high_wind_ambiguity_candidates"] == 1
        assert up_sum["eligible_candidates"] == 208
        assert up_sum["total_evaluated_samples"] == 307
        assert up_sum["awaiting_analyst_review"] == 204

        # 4. Clean up test candidate and verify rollback to 0
        with SessionLocal() as db:
            db.query(SARCandidate).filter_by(candidate_id="cand_test_dynamic_high_wind_999").delete()
            db.commit()

        reset_resp = client.get("/api/v1/sar-candidates/summary")
        assert reset_resp.status_code == 200
        assert reset_resp.json()["high_wind_ambiguity"] == 0

    def test_list_candidates_filters(self) -> None:
        # 1. Filter by screening_status
        resp = client.get("/api/v1/sar-candidates?screening_status=low_wind_ambiguity_review")
        assert resp.status_code == 200
        data = resp.json()
        assert all(it["screening_status"] == "low_wind_ambiguity_review" for it in data["items"])

        # 2. Filter by coastal
        resp_coastal = client.get("/api/v1/sar-candidates?is_coastal=true")
        assert resp_coastal.status_code == 200
        data_coastal = resp_coastal.json()
        assert all(it["is_coastal"] is True for it in data_coastal["items"])

        # 3. Search filter by neutral candidate ID or SAFE scene
        resp_search = client.get("/api/v1/sar-candidates?search=cand_s1")
        assert resp_search.status_code == 200
        data_search = resp_search.json()
        assert len(data_search["items"]) > 0

    def test_ground_truth_blinding_in_api(self) -> None:
        """Verify ground truth codes (ow, oc, nw, nc) and cluster names are never serialized."""
        resp = client.get("/api/v1/sar-candidates?limit=50")
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert "subset" not in item
            assert "cluster" not in item
            assert "internal_sample_id" not in item
            # Verify candidate_id is neutral
            assert item["candidate_id"].startswith("cand_s1_") or item["candidate_id"].startswith("cand_")
            # Verify image_name is neutral patch identifier
            assert item["image_name"].startswith("patch_")
            # Must not leak original category prefixes
            assert not item["image_name"].startswith(("ow-", "oc-", "nw-", "nc-"))

    def test_internal_sample_id_lookup_blocked_on_public_routes(self) -> None:
        """Verify internal_sample_id lookup is completely unavailable through public analyst routes."""
        # 1. Detail endpoint with internal ID must return 404
        resp_detail = client.get("/api/v1/sar-candidates/cand_nw_1556_09_000132")
        assert resp_detail.status_code == 404
        assert "not found" in resp_detail.json()["detail"].lower()

        resp_detail_2 = client.get("/api/v1/sar-candidates/cand_ow_0555")
        assert resp_detail_2.status_code == 404

        # 2. Image endpoint with internal ID must return 404
        resp_img = client.get("/api/v1/sar-candidates/cand_nw_1556_09_000132/image")
        assert resp_img.status_code == 404

        # 3. Review endpoint with internal ID must fail (400 or 404)
        resp_rev = client.post(
            "/api/v1/sar-candidates/cand_nw_1556_09_000132/reviews",
            json={"decision": "inconclusive", "reviewer_id": "test_analyst"},
        )
        assert resp_rev.status_code in (400, 404)

        # 4. Search query by internal ID pattern must yield 0 results
        resp_search = client.get("/api/v1/sar-candidates?search=cand_nw_")
        assert resp_search.status_code == 200
        assert len(resp_search.json()["items"]) == 0


class TestCandidateDetailAndReviews:
    def test_candidate_detail_and_interpretation(self) -> None:
        # Fetch one candidate from listing
        list_resp = client.get("/api/v1/sar-candidates?limit=1")
        cand_id = list_resp.json()["items"][0]["candidate_id"]

        resp = client.get(f"/api/v1/sar-candidates/{cand_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["candidate_id"] == cand_id
        assert "interpretation" in detail
        assert len(detail["interpretation"]) > 20
        assert "reviews" in detail
        assert isinstance(detail["reviews"], list)
        assert "subset" not in detail
        assert "cluster" not in detail
        assert "internal_sample_id" not in detail

    def test_candidate_detail_not_found(self) -> None:
        resp = client.get("/api/v1/sar-candidates/cand_nonexistent_999999")
        assert resp.status_code == 404

    def test_candidate_review_lifecycle_and_audit_trail(self) -> None:
        # Pick an awaiting_review candidate
        list_resp = client.get("/api/v1/sar-candidates?review_status=awaiting_review&limit=1")
        cand_id = list_resp.json()["items"][0]["candidate_id"]

        # 1. Submit review action: potential_oil_slick
        payload_1 = {
            "decision": "potential_oil_slick",
            "reviewer_id": "test_analyst_01",
            "notes": "Clear dark patch with high contrast and sharp boundary.",
            "evidence_references": {"optical_glint": "checked_inconclusive"},
        }
        rev_resp_1 = client.post(f"/api/v1/sar-candidates/{cand_id}/reviews", json=payload_1)
        assert rev_resp_1.status_code == 200
        detail_1 = rev_resp_1.json()
        assert detail_1["review_status"] == "potential_oil_slick"
        assert detail_1["latest_review_decision"] == "potential_oil_slick"
        assert detail_1["latest_reviewer_id"] == "test_analyst_01"
        assert "internal_sample_id" not in detail_1
        assert "subset" not in detail_1
        assert "cluster" not in detail_1
        assert len(detail_1["reviews"]) >= 1
        latest_rev = detail_1["reviews"][0]
        assert latest_rev["decision"] == "potential_oil_slick"
        assert latest_rev["previous_status"] == "awaiting_review"
        assert latest_rev["notes"] == "Clear dark patch with high contrast and sharp boundary."

        # 2. Subsequent review update: rejected_lookalike
        payload_2 = {
            "decision": "rejected_lookalike",
            "reviewer_id": "test_senior_analyst",
            "notes": "Secondary Sentinel-2 NDCI analysis confirmed algal bloom.",
            "evidence_references": {"sentinel2_ndci": 0.42},
        }
        rev_resp_2 = client.post(f"/api/v1/sar-candidates/{cand_id}/reviews", json=payload_2)
        assert rev_resp_2.status_code == 200
        detail_2 = rev_resp_2.json()
        assert detail_2["review_status"] == "rejected_lookalike"
        assert len(detail_2["reviews"]) == len(detail_1["reviews"]) + 1
        new_rev = detail_2["reviews"][0]
        assert new_rev["decision"] == "rejected_lookalike"
        assert new_rev["previous_status"] == "potential_oil_slick"
        assert new_rev["reviewer_id"] == "test_senior_analyst"
        # Confirm previous review remains completely unmodified
        prior_rev = detail_2["reviews"][1]
        assert prior_rev["review_id"] == latest_rev["review_id"]
        assert prior_rev["decision"] == "potential_oil_slick"
        assert prior_rev["notes"] == "Clear dark patch with high contrast and sharp boundary."

    def test_invalid_review_decision_rejected(self) -> None:
        list_resp = client.get("/api/v1/sar-candidates?limit=1")
        cand_id = list_resp.json()["items"][0]["candidate_id"]

        bad_payload = {
            "decision": "not_a_valid_decision",
            "reviewer_id": "test_analyst",
        }
        resp = client.post(f"/api/v1/sar-candidates/{cand_id}/reviews", json=bad_payload)
        assert resp.status_code == 400
        assert "Invalid review decision" in resp.json()["detail"]


class TestCandidateAuditHardening:
    def test_cannot_delete_candidate_with_reviews_on_delete_restrict(self) -> None:
        """Verify PostgreSQL foreign key ON DELETE RESTRICT prevents deleting reviewed candidates."""
        with SessionLocal() as db:
            # Clean up test rows if present
            db.query(SARCandidateReview).filter_by(review_id="rev_test_restrict_audit_01").delete()
            db.query(SARCandidate).filter_by(candidate_id="cand_test_restrict_verify").delete()
            db.commit()

            # 1. Create a dedicated test candidate
            test_cand = SARCandidate(
                candidate_id="cand_test_restrict_verify",
                internal_sample_id="cand_internal_restrict_01",
                neutral_image_id="patch_test_restrict.jpg",
                image_name="test_restrict.jpg",
                safe_scene="TEST_SAFE_SCENE",
                subset="ow",
                cluster="oil",
                split="test_acceptance",
                latitude=18.0,
                longitude=72.0,
                is_coastal=False,
                acquisition_timestamp=utcnow(),
                detector_name="sar-oil-slick-v2.2",
                model_version="2.2.0-experimental",
                raw_confidence=0.91,
                screening_status="candidate_requires_review",
                review_status="awaiting_review",
            )
            db.add(test_cand)
            db.commit()

            cand = db.query(SARCandidate).filter_by(candidate_id="cand_test_restrict_verify").first()
            assert cand is not None

            # 2. Add an audit review record referencing the candidate
            review = SARCandidateReview(
                review_id="rev_test_restrict_audit_01",
                candidate_id=cand.id,
                previous_status="awaiting_review",
                decision="potential_oil_slick",
                reviewer_id="analyst_audit_tester",
                reviewed_at=utcnow(),
                model_version="2.2.0-experimental",
                notes="Audit protection verification test review",
                created_at=utcnow(),
            )
            db.add(review)
            db.commit()

            # 3. Attempt to delete candidate: MUST raise IntegrityError due to ON DELETE RESTRICT
            with pytest.raises(IntegrityError) as exc_info:
                db.delete(cand)
                db.commit()

            # Verify foreign key constraint violation
            err_str = str(exc_info.value).lower()
            assert "foreign key" in err_str or "sar_candidate_reviews_candidate_id_fkey" in err_str
            db.rollback()

            # Clean up review first, then candidate
            db.query(SARCandidateReview).filter_by(review_id="rev_test_restrict_audit_01").delete()
            db.delete(cand)
            db.commit()


class TestCandidateImageAndMapPoints:
    def test_candidate_image_serving(self) -> None:
        list_resp = client.get("/api/v1/sar-candidates?limit=1")
        cand_id = list_resp.json()["items"][0]["candidate_id"]

        resp = client.get(f"/api/v1/sar-candidates/{cand_id}/image")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert len(resp.content) > 100
        # Verify content-disposition filename is blinded
        cd = resp.headers.get("content-disposition", "")
        if cd:
            assert not any(cd.startswith(p) for p in ("ow-", "oc-", "nw-", "nc-"))

    def test_candidate_map_points_geojson_format(self) -> None:
        resp = client.get("/api/v1/sar-candidates/map-points")
        assert resp.status_code == 200
        points = resp.json()
        assert isinstance(points, list)
        assert len(points) >= 100

        p = points[0]
        assert "candidate_id" in p
        assert "latitude" in p
        assert "longitude" in p
        assert "map_state" in p
        assert "color" in p
        assert "internal_sample_id" not in p
        assert "subset" not in p
        assert "cluster" not in p
        assert p["image_name"].startswith("patch_")
        assert p["map_state"] in (
            "standard_candidate",
            "low_wind_ambiguity",
            "reviewed_potential_oil",
            "reviewed_rejected",
            "reviewed_inconclusive",
            "reviewed_requires_evidence",
        )

    def test_raw_confidence_preservation(self) -> None:
        list_resp = client.get("/api/v1/sar-candidates?limit=5")
        for cand in list_resp.json()["items"]:
            assert 0.0 <= cand["raw_confidence"] <= 1.0
            assert cand["confidence_is_calibrated"] is False
            detail_resp = client.get(f"/api/v1/sar-candidates/{cand['candidate_id']}")
            assert detail_resp.json()["raw_confidence"] == cand["raw_confidence"]

    def test_missing_era5_candidate_handling(self) -> None:
        with SessionLocal() as db:
            missing_cand = SARCandidate(
                candidate_id="cand_test_missing_wind_001",
                neutral_image_id="patch_test_missing.jpg",
                image_name="test_missing.jpg",
                subset="ow",
                cluster="oil",
                split="test_split",
                latitude=15.0,
                longitude=70.0,
                is_coastal=False,
                acquisition_timestamp=utcnow(),
                detector_name="sar-oil-slick-v2.2",
                model_version="2.2.0-experimental",
                raw_confidence=0.82,
                confidence_is_calibrated=False,
                wind_speed_ms=None,
                wind_direction_deg=None,
                era5_source="ECMWF ERA5",
                quality_status="missing",
                environmental_warnings=["Wind context unverified: Missing ERA5 reanalysis"],
                screening_status="candidate_requires_review",
                retained_for_analyst_review=True,
                review_status="awaiting_review",
            )
            db.merge(missing_cand)
            db.commit()

        resp = client.get("/api/v1/sar-candidates/cand_test_missing_wind_001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["wind_speed_ms"] is None
        assert data["quality_status"] == "missing"
        assert data["screening_status"] == "candidate_requires_review"
        assert data["retained_for_analyst_review"] is True
        assert any("Wind context unverified" in w for w in data["environmental_warnings"])

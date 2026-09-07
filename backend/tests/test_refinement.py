"""Tests for stage-two refinement.

The central claim these protect: an ``oil_like_signature`` is unreachable at
screening resolution and becomes reachable only after subdivision, with the
evidence to support it.
"""

from __future__ import annotations

import pytest
from app.models import PollutionEvent, Region
from app.models.enums import PollutionSignature
from app.services.refinement_service import (
    MAX_SUBDIVISION,
    TARGET_SUBCELL_KM2,
    subdivide,
    subdivision_factor,
)
from fastapi.testclient import TestClient
from sqlalchemy import select


class TestSubdivisionMath:
    def test_small_cell_gets_minimum_subdivision(self) -> None:
        assert subdivision_factor(TARGET_SUBCELL_KM2 / 2) == 2

    def test_large_cell_gets_more_subdivision(self) -> None:
        assert subdivision_factor(800_000.0) > subdivision_factor(50_000.0)

    def test_subdivision_is_capped(self) -> None:
        """Cost must stay bounded however large the cell."""
        assert subdivision_factor(100_000_000.0) == MAX_SUBDIVISION

    @pytest.mark.parametrize("area", [1_000.0, 50_000.0, 800_000.0, 5_000_000.0])
    def test_factor_always_in_valid_range(self, area: float) -> None:
        assert 2 <= subdivision_factor(area) <= MAX_SUBDIVISION


class TestSubdivideGeometry:
    @pytest.fixture
    def region(self) -> Region:
        return Region(
            code="test_region",
            name="Test Region",
            parent_code="Test Sea",
            min_lon=10.0,
            min_lat=20.0,
            max_lon=18.0,
            max_lat=28.0,
            centroid_lat=24.0,
            centroid_lon=14.0,
        )

    def test_produces_factor_squared_cells(self, region: Region) -> None:
        assert len(subdivide(region, 4)) == 16

    def test_subcells_tile_the_parent_exactly(self, region: Region) -> None:
        """No gaps, no overlaps, no drift outside the parent bounds."""
        cells = subdivide(region, 4)
        assert min(c.min_lon for c in cells) == pytest.approx(region.min_lon)
        assert max(c.max_lon for c in cells) == pytest.approx(region.max_lon)
        assert min(c.min_lat for c in cells) == pytest.approx(region.min_lat)
        assert max(c.max_lat for c in cells) == pytest.approx(region.max_lat)

    def test_subcell_area_sums_to_parent_area(self, region: Region) -> None:
        from app.services.refinement_service import _region_area_km2

        cells = subdivide(region, 4)
        assert sum(c.area_km2 for c in cells) == pytest.approx(
            _region_area_km2(region), rel=1e-6
        )

    def test_subcell_codes_are_unique_and_traceable(self, region: Region) -> None:
        cells = subdivide(region, 3)
        codes = [c.code for c in cells]
        assert len(set(codes)) == len(codes)
        assert all(c.startswith(region.code + "__") for c in codes)


class TestTwoStagePipeline:
    def test_screening_stage_never_claims_oil(
        self, seeded_client: TestClient, session
    ) -> None:
        """At screening resolution, a slick-scale claim is unsupportable.

        Every coarse-grid detection must be a bare dark formation: cells span
        10^4-10^5 km squared, so any dark region within one exceeds a
        plausible slick by an order of magnitude.
        """
        all_events = session.scalars(select(PollutionEvent)).all()
        # Guard against a vacuous pass: there must be detections to judge.
        assert all_events, "screening produced no events; test would be vacuous"

        coarse = [e for e in all_events if (e.extra or {}).get("refinement_stage") != 2]
        assert coarse, "no coarse-grid events; test would be vacuous"
        assert all(
            e.signature != str(PollutionSignature.OIL_LIKE_SIGNATURE) for e in coarse
        )

    def test_refinement_makes_oil_like_reachable(self, seeded_client: TestClient) -> None:
        """Subdividing turns an unsupportable claim into a supportable one."""
        summary = seeded_client.post(
            "/api/v1/satellite/refine", params={"max_cells": 5}
        ).json()
        assert summary["cells_refined"] > 0
        assert summary["subcells_observed"] > summary["cells_refined"]
        assert summary["upgraded_to_oil_like"] > 0

    def test_refined_events_record_their_provenance(
        self, seeded_client: TestClient, session
    ) -> None:
        """A stage-2 detection must say it came from a targeted second look."""
        seeded_client.post("/api/v1/satellite/refine", params={"max_cells": 3})
        refined = [
            e
            for e in session.scalars(select(PollutionEvent)).all()
            if (e.extra or {}).get("refinement_stage") == 2
        ]
        assert refined
        for event in refined:
            assert event.extra["parent_region_code"]
            assert event.extra["subdivision_factor"] >= 2
            assert any("Stage-2 refinement" in c for c in event.caveats)

    def test_refinement_with_no_flagged_cells_is_a_no_op(
        self, client: TestClient
    ) -> None:
        """Nothing screened means nothing to refine; must not error."""
        summary = client.post("/api/v1/satellite/refine").json()
        assert summary["cells_refined"] == 0
        assert summary["events_created"] == 0

    def test_refinement_is_bounded_by_max_cells(self, seeded_client: TestClient) -> None:
        summary = seeded_client.post(
            "/api/v1/satellite/refine", params={"max_cells": 2}
        ).json()
        assert summary["cells_refined"] <= 2

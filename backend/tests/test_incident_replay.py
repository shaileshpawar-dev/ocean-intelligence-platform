"""A negative replay must reach the page exactly as a positive would.

Screening open water and finding nothing proves little: a detector that
always answered "no" behaves identically. Replaying a documented incident is
the test that distinguishes them -- and it is only a test if the result is
published whichever way it comes out.

So these pin the two things that would quietly turn it back into decoration:
the result is stored and served regardless of outcome, and the conditions
that weaken a negative travel with it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RESULT = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "raw"
    / "incident_replay"
    / "msc_elsa_3.json"
)


@pytest.fixture(scope="module")
def replay() -> dict:
    if not RESULT.exists():
        pytest.skip("replay not run in this checkout")
    return json.loads(RESULT.read_text(encoding="utf-8"))


class TestTheIncidentIsCited:
    """Every figure traceable to an official document."""

    def test_it_names_its_source(self, replay):
        citation = replay["incident"]["citation"]

        assert "Kerala State Disaster Management Authority" in citation
        assert "SITREP" in citation
        assert "sdma.kerala.gov.in" in citation

    def test_the_position_is_the_one_in_the_sitrep(self, replay):
        incident = replay["incident"]

        assert incident["position_text"] == "09\u00b018.75'N 076\u00b008.16'E"
        assert abs(incident["latitude"] - 9.3125) < 1e-6
        assert abs(incident["longitude"] - 76.136) < 1e-3
        assert incident["imo"] == "9123221"

    def test_the_label_names_the_incident_and_date(self, replay):
        assert replay["label"].startswith("Historical incident replay:")
        assert "MSC ELSA 3" in replay["label"]
        assert "2025-05-25" in replay["label"]


class TestANegativeIsPublishedAnyway:
    """The property that makes this validation rather than decoration."""

    def test_the_result_exists_whatever_the_outcome(self, replay):
        assert replay["verdict"]
        assert replay["screening"]["tiles_screened"] > 0

    def test_a_negative_states_why_it_is_weak_evidence(self, replay):
        if replay["screening"]["detected"]:
            pytest.skip("this replay detected something")

        interpretation = replay["interpretation"].lower()

        assert "does not establish that no slick was present" in interpretation
        for reason in ("dispersant", "weathers", "distribution"):
            assert reason in interpretation, f"missing: {reason}"

    def test_the_conditions_travel_with_the_result(self, replay):
        """Wind decides what a negative means. Below ~3 m/s a flat sea looks
        like oil; above ~8 m/s roughening erases a slick's contrast."""
        passes = replay["screening"]["passes"]

        assert passes, "a replay with no passes is no coverage, not a negative"
        assert any(p.get("wind_speed_ms") is not None for p in passes)
        assert all("days_after" in p for p in passes)

    def test_the_domain_gap_is_recorded_beside_the_scores(self, replay):
        screening = replay["screening"]

        assert screening["training_tile_mean"]
        assert screening["model"] == "sar-oil-slick-v2.2"
        assert "dB" in screening["window"]
